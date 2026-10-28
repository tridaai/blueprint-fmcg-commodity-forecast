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
slot (a per-day log-price path per event). Round 2 ships the slot
empty; the event registry fills it in R5, where an event's
contribution will appear as its own line instead of being absorbed.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from typing import Protocol

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

    The R5 event registry produces these from EventRecords; R2 ships
    the slot empty and the engine simply validates and applies any
    path it is handed.
    """

    event_id: str
    path: list[float] = Field(description="Log-price adjustment per horizon day")


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
) -> tuple[dict[str, np.ndarray], list[date]]:
    """Standardised driver regressors aligned to common observed days."""
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

    inputs, reg_days = _driver_inputs(source, commodity, market, as_of, days_obs)
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

    for adj in event_adjustments:
        if len(adj.path) != FORECAST_DAYS:
            raise ForecastError(
                f"event adjustment {adj.event_id} carries {len(adj.path)} days; "
                f"the slot requires exactly {FORECAST_DAYS}"
            )
    events_log = np.zeros(FORECAST_DAYS)
    for adj in event_adjustments:
        events_log += np.array(adj.path, dtype=float)

    future_dates = [as_of + timedelta(days=h) for h in range(1, FORECAST_DAYS + 1)]
    future_design = baseline_design(future_dates)
    log_baseline = future_design @ base_coef

    input_paths: dict[str, np.ndarray] = {
        name: np.array(
            [last_input[name] * persistence[name] ** h for h in range(1, FORECAST_DAYS + 1)]
        )
        for name in line_names
    }
    log_contrib = {
        name: coefficients[name] * input_paths[name] for name in line_names
    }

    days: list[ForecastDay] = []
    contrib_paths_inr: dict[str, list[float]] = {name: [] for name in line_names}
    events_path_inr: list[float] = []
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
        events_value = round(math.exp(running + float(events_log[i])) - level, 2)
        events_path_inr.append(events_value)
        p50 = round(baseline_inr + sum(contributions.values()) + events_value, 2)
        g = growth(h) * sparsity_multiplier
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

    def at_horizon(path: list[float]) -> dict[str, float]:
        return {str(h): path[h - 1] for h in HORIZONS}

    lines: list[ContributionLine] = []
    for name in line_names:
        lines.append(
            ContributionLine(
                driver=name,
                coefficient=round(coefficients[name], 6),
                input_path=[round(float(v), 4) for v in input_paths[name]],
                contribution_path_inr=contrib_paths_inr[name],
                at_horizon=at_horizon(contrib_paths_inr[name]),
                input_summary={
                    "transform": _TRANSFORMS[name],
                    "last_observed_date": reg_days[-1].isoformat(),
                    "last_input": round(last_input[name], 4),
                    "persistence": round(persistence[name], 4),
                    "estimation_obs": len(reg_days),
                },
            )
        )
    lines.append(
        ContributionLine(
            driver="events",
            coefficient=None,
            input_path=[round(float(v), 4) for v in events_log],
            contribution_path_inr=events_path_inr,
            at_horizon=at_horizon(events_path_inr),
            input_summary={
                "transform": "declared event adjustment path (log price)",
                "applied_events": [a.event_id for a in event_adjustments],
                "estimation_obs": 0,
            },
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
        missing_drivers=missing_drivers(spec),
    )
    forecast.forecast_id = forecast_content_id(forecast)
    return forecast


def forecast_content_id(forecast: Forecast) -> str:
    """The content address: a hash over everything except id/status."""
    payload = forecast.model_dump(mode="json", exclude={"forecast_id", "status"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "FCST-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]
