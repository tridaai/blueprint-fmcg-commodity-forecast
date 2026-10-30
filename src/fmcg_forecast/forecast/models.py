"""Forecast artefacts (R2) and accuracy artefacts (R3).

A *forecast* is a stored, content-addressed artefact: its id hashes
the full decomposition, so any later edit to a line, a total or a
method coefficient breaks the id and is detectable. The lifecycle
status (``draft`` -> ``official``) is deliberately NOT part of the
hashed content — it is state about the artefact, flipped only by a
recorded approval act, and the store keeps it in its own column.

Every figure in here is computed by the engine in code (Law 1). The
model port only ever sees these artefacts, never the raw series.

R3 adds the Law 2 artefacts: a *backtest result* (one origin, one
horizon, the scored forecast path against the realised path), an
*accuracy record* (the ledger's pooled aggregation over a stated
window of results), and the *accuracy attachment* a forecast carries
— a pinned, self-contained snapshot of the ledger records for its
series at the moment it was run.
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
    "sentiment",
    "events",
)

HORIZONS: tuple[int, ...] = (7, 30, 90)
FORECAST_DAYS = 90


class ContributionLine(BaseModel):
    """One driver's contribution, as a recorded line (Law 1)."""

    driver: str = Field(description="arrivals | stock_level | trade_flow | weather_index | sentiment | events")
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
        description="Declared-event adjustment in INR/quintal: the sum "
        "of the applied events' own telescoped steps (each event's "
        "path is recorded on the events line, R5). Zero when no "
        "declared event touches the day."
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
        description="Declared events whose adjustments are in this "
        "forecast (R5), in the order they were telescoped",
    )


class HorizonAccuracy(BaseModel):
    """One horizon's slice of a forecast's accuracy attachment."""

    horizon_days: int
    state: Literal["measured", "degraded", "unmeasured"] = Field(
        description="degraded when the ledger record's MAPE exceeds the "
        "accuracy pack's stated threshold; unmeasured when the series "
        "has no backtest coverage at this horizon yet"
    )
    record_id: str | None = Field(
        description="The accuracy record this slice was pinned from "
        "(None when unmeasured)"
    )
    n_origins: int = Field(description="Backtest origins behind the record")
    mae: float | None = Field(description="Pooled MAE, INR/quintal")
    mape: float | None = Field(description="Pooled MAPE, percent")
    bias: float | None = Field(
        description="Pooled mean error (realised - forecast), INR/quintal"
    )
    coverage: float | None = Field(
        description="Share of realised days inside the P10-P90 band"
    )


class AccuracyAttachment(BaseModel):
    """The measured accuracy a forecast carries (Law 2).

    A pinned snapshot: the ledger records for this forecast's series
    at run time, copied onto the artefact so the forecast of record
    keeps the accuracy it was judged by even after the ledger moves
    on. There is no view of a forecast without this attachment's
    state — a caller cannot ask for the flag to be left off.
    """

    state: Literal["measured", "degraded", "unmeasured"] = Field(
        description="degraded when ANY horizon is degraded; unmeasured "
        "when NO horizon has backtest coverage; measured otherwise"
    )
    pack_version: str | None = Field(
        description="Accuracy pack version the records were built under"
    )
    per_horizon: list[HorizonAccuracy]
    note: str = Field(
        description="Why the state is what it is, in one stated sentence "
        "— an unmeasured series names its missing coverage here"
    )


class PreflightPin(BaseModel):
    """The coverage pre-flight a run pinned (R13, F20-OW4).

    The run-anyway path, on the record: the checklist's named
    gaps ride on the artefact verbatim, beside the forecast's
    own missing-driver list, so a number struck over thin
    evidence carries the evidence's gaps wherever it is read.
    The pin is part of the content address — a run over the
    same estimation with a different checklist is a different
    artefact.
    """

    preflight_id: str = Field(description="The pre-flight report pinned")
    pack_version: str = Field(description="Console pack the report was struck under")
    gaps: list[str] = Field(
        description="The report's named gaps, verbatim — the "
        "console verifier checks they are exactly the pinned "
        "report's list"
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
    accuracy: AccuracyAttachment | None = Field(
        default=None,
        description="Measured backtest accuracy pinned at run time "
        "(Law 2, R3). Attached by the forecast service on the run "
        "path; raw engine runs carry None — the engine estimates, "
        "the service judges.",
    )
    preflight: PreflightPin | None = Field(
        default=None,
        description="The coverage pre-flight pinned at run time "
        "(R13, F20-OW4), when the run was struck under one. "
        "Attached by the forecast service on the run path; "
        "unpinned runs carry None.",
    )


class BacktestDay(BaseModel):
    """One scored day of a backtest: forecast band vs what happened."""

    forecast_date: date
    p10: float
    p50: float
    p90: float
    realised: float = Field(description="Observed modal price that day, INR/quintal")


class BacktestResult(BaseModel):
    """One rolling-origin backtest: one series, one origin, one horizon.

    The scored days are the days in (origin, origin + horizon] that
    carry a realised observation — markets rest on Sundays, and a
    day with no observation is not scored, never zero-filled. The
    sums are the primitive record; the derived metrics are computed
    from them by the stated formulas in backtest/metrics.py, so a
    verifier can re-perform every figure from this artefact alone.
    """

    result_id: str
    commodity: str
    market: str
    origin: date = Field(description="The as_of the engine estimated at")
    horizon_days: int
    forecast_id: str = Field(
        description="Content address of the engine run at this origin "
        "(provenance; backtest runs are harness artefacts, re-performable "
        "from series + origin, and are not entered in the desk's "
        "forecast record)"
    )
    engine_version: str
    pack_version: str
    days: list[BacktestDay]
    n_days: int
    covered_days: int = Field(description="Scored days with p10 <= realised <= p90")
    sum_err: float = Field(description="Sum of (realised - p50) over scored days")
    sum_abs_err: float
    sum_abs_pct: float = Field(description="Sum of |realised - p50| / realised")
    mae: float = Field(description="sum_abs_err / n_days, INR/quintal")
    mape: float = Field(description="100 * sum_abs_pct / n_days, percent")
    bias: float = Field(description="sum_err / n_days, INR/quintal")
    coverage: float = Field(description="covered_days / n_days")


class AccuracyRecord(BaseModel):
    """The accuracy ledger's current record for one series x horizon.

    Aggregated by the stated rule: pool the error sums of the most
    recent ``ledger_window_origins`` backtest results (by origin) and
    derive the metrics from the pooled sums — day-weighted, so a
    long-horizon origin counts for its scored days, not as one vote.
    ``degraded`` is stamped here, at ledger build time, against the
    accuracy pack's threshold; forecasts copy it, they never
    re-judge it.
    """

    record_id: str
    commodity: str
    market: str
    horizon_days: int
    origins: list[date] = Field(description="Origins pooled, ascending")
    n_results: int
    n_days: int
    covered_days: int
    mae: float
    mape: float
    bias: float
    coverage: float
    engine_version: str
    pack_version: str
    degraded_threshold_mape_pct: float
    degraded: bool = Field(
        description="mape > degraded_threshold_mape_pct, judged when "
        "the ledger was built"
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
