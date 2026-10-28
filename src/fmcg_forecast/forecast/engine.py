"""The forecast engine v1 — stated, decomposed, computed (Law 1).

For one (commodity x market) series the engine produces a 90-day
daily forecast as a stored artefact. The method is stated here in
full; there is no other method:

1. **Baseline.** OLS of log price on [1, years since the first
   observed day, sin/cos of day-of-year] over all price history up to
   ``as_of``. The forecast baseline is that fitted surface projected
   forward.
2. **Driver contributions.** The baseline's in-sample residuals are
   regressed (no intercept) on standardised driver inputs:
   arrivals = z(log arrivals), stock cover = z(stock level),
   trade flow = z(import flow - export flow), weather = the raw
   index. Each coefficient is one driver's stated effect. A driver's
   future input path is its last observed input decayed by its
   measured lag-1 persistence, ``x(h) = x_last * rho**h`` — today's
   pressure fading at the rate history says it fades.
3. **Attribution.** Log contributions are converted to INR by
   sequential (telescoping) attribution in the stated order
   (arrivals, stock, trade, weather, events): each driver is credited
   with the price move its log contribution makes on top of the
   drivers before it. Baseline + contributions + events therefore
   equals the total exactly, to the paisa, and a verifier can
   re-perform the sum (see verify.py).
4. **Intervals.** Full-model residuals over a rolling 365-observation
   window give empirical q10/q90; they are propagated to horizon h by
   the AR growth factor ``sqrt((1-rho^2h)/(1-rho^2))`` from the
   residuals' own lag-1 autocorrelation, then widened by the series'
   sparsity multiplier ``sqrt(calendar days / observed days)`` —
   sparse series (coffee) get honestly wide bands (Law 7).

Data discipline: the engine reads only observations dated on or
before ``as_of``, through the store port. An ``as_of`` inside the
sealed grading window (the manifest's future window) is refused
unless the caller explicitly invokes the backtest path — and even
then the engine can only see the observations table, never the
sealed rows behind the truth store (which this package never
imports).

Events: the engine accepts declared event adjustments as an input
slot (a per-day log-price path per event). Round 2 shipped the
slot empty; the event registry fills it in R5 (Law 4). Each event
is telescoped separately, in the order given, after the drivers:
the events line records every event's own INR contribution path
(``per_event`` in its input summary), so a shocked forecast shows
each shock as its own named line instead of one absorbed total.
An adjustment may also carry an interval widening factor: on any
day where an event's path is non-zero, the interval growth factor
is multiplied by the widest active factor — the event pack states
the factor (1.25); the engine merely applies what it is handed.

Sentiment (R4, Law 3): the engine accepts a sentiment input — the
weekly index carried daily, supplied by the sentiment service —
and treats it as one more driver: standardised alignment on the
common observed days, its coefficient estimated by the same
residual regression, its future path the last index value decayed
at its measured persistence. But the line is earned, not assumed:
the pack's estimation floors ride on the input, and when the
index history is too thin, too short-spanned or too stale, the
engine records a ``not_estimable`` sentiment line with zero
contribution and the failing floor named — following the same
honesty pattern as coffee's named data gaps. When no sentiment
input is supplied at all, the engine behaves exactly as it did
before R4.

Scenarios (R6, Law 5): the engine accepts driver shifts and a
sentiment start override — perturbations of the future INPUT
paths, computed by the scenario layer from the pack's bounded
levers. Estimation never sees them (coefficients, persistence
and the baseline are history's), the telescoping attribution
runs over the shifted paths exactly as over unshifted ones, and
each shifted line records the application in its summary. A
shift for a driver the run did not estimate is refused. With no
shifts handed in, the engine behaves exactly as it did before R6.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from typing import Literal, Protocol

import numpy as np
from pydantic import BaseModel, Field

from fmcg_forecast.catalogue import BY_NAME, missing_drivers
from fmcg_forecast.forecast.models import (
    ATTRIBUTION_ORDER,
    FORECAST_DAYS,
    HORIZONS,
    BaselineMethod,
    ContributionLine,
    DriverMethod,
    Forecast,
    ForecastDay,
    ForecastMethod,
    HorizonSummary,
    ResidualMethod,
    SparsityMethod,
)
from fmcg_forecast.models import Manifest, Observation

ENGINE_VERSION = "1.0.0"
# The estimation floor is stated in observations AND calendar span:
# a sparse series (coffee reports twice a week) accumulates
# observations slowly but can still carry two full seasonal cycles,
# while a dense series over one short season cannot state a
# seasonality at all.
MIN_HISTORY_OBS = 250
MIN_HISTORY_SPAN_DAYS = 730
RESIDUAL_WINDOW_OBS = 365

# Line name -> (source drivers, stated transform label). trade_flow is
# one line built from two reported drivers (Law: contributions are
# per driver family — supply arrivals, stock cover, trade, weather).
_TRANSFORMS = {
    "arrivals": "z of log arrivals",
    "stock_level": "z of stock level",
    "trade_flow": "z of (import flow - export flow)",
    "weather_index": "raw weather index (-1..1)",
    "sentiment": "weekly sentiment index carried daily (raw, -1..1)",
}


class ForecastError(RuntimeError):
    """Base for engine refusals."""


class SealedWindowRefusal(ForecastError):
    """as_of sits inside the sealed grading window without the
    backtest path being invoked."""


class InsufficientHistoryError(ForecastError):
    """Too little history to state the method over."""


class UnknownSeriesError(ForecastError):
    """The commodity/market series does not exist in the catalogue."""


class EventAdjustment(BaseModel):
    """A declared event's per-day log-price adjustment path.

    The R5 event registry produces these from MarketEvents (the
    pack's stated path rule); the engine validates and applies any
    path it is handed, telescoping each event separately.
    """

    event_id: str
    path: list[float] = Field(description="Log-price adjustment per horizon day")
    interval_widening: float = Field(
        default=1.0,
        description="Interval growth multiplier on days where this "
        "event's path is non-zero (the event pack states 1.25; "
        "1.0 = no widening)",
    )


class DriverShift(BaseModel):
    """A scenario lever's hand-off to the engine (R6, Law 5).

    A shift moves a driver's future INPUT path — never the
    output price: ``add`` adds ``value`` (in the driver's input
    units) to the path on every horizon day; ``add_clip`` adds
    and then clips the path to the stated range (the weather
    index's own bounds). The scenario layer computes the value
    from the lever by the scenario pack's stated conversion and
    records it on the run; the engine merely applies what it is
    handed, and records the application on the line's summary so
    the artefact states that its path was shifted, and by how
    much. With no shifts handed in, the engine behaves exactly
    as it did before R6.
    """

    driver: str = Field(description="The contribution line whose input path moves")
    mode: Literal["add", "add_clip"]
    value: float = Field(description="The shift in the driver's input units")
    clip_min: float | None = None
    clip_max: float | None = None


class SentimentInput(BaseModel):
    """The sentiment service's hand-off to the engine (R4, Law 3).

    ``daily`` is the weekly index carried to each day of its week
    (ISO date -> value), restricted to fully-ended weeks. The
    estimation floors and the pack version ride along from the
    sentiment pack, so the engine judges estimability against the
    pack's stated bars and records them on the line it produces.
    ``cited_item_ids`` are the strongest items behind the latest
    index whose readings agree with its sign — the only items
    commentary may cite for the latest reading.
    """

    daily: dict[str, float] = Field(
        description="ISO date -> sentiment index value for that day"
    )
    cited_item_ids: list[str] = Field(default_factory=list)
    latest_index_value: float | None = None
    latest_week_start: date | None = None
    pack_version: str = ""
    min_aligned_days: int = Field(description="Estimation floor from the sentiment pack")
    min_span_days: int
    recency_days: int


class SeriesSource(Protocol):
    """The read surface the engine is allowed: observations only."""

    def series(
        self,
        commodity: str,
        market: str,
        driver: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Observation]: ...


def _z(values: np.ndarray) -> np.ndarray:
    mean = float(values.mean())
    std = float(values.std())
    if std == 0.0:
        return np.zeros_like(values)
    return (values - mean) / std


def _lag1_autocorr(values: np.ndarray) -> float:
    if len(values) < 3 or float(values.std()) == 0.0:
        return 0.0
    return float(np.corrcoef(values[:-1], values[1:])[0, 1])


def _driver_inputs(
    source: SeriesSource,
    commodity: str,
    market: str,
    as_of: date,
    price_dates: list[date],
    sentiment_daily: dict[date, float] | None = None,
) -> tuple[dict[str, np.ndarray], list[date]]:
    """Standardised driver regressors aligned to common observed days.

    Sentiment is a pseudo-driver: its raw series is the index the
    sentiment service computed (per commodity, carried daily), not
    an observation, so it arrives as an argument rather than
    through the store port. It aligns by the same common-days rule
    and enters raw, like the weather index.
    """
    spec = BY_NAME[commodity]
    raw: dict[str, dict[date, float]] = {}

    def load(driver: str) -> dict[date, float]:
        rows = source.series(commodity, market, driver, None, as_of)
        return {r.obs_date: float(r.value) for r in rows}

    wanted: dict[str, list[str]] = {}
    if "arrivals" in spec.drivers:
        wanted["arrivals"] = ["arrivals"]
    if "stock_level" in spec.drivers:
        wanted["stock_level"] = ["stock_level"]
    if "import_flow" in spec.drivers and "export_flow" in spec.drivers:
        wanted["trade_flow"] = ["import_flow", "export_flow"]
    if "weather_index" in spec.drivers:
        wanted["weather_index"] = ["weather_index"]
    if sentiment_daily is not None:
        wanted["sentiment"] = ["sentiment"]
        raw["sentiment"] = dict(sentiment_daily)

    common = set(price_dates)
    for source_drivers in wanted.values():
        for driver in source_drivers:
            if driver not in raw:
                raw[driver] = load(driver)
            common &= set(raw[driver])
    days = sorted(common)

    inputs: dict[str, np.ndarray] = {}
    for line, source_drivers in wanted.items():
        if line == "arrivals":
            values = np.array([math.log(raw["arrivals"][d]) for d in days])
            inputs[line] = _z(values)
        elif line == "stock_level":
            values = np.array([raw["stock_level"][d] for d in days])
            inputs[line] = _z(values)
        elif line == "trade_flow":
            values = np.array(
                [raw["import_flow"][d] - raw["export_flow"][d] for d in days]
            )
            inputs[line] = _z(values)
        elif line == "weather_index":
            inputs[line] = np.array([raw["weather_index"][d] for d in days])
        elif line == "sentiment":
            inputs[line] = np.array([raw["sentiment"][d] for d in days])
    return inputs, days


def run_engine(
    source: SeriesSource,
    manifest: Manifest,
    commodity: str,
    market: str,
    as_of: date,
    *,
    via_backtest: bool = False,
    event_adjustments: list[EventAdjustment] | tuple[EventAdjustment, ...] = (),
    sentiment_input: SentimentInput | None = None,
    driver_shifts: list[DriverShift] | tuple[DriverShift, ...] = (),
    sentiment_start_override: float | None = None,
) -> Forecast:
    """Run the stated method and return the forecast artefact (draft)."""
    if as_of >= manifest.future_start and not via_backtest:
        raise SealedWindowRefusal(
            f"as_of {as_of.isoformat()} is inside the sealed grading window "
            f"({manifest.future_start.isoformat()}..{manifest.future_end.isoformat()}); "
            "the engine estimates on history only — invoke the backtest path "
            "explicitly if that is what this run is"
        )
    spec = BY_NAME.get(commodity)
    if spec is None or market not in {m.market for m in spec.markets}:
        raise UnknownSeriesError(f"no such series: {commodity}/{market}")

    price_rows = source.series(commodity, market, "modal_price", None, as_of)
    if not price_rows:
        raise UnknownSeriesError(f"no price history for {commodity}/{market}")
    span_days = (as_of - price_rows[0].obs_date).days + 1
    if len(price_rows) < MIN_HISTORY_OBS or span_days < MIN_HISTORY_SPAN_DAYS:
        raise InsufficientHistoryError(
            f"{commodity}/{market} has {len(price_rows)} observed price days "
            f"spanning {span_days} calendar days up to {as_of.isoformat()}; "
            f"the stated method needs at least {MIN_HISTORY_OBS} observations "
            f"spanning at least {MIN_HISTORY_SPAN_DAYS} days (two seasonal cycles)"
        )

    days_obs = [r.obs_date for r in price_rows]
    y = np.log(np.array([float(r.value) for r in price_rows]))
    anchor = days_obs[0]

    # --- sentiment estimability (R4): the line is earned ----------
    # The pack's floors ride on the input: enough index-covered
    # price days, spanning enough calendar time, with the newest
    # covered day inside the recency window. Failing any floor
    # records a not-estimable line (zero contribution, reason
    # named) instead of estimating on a corpus too thin to carry
    # the driver — the coffee pattern, applied to sentiment.
    sentiment_daily: dict[date, float] | None = None
    sentiment_not_estimable: str | None = None
    sentiment_counts = {"aligned_days": 0, "span_days": 0}
    if sentiment_input is not None:
        parsed = {
            date.fromisoformat(k): float(v)
            for k, v in sentiment_input.daily.items()
        }
        covered = [d for d in days_obs if d in parsed]
        aligned = len(covered)
        span = (covered[-1] - covered[0]).days + 1 if covered else 0
        newest_age = (as_of - covered[-1]).days if covered else None
        sentiment_counts = {"aligned_days": aligned, "span_days": span}
        failures: list[str] = []
        if aligned < sentiment_input.min_aligned_days:
            failures.append(
                f"only {aligned} index-covered price days (the pack's "
                f"floor is {sentiment_input.min_aligned_days})"
            )
        if span < sentiment_input.min_span_days:
            failures.append(
                f"the covered days span {span} calendar days (the "
                f"pack's floor is {sentiment_input.min_span_days})"
            )
        if newest_age is None:
            failures.append("no index-covered price day at all")
        elif newest_age > sentiment_input.recency_days:
            failures.append(
                f"the newest index-covered day is {newest_age} days "
                f"before as_of (the pack allows {sentiment_input.recency_days})"
            )
        if failures:
            sentiment_not_estimable = "; ".join(failures)
        else:
            sentiment_daily = parsed

    def baseline_design(dates: list[date]) -> np.ndarray:
        years = np.array([(d - anchor).days / 365.25 for d in dates])
        angle = np.array(
            [2.0 * math.pi * d.timetuple().tm_yday / 365.25 for d in dates]
        )
        return np.column_stack(
            [np.ones(len(dates)), years, np.sin(angle), np.cos(angle)]
        )

    design = baseline_design(days_obs)
    base_coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    resid1 = y - design @ base_coef

    inputs, reg_days = _driver_inputs(
        source, commodity, market, as_of, days_obs, sentiment_daily
    )
    reg_index = {d: i for i, d in enumerate(days_obs)}
    reg_rows = [reg_index[d] for d in reg_days]
    line_names = [name for name in ATTRIBUTION_ORDER if name in inputs]
    if line_names:
        x_mat = np.column_stack([inputs[name] for name in line_names])
        driver_coef, *_ = np.linalg.lstsq(x_mat, resid1[reg_rows], rcond=None)
        full_resid = resid1[reg_rows] - x_mat @ driver_coef
    else:  # a series with no drivers at all: baseline only
        driver_coef = np.zeros(0)
        full_resid = resid1[reg_rows]

    coefficients = {
        name: float(driver_coef[i]) for i, name in enumerate(line_names)
    }
    persistence = {
        name: min(0.95, max(0.0, _lag1_autocorr(inputs[name])))
        for name in line_names
    }
    last_input = {name: float(inputs[name][-1]) for name in line_names}

    window = full_resid[-RESIDUAL_WINDOW_OBS:]
    q10, q90 = (float(v) for v in np.quantile(window, [0.10, 0.90]))
    rho_e = min(0.9, max(0.0, _lag1_autocorr(full_resid)))

    def growth(h: int) -> float:
        if rho_e <= 1e-9:
            return 1.0
        return math.sqrt((1.0 - rho_e ** (2 * h)) / (1.0 - rho_e**2))

    calendar_days = (as_of - manifest.history_start).days + 1
    sparsity_multiplier = math.sqrt(calendar_days / len(days_obs))

    seen_event_ids: set[str] = set()
    for adj in event_adjustments:
        if len(adj.path) != FORECAST_DAYS:
            raise ForecastError(
                f"event adjustment {adj.event_id} carries {len(adj.path)} days; "
                f"the slot requires exactly {FORECAST_DAYS}"
            )
        if adj.event_id in seen_event_ids:
            raise ForecastError(
                f"event adjustment {adj.event_id} is applied twice; each "
                "declared event enters a run once"
            )
        seen_event_ids.add(adj.event_id)
        if adj.interval_widening < 1.0:
            raise ForecastError(
                f"event adjustment {adj.event_id} carries interval "
                f"widening {adj.interval_widening} below 1.0 — a shock "
                "may widen a band or leave it, never narrow it"
            )
    events_log = np.zeros(FORECAST_DAYS)
    for adj in event_adjustments:
        events_log += np.array(adj.path, dtype=float)

    future_dates = [as_of + timedelta(days=h) for h in range(1, FORECAST_DAYS + 1)]
    future_design = baseline_design(future_dates)
    log_baseline = future_design @ base_coef

    # --- scenario shifts (R6, Law 5) --------------------------------
    # Levers move driver inputs, never the output: the sentiment
    # override replaces the sentiment path's starting value before
    # the paths are built (so the line's recorded last input is
    # the override, stated on its face), and driver shifts then
    # move the built paths. A shift naming a driver this run did
    # not estimate — unreported, or sentiment not estimable — is
    # refused with the driver named: a scenario may not move a
    # line that does not exist.
    shift_markers: dict[str, dict] = {}
    if sentiment_start_override is not None:
        if "sentiment" not in line_names:
            raise ForecastError(
                "a sentiment override was handed in, but this run "
                "has no estimated sentiment line to override — the "
                "driver is unreported or not estimable for this "
                "series, and a scenario cannot move it"
            )
        shift_markers["sentiment"] = {
            "mode": "set_start",
            "value": sentiment_start_override,
        }
        last_input["sentiment"] = float(sentiment_start_override)

    input_paths: dict[str, np.ndarray] = {
        name: np.array(
            [last_input[name] * persistence[name] ** h for h in range(1, FORECAST_DAYS + 1)]
        )
        for name in line_names
    }
    seen_shift_drivers: set[str] = set()
    for shift in driver_shifts:
        if shift.driver in seen_shift_drivers:
            raise ForecastError(
                f"driver {shift.driver} is shifted twice; each "
                "driver's input path moves once per run"
            )
        seen_shift_drivers.add(shift.driver)
        if shift.driver not in input_paths:
            raise ForecastError(
                f"a shift was handed in for driver {shift.driver}, "
                "but this run has no such input path — the driver "
                "is unreported or not estimable for this series, "
                "and a scenario cannot move it"
            )
        if shift.mode == "add":
            input_paths[shift.driver] = input_paths[shift.driver] + shift.value
        else:  # add_clip
            if shift.clip_min is None or shift.clip_max is None:
                raise ForecastError(
                    f"driver {shift.driver} shift is add_clip "
                    "without stated clip bounds"
                )
            input_paths[shift.driver] = np.clip(
                input_paths[shift.driver] + shift.value,
                shift.clip_min,
                shift.clip_max,
            )
        shift_markers[shift.driver] = {
            "mode": shift.mode,
            "value": shift.value,
            "clip_min": shift.clip_min,
            "clip_max": shift.clip_max,
        }
    log_contrib = {
        name: coefficients[name] * input_paths[name] for name in line_names
    }

    days: list[ForecastDay] = []
    contrib_paths_inr: dict[str, list[float]] = {name: [] for name in line_names}
    events_path_inr: list[float] = []
    per_event_paths_inr: dict[str, list[float]] = {
        adj.event_id: [] for adj in event_adjustments
    }
    for h in range(1, FORECAST_DAYS + 1):
        i = h - 1
        level = math.exp(float(log_baseline[i]))
        baseline_inr = round(level, 2)
        running = float(log_baseline[i])
        contributions: dict[str, float] = {}
        for name in line_names:
            running += float(log_contrib[name][i])
            new_level = math.exp(running)
            value = round(new_level - level, 2)
            contributions[name] = value
            contrib_paths_inr[name].append(value)
            level = new_level
        # Events telescope separately, in the order given, so each
        # event's own INR path is a recorded line — never one
        # absorbed total (Law 4). The day's events adjustment is
        # the sum of the per-event steps, so the decomposition
        # stays exact by construction.
        events_value = 0.0
        widening = 1.0
        for adj in event_adjustments:
            step = round(math.exp(running + float(adj.path[i])) - level, 2)
            running += float(adj.path[i])
            level = math.exp(running)
            per_event_paths_inr[adj.event_id].append(step)
            events_value = round(events_value + step, 2)
            if adj.path[i] != 0.0:
                widening = max(widening, adj.interval_widening)
        events_path_inr.append(events_value)
        p50 = round(baseline_inr + sum(contributions.values()) + events_value, 2)
        g = growth(h) * sparsity_multiplier * widening
        days.append(
            ForecastDay(
                forecast_date=future_dates[i],
                baseline=baseline_inr,
                contributions=contributions,
                events_adjustment=events_value,
                p10=round(p50 * math.exp(q10 * g), 2),
                p50=p50,
                p90=round(p50 * math.exp(q90 * g), 2),
            )
        )

    if sentiment_not_estimable is not None:
        # The line exists on every day at exactly zero, in
        # attribution order — present, named, and contributing
        # nothing, so the decomposition identity is untouched.
        for day in days:
            ordered: dict[str, float] = {}
            for name in ATTRIBUTION_ORDER:
                if name == "sentiment":
                    ordered["sentiment"] = 0.0
                elif name in day.contributions:
                    ordered[name] = day.contributions[name]
            day.contributions = ordered

    def at_horizon(path: list[float]) -> dict[str, float]:
        return {str(h): path[h - 1] for h in HORIZONS}

    lines: list[ContributionLine] = []
    for name in line_names:
        summary: dict = {
            "transform": _TRANSFORMS[name],
            "last_observed_date": reg_days[-1].isoformat(),
            "last_input": round(last_input[name], 4),
            "persistence": round(persistence[name], 4),
            "estimation_obs": len(reg_days),
        }
        if name in shift_markers:
            # The line states on its face that a scenario lever
            # moved its input path, and by how much (R6).
            summary["scenario_shift"] = shift_markers[name]
        lines.append(
            ContributionLine(
                driver=name,
                coefficient=round(coefficients[name], 6),
                input_path=[round(float(v), 4) for v in input_paths[name]],
                contribution_path_inr=contrib_paths_inr[name],
                at_horizon=at_horizon(contrib_paths_inr[name]),
                input_summary=summary,
            )
        )
    if sentiment_not_estimable is not None and sentiment_input is not None:
        lines.append(
            ContributionLine(
                driver="sentiment",
                coefficient=None,
                input_path=[0.0] * FORECAST_DAYS,
                contribution_path_inr=[0.0] * FORECAST_DAYS,
                at_horizon={str(h): 0.0 for h in HORIZONS},
                input_summary={
                    "state": "not_estimable",
                    "reason": sentiment_not_estimable,
                    "transform": _TRANSFORMS["sentiment"],
                    "pack_version": sentiment_input.pack_version,
                    "aligned_days": sentiment_counts["aligned_days"],
                    "span_days": sentiment_counts["span_days"],
                    "min_aligned_days": sentiment_input.min_aligned_days,
                    "min_span_days": sentiment_input.min_span_days,
                    "recency_days": sentiment_input.recency_days,
                },
            )
        )
    if sentiment_daily is not None and sentiment_input is not None:
        for line in lines:
            if line.driver == "sentiment":
                line.input_summary.update(
                    {
                        "state": "estimated",
                        "pack_version": sentiment_input.pack_version,
                        "latest_index_value": sentiment_input.latest_index_value,
                        "latest_week_start": (
                            sentiment_input.latest_week_start.isoformat()
                            if sentiment_input.latest_week_start
                            else None
                        ),
                        "cited_item_ids": list(sentiment_input.cited_item_ids),
                    }
                )
    events_summary: dict = {
        "transform": "declared event adjustment path (log price)",
        "applied_events": [a.event_id for a in event_adjustments],
        "estimation_obs": 0,
    }
    if event_adjustments:
        # Each event's own line, recorded on the artefact: its log
        # path, its telescoped INR path, and the widening it
        # carried. Present only when events were applied, so an
        # unshocked forecast is byte-identical to its pre-R5 form.
        events_summary["per_event"] = {
            adj.event_id: {
                "input_path": [round(float(v), 4) for v in adj.path],
                "contribution_path_inr": per_event_paths_inr[adj.event_id],
                "at_horizon": at_horizon(per_event_paths_inr[adj.event_id]),
                "interval_widening": adj.interval_widening,
            }
            for adj in event_adjustments
        }
        events_summary["interval_widening"] = max(
            adj.interval_widening for adj in event_adjustments
        )
    lines.append(
        ContributionLine(
            driver="events",
            coefficient=None,
            input_path=[round(float(v), 4) for v in events_log],
            contribution_path_inr=events_path_inr,
            at_horizon=at_horizon(events_path_inr),
            input_summary=events_summary,
        )
    )

    horizons_summary = [
        HorizonSummary(
            horizon_days=h,
            forecast_date=days[h - 1].forecast_date,
            baseline=days[h - 1].baseline,
            contributions=dict(days[h - 1].contributions),
            events_adjustment=days[h - 1].events_adjustment,
            p10=days[h - 1].p10,
            p50=days[h - 1].p50,
            p90=days[h - 1].p90,
        )
        for h in HORIZONS
    ]

    method = ForecastMethod(
        engine_version=ENGINE_VERSION,
        baseline=BaselineMethod(
            intercept=round(float(base_coef[0]), 6),
            trend_per_year=round(float(base_coef[1]), 6),
            seasonal_sin=round(float(base_coef[2]), 6),
            seasonal_cos=round(float(base_coef[3]), 6),
            anchor_date=anchor,
            n_obs=len(days_obs),
        ),
        drivers={
            name: DriverMethod(
                coefficient=round(coefficients[name], 6),
                persistence=round(persistence[name], 4),
                last_input=round(last_input[name], 4),
            )
            for name in line_names
        },
        residuals=ResidualMethod(
            sigma=round(float(full_resid.std()), 6),
            rho=round(rho_e, 4),
            q10=round(q10, 6),
            q90=round(q90, 6),
            window_obs=len(window),
        ),
        sparsity=SparsityMethod(
            observed_days=len(days_obs),
            calendar_days=calendar_days,
            multiplier=round(sparsity_multiplier, 4),
        ),
        attribution_order=list(ATTRIBUTION_ORDER),
        events_applied=[a.event_id for a in event_adjustments],
    )

    named_missing = missing_drivers(spec)
    if sentiment_not_estimable is not None:
        # Named alongside the catalogue's data gaps, so the desk
        # sees the absent driver in the same place it already
        # looks — the line itself carries the failing floors.
        named_missing = named_missing + ["sentiment_not_estimable"]

    forecast = Forecast(
        forecast_id="FCST-pending",
        commodity=commodity,
        market=market,
        as_of=as_of,
        status="draft",
        engine_version=ENGINE_VERSION,
        method=method,
        days=days,
        lines=lines,
        horizons_summary=horizons_summary,
        missing_drivers=named_missing,
    )
    forecast.forecast_id = forecast_content_id(forecast)
    return forecast


def forecast_content_id(forecast: Forecast) -> str:
    """The content address: a hash over everything except id/status."""
    payload = forecast.model_dump(mode="json", exclude={"forecast_id", "status"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "FCST-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]
