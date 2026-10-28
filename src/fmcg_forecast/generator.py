"""The dataset generator — gold by construction.

One deterministic, seeded pass builds the whole timeline
(2023-01-01 .. 2026-03-31) for every commodity/market, then splits it
at 2026-01-01: the past is the *history* the system works with; the
future 90 days are the **sealed grading truth**, written only through
the truth store and never readable by the forecast package (the
isolation is graded structurally by a test and the eval gate).

What is planted, all of it restated in the manifest:

- seasonality anchored on each commodity's harvest calendar
  (arrivals peak at harvest, prices trough there);
- trend, with two planted breaks: soybean's drift steepens from
  2024-07-01, wheat takes a +4% level shift on 2025-01-01;
- one tariff shock (soybean, from 2025-06-15, +16% peak decaying
  over 45 days through the import-parity channel);
- one export ban (basmati rice, 2024-09-01 .. 2024-10-30: export
  flow collapses and the domestic price takes a -11% step that
  recovers after the ban lifts);
- one weather anomaly (a chili drought, Jul-Sep 2025, -0.6 index);
- coffee as the thin-data case: reports Tue/Fri only, a planted
  three-week reporting disruption in Aug 2025, and no stock or
  trade-flow drivers at all — named gaps, never zero-filled rows.

Markets operate Mon-Sat; Sundays simply have no observations, and
the manifest's coverage counts are stated in operating days.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from fmcg_forecast.catalogue import BY_NAME, COMMODITIES, CommoditySpec, missing_drivers
from fmcg_forecast.models import (
    CommodityCoverage,
    EventRecord,
    Manifest,
    Observation,
    TrendBreak,
    WeatherAnomaly,
)

GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20261027

HISTORY_START = date(2023, 1, 1)
HISTORY_END = date(2025, 12, 31)
FUTURE_START = date(2026, 1, 1)
FUTURE_END = date(2026, 3, 31)

TARIFF_EVENT = EventRecord(
    event_id="EVT-2025-TARIFF-SOYBEAN",
    kind="tariff_shock",
    commodity="soybean",
    start_date=date(2025, 6, 15),
    end_date=date(2025, 7, 30),
    magnitude=0.16,
    decay_days=45,
    transmission="import_parity",
    description="Import tariff increase on oilseeds; domestic price steps up "
    "through import parity and decays as trade reroutes.",
)
BAN_EVENT = EventRecord(
    event_id="EVT-2024-BAN-BASMATI",
    kind="export_ban",
    commodity="basmati_rice",
    start_date=date(2024, 9, 1),
    end_date=date(2024, 10, 30),
    magnitude=-0.11,
    decay_days=60,
    transmission="export_flow",
    description="Export ban on basmati rice; export flow collapses for the "
    "window and the domestic price steps down until the ban lifts.",
)
EVENTS: tuple[EventRecord, ...] = (TARIFF_EVENT, BAN_EVENT)

TREND_BREAKS: tuple[TrendBreak, ...] = (
    TrendBreak(
        commodity="soybean",
        break_date=date(2024, 7, 1),
        kind="slope_change",
        detail="Log drift steepens from 0.020 to 0.055 per year.",
    ),
    TrendBreak(
        commodity="wheat",
        break_date=date(2025, 1, 1),
        kind="level_shift",
        detail="+4% level shift (support-price revision).",
    ),
)

WEATHER_ANOMALIES: tuple[WeatherAnomaly, ...] = (
    WeatherAnomaly(
        commodity="chili",
        start_date=date(2025, 7, 1),
        end_date=date(2025, 9, 15),
        depth=-0.6,
        detail="Planted drought window in the chili belt.",
    ),
)

COFFEE_DISRUPTION_START = date(2025, 8, 4)
COFFEE_DISRUPTION_END = date(2025, 8, 22)

SOYBEAN_BREAK_DATE = date(2024, 7, 1)
SOYBEAN_SLOPE_AFTER = 0.055
WHEAT_SHIFT_DATE = date(2025, 1, 1)
WHEAT_SHIFT = math.log(1.04)


@dataclass
class GeneratedData:
    history: list[Observation]
    future: list[Observation]
    manifest: Manifest


def _operating_days(spec: CommoditySpec, start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        weekday = current.weekday()  # Mon=0 .. Sun=6
        if spec.reporting == "tue_fri":
            if weekday in (1, 4):  # Tue, Fri
                days.append(current)
        elif weekday != 6:  # Mon-Sat
            days.append(current)
        current += timedelta(days=1)
    return days


def _ar1(rng: np.random.Generator, n: int, rho: float, sigma: float) -> np.ndarray:
    noise = rng.normal(0.0, sigma, n)
    out = np.zeros(n)
    for i in range(1, n):
        out[i] = rho * out[i - 1] + noise[i]
    out[0] = noise[0]
    return out


def _event_price_term(spec: CommoditySpec, days: list[date]) -> np.ndarray:
    """Planted event contributions to log price, day by day."""
    term = np.zeros(len(days))
    for i, day in enumerate(days):
        if spec.commodity == "soybean" and day >= TARIFF_EVENT.start_date:
            age = (day - TARIFF_EVENT.start_date).days
            if age <= TARIFF_EVENT.decay_days:
                ramp = min(1.0, (age + 1) / 3.0)
                decay = math.exp(-math.log(2) * max(0, age - 3) / 18.0)
                term[i] += TARIFF_EVENT.magnitude * ramp * decay
        if spec.commodity == "basmati_rice":
            if BAN_EVENT.start_date <= day <= BAN_EVENT.end_date:
                age = (day - BAN_EVENT.start_date).days
                ramp = min(1.0, (age + 1) / 3.0)
                term[i] += BAN_EVENT.magnitude * ramp
            elif BAN_EVENT.end_date < day <= BAN_EVENT.end_date + timedelta(days=10):
                since = (day - BAN_EVENT.end_date).days
                term[i] += BAN_EVENT.magnitude * (1.0 - since / 10.0)
    return term


def _series_rows(
    spec: CommoditySpec,
    market,
    days: list[date],
    n_hist_days: int,
    rng: np.random.Generator,
) -> tuple[list[Observation], list[Observation]]:
    n = len(days)
    doy = np.array([d.timetuple().tm_yday for d in days], dtype=float)
    weekday = np.array([d.weekday() for d in days], dtype=float)
    years = np.array([(d - HISTORY_START).days / 365.25 for d in days])

    # --- arrivals -------------------------------------------------
    seasonal_arr = np.clip(
        1.0 + spec.arrivals_seasonal_amp * np.cos(2 * np.pi * (doy - spec.harvest_doy) / 365.25),
        0.08,
        None,
    )
    weekday_factor = np.where(weekday == 0, 1.08, np.where(weekday == 5, 0.72, 1.0))
    arrivals = (
        spec.arrivals_base
        * market.arrivals_factor
        * seasonal_arr
        * weekday_factor
        * np.exp(rng.normal(0.0, 0.16, n))
    )
    arrivals = np.clip(arrivals, 1.0, None)

    # --- weather --------------------------------------------------
    weather = 0.5 * np.sin(2 * np.pi * (doy - 105) / 365.25) + _ar1(rng, n, 0.7, 0.16)
    for anomaly in WEATHER_ANOMALIES:
        if anomaly.commodity == spec.commodity:
            mask = np.array([anomaly.start_date <= d <= anomaly.end_date for d in days])
            weather = weather + anomaly.depth * mask
    weather = np.clip(weather, -1.0, 1.0)

    # --- stocks (integrates arrivals) ------------------------------
    stock = np.zeros(n)
    level = 70.0
    for i in range(n):
        level += (arrivals[i] / (spec.arrivals_base * market.arrivals_factor) - 1.0) * 7.5
        level += rng.normal(0.0, 0.8)
        level = float(np.clip(level, 5.0, 160.0))
        stock[i] = level

    # --- trade flows ----------------------------------------------
    imports = (
        spec.import_base
        * (1.0 + 0.25 * np.cos(2 * np.pi * (doy - spec.harvest_doy - 40) / 365.25))
        * np.exp(rng.normal(0.0, 0.20, n))
    )
    exports = (
        spec.export_base
        * (1.0 + 0.25 * np.cos(2 * np.pi * (doy - spec.harvest_doy + 20) / 365.25))
        * np.exp(rng.normal(0.0, 0.20, n))
    )
    if spec.commodity == "basmati_rice":
        ban_mask = np.array([BAN_EVENT.start_date <= d <= BAN_EVENT.end_date for d in days])
        exports = np.where(ban_mask, exports * 0.05, exports)
    imports = np.clip(imports, 0.0, None)
    exports = np.clip(exports, 0.0, None)

    # --- price ------------------------------------------------------
    log_base = math.log(spec.base_price * market.price_factor)
    if spec.commodity == "soybean":
        break_years = (SOYBEAN_BREAK_DATE - HISTORY_START).days / 365.25
        trend = np.where(
            years <= break_years,
            spec.trend_per_year * years,
            spec.trend_per_year * break_years
            + SOYBEAN_SLOPE_AFTER * (years - break_years),
        )
    else:
        trend = spec.trend_per_year * years
    if spec.commodity == "wheat":
        trend = trend + np.array([WHEAT_SHIFT if d >= WHEAT_SHIFT_DATE else 0.0 for d in days])
    seasonal_price = -spec.price_seasonal_amp * np.cos(
        2 * np.pi * (doy - spec.harvest_doy) / 365.25
    )
    z_arr = (np.log(arrivals) - np.log(arrivals).mean()) / np.log(arrivals).std()
    log_price = (
        log_base
        + trend
        + seasonal_price
        - 0.085 * z_arr
        - 0.06 * weather
        - 0.035 * (stock - 70.0) / 30.0
        + _event_price_term(spec, days)
        + _ar1(rng, n, 0.35, 0.011)
    )
    price = np.exp(log_price)

    drivers: dict[str, np.ndarray] = {
        "modal_price": np.round(price, 2),
        "arrivals": np.round(arrivals, 1),
        "stock_level": np.round(stock, 2),
        "import_flow": np.round(imports, 1),
        "export_flow": np.round(exports, 1),
        "weather_index": np.round(weather, 4),
    }
    hist_rows: list[Observation] = []
    fut_rows: list[Observation] = []
    for driver in spec.drivers:
        values = drivers[driver]
        for i, day in enumerate(days):
            row = Observation(
                commodity=spec.commodity,
                market=market.market,
                obs_date=day,
                driver=driver,  # type: ignore[arg-type]
                value=float(values[i]),
            )
            (hist_rows if i < n_hist_days else fut_rows).append(row)
    return hist_rows, fut_rows


def _digest(rows: list[Observation]) -> str:
    h = hashlib.sha256()
    for row in sorted(rows, key=lambda r: (r.commodity, r.market, r.obs_date, r.driver)):
        h.update(
            f"{row.commodity}|{row.market}|{row.obs_date.isoformat()}|{row.driver}|{row.value!r}\n".encode()
        )
    return h.hexdigest()


def generate_dataset(seed: int = DEFAULT_SEED) -> GeneratedData:
    """Generate the full timeline deterministically from ``seed``."""
    all_days_start, all_days_end = HISTORY_START, FUTURE_END
    history: list[Observation] = []
    future: list[Observation] = []
    coverage: list[CommodityCoverage] = []

    for c_idx, spec in enumerate(COMMODITIES):
        hist_days = _operating_days(spec, HISTORY_START, HISTORY_END)
        fut_days = _operating_days(spec, FUTURE_START, FUTURE_END)
        if spec.commodity == "coffee":
            hist_days = [
                d for d in hist_days if not (COFFEE_DISRUPTION_START <= d <= COFFEE_DISRUPTION_END)
            ]
        days = hist_days + fut_days
        spec_hist_rows = 0
        for m_idx, market in enumerate(spec.markets):
            rng = np.random.default_rng(
                np.random.SeedSequence([seed, c_idx * 100 + m_idx])
            )
            hist_rows, fut_rows = _series_rows(spec, market, days, len(hist_days), rng)
            history.extend(hist_rows)
            future.extend(fut_rows)
            spec_hist_rows += len(hist_rows)
        coverage.append(
            CommodityCoverage(
                commodity=spec.commodity,
                markets=[m.market for m in spec.markets],
                drivers=list(spec.drivers),
                reporting_pattern=spec.reporting,
                history_days_per_market=len(hist_days),
                history_rows=spec_hist_rows,
                missing_drivers=missing_drivers(spec),
            )
        )

    lost = len(
        [
            d
            for d in _operating_days(BY_NAME["coffee"], COFFEE_DISRUPTION_START, COFFEE_DISRUPTION_END)
        ]
    )
    manifest = Manifest(
        generator_version=GENERATOR_VERSION,
        seed=seed,
        history_start=HISTORY_START,
        history_end=HISTORY_END,
        future_start=FUTURE_START,
        future_end=FUTURE_END,
        commodities=coverage,
        events=list(EVENTS),
        trend_breaks=list(TREND_BREAKS),
        weather_anomalies=list(WEATHER_ANOMALIES),
        coffee_disruption_start=COFFEE_DISRUPTION_START,
        coffee_disruption_end=COFFEE_DISRUPTION_END,
        coffee_disruption_reporting_days_lost=lost,
        history_digest=_digest(history),
        history_rows=len(history),
        future_rows=len(future),
    )
    return GeneratedData(history=history, future=future, manifest=manifest)
