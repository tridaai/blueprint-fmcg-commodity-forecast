"""Forecast artefacts (R2).

A *forecast* is a stored, content-addressed artefact: its id hashes
the full decomposition, so any later edit to a line, a total or a
method coefficient breaks the id and is detectable. The lifecycle
status (``draft`` -> ``official``) is deliberately NOT part of the
hashed content — it is state about the artefact, flipped only by a
recorded approval act, and the store keeps it in its own column.

Every figure in here is computed by the engine in code (Law 1). The
model port only ever sees these artefacts, never the raw series.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

# The stated attribution order: contributions are assigned
# sequentially in this order (telescoping), so baseline + the sum of
# contributions + the events adjustment equals the forecast total
# exactly, to the paisa. The order is part of the method and is
# recorded on every artefact.
ATTRIBUTION_ORDER: tuple[str, ...] = (
    "arrivals",
    "stock_level",
    "trade_flow",
    "weather_index",
    "events",
)

HORIZONS: tuple[int, ...] = (7, 30, 90)
FORECAST_DAYS = 90


class ContributionLine(BaseModel):
    """One driver's contribution, as a recorded line (Law 1)."""

    driver: str = Field(description="arrivals | stock_level | trade_flow | weather_index | events")
    coefficient: float | None = Field(
        description="Estimated log-price effect per unit of the standardised "
        "input (None for the events slot, whose input is a declared path)"
    )
    input_path: list[float] = Field(
        description="The standardised driver input used on each horizon day "
        "(for events: the declared log-price adjustment path)"
    )
    contribution_path_inr: list[float] = Field(
        description="This driver's contribution in INR/quintal on each "
        "horizon day, attributed sequentially in ATTRIBUTION_ORDER"
    )
    at_horizon: dict[str, float] = Field(
        description="Contribution in INR/quintal on the day each horizon closes"
    )
    input_summary: dict = Field(
        description="How the input path was produced: last observed input, "
        "persistence, estimation window"
    )


class ForecastDay(BaseModel):
    forecast_date: date
    baseline: float = Field(description="Trend + seasonality baseline, INR/quintal")
    contributions: dict[str, float] = Field(
        description="Per-driver contribution in INR/quintal (events excluded; "
        "it is its own field)"
    )
    events_adjustment: float = Field(
        description="Declared-event adjustment in INR/quintal. The slot "
        "exists from R2; the event registry fills it in R5. Zero until then."
    )
    p10: float
    p50: float = Field(
        description="baseline + sum(contributions) + events_adjustment, "
        "exact to the paisa by construction"
    )
    p90: float


class HorizonSummary(BaseModel):
    horizon_days: int
    forecast_date: date
    baseline: float
    contributions: dict[str, float]
    events_adjustment: float
    p10: float
    p50: float
    p90: float


class DriverMethod(BaseModel):
    coefficient: float
    persistence: float = Field(description="Lag-1 autocorrelation of the standardised input, clipped to [0, 0.95]")
    last_input: float = Field(description="Standardised input on the last observed day")


class BaselineMethod(BaseModel):
    intercept: float
    trend_per_year: float
    seasonal_sin: float
    seasonal_cos: float
    anchor_date: date = Field(description="First observed day; trend and seasonality are anchored here")
    n_obs: int


class ResidualMethod(BaseModel):
    sigma: float
    rho: float = Field(description="Lag-1 autocorrelation of full-model residuals, clipped to [0, 0.9]")
    q10: float = Field(description="Empirical 10th percentile of residuals over the rolling window")
    q90: float = Field(description="Empirical 90th percentile of residuals over the rolling window")
    window_obs: int


class SparsityMethod(BaseModel):
    observed_days: int
    calendar_days: int
    multiplier: float = Field(
        description="Interval widening factor: sqrt(calendar days / observed "
        "days) over the estimation window. Sparse series (coffee) widen "
        "honestly instead of borrowing precision they do not have (Law 7)."
    )


class ForecastMethod(BaseModel):
    engine_version: str
    baseline: BaselineMethod
    drivers: dict[str, DriverMethod]
    residuals: ResidualMethod
    sparsity: SparsityMethod
    attribution_order: list[str]
    rounding: str = "INR figures rounded to 2dp; the decomposition is exact to the paisa by construction"
    events_applied: list[str] = Field(
        default_factory=list,
        description="Declared events whose adjustments are in this forecast (R5; empty in R2)",
    )


class Forecast(BaseModel):
    forecast_id: str
    commodity: str
    market: str
    as_of: date = Field(description="Last history day the engine estimated on")
    status: Literal["draft", "official"] = "draft"
    engine_version: str
    method: ForecastMethod
    days: list[ForecastDay]
    lines: list[ContributionLine]
    horizons_summary: list[HorizonSummary]
    missing_drivers: list[str] = Field(
        default_factory=list,
        description="Drivers this commodity does not report — named gaps "
        "(Law 7), never silently treated as zero-effect",
    )


class ForecastApproval(BaseModel):
    """The recorded act that makes a draft the desk's official view."""

    approval_id: str
    forecast_id: str
    approver: str
    role: str
    decided_on: date


class Commentary(BaseModel):
    """Model-drafted commentary over a forecast artefact.

    Stored only after every decimal figure in the text verifies
    against the artefact (see commentary.py). A draft that fails
    verification is refused wholesale — nothing is stored.
    """

    forecast_id: str
    model_profile: str
    subject: str
    text: str
    figures: dict[str, str]
