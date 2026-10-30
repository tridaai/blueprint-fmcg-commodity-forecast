"""Forecast-ops analytics artefacts (R12, F20-AM1).

An *ops report* is a stored, content-addressed artefact: the
desk's track record, computed in code from the artefacts of
record — the backtest results, the accuracy ledger, the buy
signals and the event registry — under the analytics pack, and
naming the accuracy, signal and event pack versions its inputs
were struck under. It has four sections:

- **accuracy trends** — per series x horizon, the pooled early
  window against the pooled late window of stored results, the
  direction the pack's rule states, and the ledger record of
  record riding beside the trend;
- **signal outcomes** — every measurable buy signal (struck
  over the backtest grid's origins, and the desk's own stored
  signals) graded against the price that actually followed it,
  with pending signals named, never graded;
- **transmission error** — per event class, claimed against
  seasonally-matched measured transmission, with sample counts
  on the face and small samples named as such;
- **shock-window grades** — per event x market x horizon, the
  accuracy of scored days inside the event's window (plus its
  decay tail) against the same series' days outside it, with
  ungraded events named rather than silently absent.

Nothing in a report is authored: the same store always
recomputes the same report, which is what lets the verifier
re-perform it field for field.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


def _content_id(prefix: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return prefix + hashlib.sha256(canonical.encode()).hexdigest()[:16]


class AccuracyTrendRow(BaseModel):
    """One series x horizon's accuracy trend, from stored results."""

    commodity: str
    market: str
    horizon_days: int
    n_results: int = Field(description="Stored results behind the row")
    origins: list[date] = Field(description="Every pooled origin, ascending")
    early_origins: list[date] = Field(
        description="The early window's origins (empty when the "
        "trend is insufficient)"
    )
    late_origins: list[date] = Field(
        description="The late window's origins (empty when the "
        "trend is insufficient)"
    )
    early_mape: float | None = Field(description="Early window pooled MAPE, percent")
    late_mape: float | None = Field(description="Late window pooled MAPE, percent")
    early_coverage: float | None = Field(
        description="Early window pooled band coverage"
    )
    late_coverage: float | None = Field(
        description="Late window pooled band coverage"
    )
    delta_mape_pp: float | None = Field(
        description="late MAPE - early MAPE, percentage points"
    )
    delta_coverage: float | None = Field(
        description="late coverage - early coverage"
    )
    direction: Literal["improving", "steady", "worsening", "insufficient_history"]
    reason: str = Field(description="Why the direction is what it is, stated")
    ledger_record_id: str | None = Field(
        description="The accuracy ledger's current record for "
        "this series x horizon; None when the ledger holds none"
    )
    ledger_mape: float | None = Field(description="The ledger record's pooled MAPE")
    ledger_degraded: bool | None = Field(
        description="The ledger record's degraded stamp, as struck"
    )


class SignalOutcomeRow(BaseModel):
    """One buy signal measured against the price that followed it."""

    population: Literal["backtest_grid", "desk"] = Field(
        description="backtest_grid: struck from a raw engine run "
        "at an accuracy-grid origin, with the as-of attachment; "
        "desk: a stored signal from the desk's record"
    )
    commodity: str
    market: str
    as_of: date = Field(description="The origin the signal judged from")
    signal_id: str = Field(
        description="The signal artefact's content address (the "
        "stored artefact for desk rows; the computed artefact's "
        "address for grid rows)"
    )
    forecast_id: str = Field(description="The forecast the signal pinned")
    value: str = Field(description="The call, after caps: buy_now | phased | wait")
    base_value: str = Field(description="The call before accuracy caps")
    caps_applied: list[str]
    accuracy_state: str = Field(
        description="The accuracy state the signal inherited"
    )
    spot_inr: float = Field(description="The spot the signal pinned")
    spot_date: date
    predicted_drift_pct: float = Field(
        description="The signal's drift: horizon P50 against spot, percent"
    )
    state: Literal["graded", "pending"] = Field(
        description="pending when the horizon has not landed in "
        "observed history — named, never graded"
    )
    reason: str | None = Field(
        description="Why the row is pending; None when graded"
    )
    realised_date: date | None = Field(
        description="The last observed day inside the horizon window"
    )
    realised_inr: float | None = Field(description="The realised modal price that day")
    realised_drift_pct: float | None = Field(
        description="(realised - spot) / spot x 100, 4dp"
    )
    drift_error_pct: float | None = Field(
        description="realised drift - predicted drift, percentage points"
    )
    move: Literal["rose", "fell", "flat"] | None = Field(
        description="The realised move against the signal pack's bars"
    )
    favourable: bool | None = Field(
        description="Whether the move vindicates the call under "
        "the analytics pack's stated rule; None while pending"
    )


class OriginSignalSkip(BaseModel):
    """A grid origin the engine refused, named — never dropped."""

    commodity: str
    market: str
    origin: date
    reason: str = Field(description="The engine's refusal, verbatim")


class TransmissionClassRow(BaseModel):
    """One event class's claimed-vs-measured transmission error."""

    event_class: str
    event_ids: list[str] = Field(
        description="Every registered event of the class"
    )
    measurable_event_ids: list[str] = Field(
        description="Events the measurement layer could measure"
    )
    not_measurable_event_ids: list[str] = Field(
        description="Events named not measurable, with the "
        "measurement's reason standing on the event's own face"
    )
    n_events: int
    n_measurable: int
    verified_count: int = Field(
        description="Measurable events whose claim verified "
        "inside the event pack's band"
    )
    unverified_count: int = Field(
        description="Measurable events whose claim the "
        "measurement flags unverified"
    )
    mean_signed_error: float | None = Field(
        description="Mean of (measured - claimed) log effect "
        "over measurable events; None when none are measurable"
    )
    mean_abs_error: float | None = Field(
        description="Mean absolute signed error, log points"
    )
    mean_ratio_to_claim: float | None = Field(
        description="Mean of measured / claimed over measurable events"
    )
    sample_state: Literal["evidence", "small_sample", "no_measurable_events"]
    note: str = Field(
        description="How the row reads — a small sample is named "
        "anecdote on its face, never dressed as evidence"
    )


class ShockWindowRow(BaseModel):
    """One event x market x horizon's shock-window accuracy grade."""

    event_id: str
    event_class: str
    commodity: str
    market: str
    horizon_days: int
    window_start: date
    window_end: date | None = Field(
        description="The declared window end; None while open-ended"
    )
    shock_end: date = Field(
        description="The last shock day judged: window end plus "
        "the stated decay tail, or the series' last observed "
        "day while the window is open-ended"
    )
    state: Literal["graded", "no_shock_window_days", "no_baseline_days"]
    reason: str = Field(description="Why the state is what it is, stated")
    n_results_shock: int = Field(
        description="Stored results contributing at least one shock day"
    )
    shock_n_days: int
    shock_mape: float | None = Field(
        description="Pooled MAPE over shock days, percent; None "
        "when the pool is empty"
    )
    shock_coverage: float | None = Field(
        description="Pooled band coverage over shock days"
    )
    rest_n_days: int
    rest_mape: float | None = Field(
        description="Pooled MAPE over the same series x horizon's "
        "scored days outside the window"
    )
    rest_coverage: float | None
    delta_mape_pp: float | None = Field(
        description="shock MAPE - rest MAPE, percentage points; "
        "None unless the row is graded"
    )


class OpsReport(BaseModel):
    """The desk's track record, as one re-performable artefact."""

    report_id: str = Field(description="Content address: OPS-<sha256[:16]>")
    analytics_pack_version: str
    accuracy_pack_version: str = Field(
        description="The accuracy pack the grid and ledger were "
        "struck under, as the stored results name it"
    )
    signal_pack_version: str
    event_pack_version: str
    history_start: date = Field(description="The manifest's first history day")
    history_end: date = Field(description="The manifest's last history day")
    n_backtest_results: int = Field(
        description="Stored backtest results the report reads"
    )
    trends: list[AccuracyTrendRow]
    signal_outcomes: list[SignalOutcomeRow]
    origin_signal_skips: list[OriginSignalSkip] = Field(
        description="Grid origins the engine refused, named with "
        "the refusal — the harness's honesty, carried here"
    )
    transmission: list[TransmissionClassRow]
    shock_windows: list[ShockWindowRow]
    small_sample_classes: list[str] = Field(
        description="Event classes the report names small-sample "
        "or unmeasurable — the caveat, collected on the face"
    )


def report_content_id(report: OpsReport) -> str:
    payload = report.model_dump(mode="json", exclude={"report_id"})
    return _content_id("OPS-", payload)
