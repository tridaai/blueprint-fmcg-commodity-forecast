"""Domain models for the FMCG commodity forecast blueprint.

An *observation* is one driver value for one commodity in one market
on one day. Everything the later rounds compute — forecasts, backtests,
dashboards — reads observations through the store port and nothing
else. The grading truth (the sealed future path) is a separate model
family living behind ``fmcg_forecast.truth`` on purpose.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Driver = Literal[
    "modal_price",
    "arrivals",
    "stock_level",
    "import_flow",
    "export_flow",
    "weather_index",
]

DRIVERS: tuple[str, ...] = (
    "modal_price",
    "arrivals",
    "stock_level",
    "import_flow",
    "export_flow",
    "weather_index",
)

# Units per driver, stated once so every surface labels figures the
# same way.
DRIVER_UNITS: dict[str, str] = {
    "modal_price": "INR/quintal",
    "arrivals": "quintal/day",
    "stock_level": "index (0-160)",
    "import_flow": "quintal/day",
    "export_flow": "quintal/day",
    "weather_index": "deviation (-1..1)",
}


class Observation(BaseModel):
    commodity: str
    market: str
    obs_date: date
    driver: Driver
    value: float

    @property
    def unit(self) -> str:
        return DRIVER_UNITS[self.driver]


class EventRecord(BaseModel):
    """A declared market event in the registry (Law 4).

    Shocks are data: kind, window, magnitude and the transmission
    channel are stated on the record, so a forecast can show the event
    as its own contribution lines instead of absorbing it silently.
    """

    event_id: str
    kind: Literal["tariff_shock", "export_ban"]
    commodity: str
    start_date: date
    end_date: date
    magnitude: float = Field(description="Signed peak price effect, e.g. +0.16 / -0.11")
    decay_days: int
    transmission: str
    description: str


class TrendBreak(BaseModel):
    commodity: str
    break_date: date
    kind: Literal["slope_change", "level_shift"]
    detail: str


class WeatherAnomaly(BaseModel):
    commodity: str
    start_date: date
    end_date: date
    depth: float = Field(description="Signed weather-index deviation planted in the window")
    detail: str


class CommodityCoverage(BaseModel):
    commodity: str
    markets: list[str]
    drivers: list[str]
    reporting_pattern: str = Field(description="'mon_sat' or 'tue_fri' (coffee)")
    history_days_per_market: int
    history_rows: int
    missing_drivers: list[str] = Field(
        default_factory=list,
        description="Drivers this commodity does not report — named gaps, never zero-filled",
    )


class Manifest(BaseModel):
    """The generator manifest: everything planted, stated.

    The eval gate grades the dataset against this manifest, so the
    manifest is the contract: event dates/magnitudes, trend breaks,
    coverage and named gaps all live here.
    """

    generator_version: str
    seed: int
    history_start: date
    history_end: date
    future_start: date
    future_end: date
    commodities: list[CommodityCoverage]
    events: list[EventRecord]
    trend_breaks: list[TrendBreak]
    weather_anomalies: list[WeatherAnomaly]
    coffee_disruption_start: date
    coffee_disruption_end: date
    coffee_disruption_reporting_days_lost: int
    history_digest: str = Field(description="SHA-256 over the canonical history rows")
    history_rows: int
    future_rows: int
