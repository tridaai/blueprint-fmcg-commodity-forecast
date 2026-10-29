"""The buy-signal artefact.

A signal is content-addressed over everything that decided it:
the pinned forecast, the spot it was judged against, the pack
thresholds it cleared or missed, the accuracy state it inherited
(including the degraded horizons and the ledger records behind
them), the declared events overlapping its horizon, the forecast's
named missing drivers, and the reasoning lines themselves. Recompute
the same inputs and you land on the same artefact; alter any stored
field and the content address no longer agrees — the verifier
re-performs the whole computation and compares field for field.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

SignalValue = Literal["buy_now", "phased", "wait"]


class SignalEventRef(BaseModel):
    """One declared event whose window overlaps the horizon."""

    event_id: str
    event_class: str
    window_start: date
    window_end: date | None = Field(
        description="The declared window end; None while open-ended"
    )
    overlap_end: date = Field(
        description="Where the event's reach (window end plus its "
        "stated decay, or the horizon end while open-ended) stops "
        "inside the signal horizon"
    )
    claimed_peak_log_effect: float = Field(
        description="The declaration's claimed peak log-price effect"
    )


class BuySignal(BaseModel):
    signal_id: str = Field(description="Content address: SIG-<sha256[:16]>")
    commodity: str
    market: str
    forecast_id: str = Field(
        description="The pinned forecast artefact the call was "
        "computed from — the series' head at computation time"
    )
    forecast_status: str = Field(
        description="The pinned forecast's status (draft / official)"
    )
    as_of: date = Field(description="The pinned forecast's as_of")
    horizon_days: int
    spot_inr: float = Field(
        description="The last observed modal price on or before as_of"
    )
    spot_date: date
    p10_horizon_inr: float
    p50_horizon_inr: float
    p90_horizon_inr: float
    drift_pct: float = Field(
        description="(P50 at horizon - spot) / spot * 100, 4dp"
    )
    band_width_pct: float = Field(
        description="(P90 - P10) / P50 * 100 at the horizon, 4dp"
    )
    accuracy_state: str = Field(
        description="The pinned forecast's accuracy attachment "
        "state: measured / degraded / unmeasured"
    )
    accuracy_record_ids: list[str] = Field(
        description="The accuracy ledger records pinned behind the "
        "attachment, per horizon, where records exist"
    )
    degraded_horizons: list[int] = Field(
        description="Horizons whose pinned slice is degraded"
    )
    base_value: SignalValue = Field(
        description="The pack's base call, before accuracy caps"
    )
    value: SignalValue = Field(description="The call, after caps")
    caps_applied: list[str] = Field(
        description="Caps that fired, in application order: "
        "degraded_accuracy / unmeasured_accuracy"
    )
    active_events: list[SignalEventRef] = Field(
        description="Declared events for the commodity whose "
        "window (plus stated decay) overlaps the horizon"
    )
    missing_drivers: list[str] = Field(
        description="The pinned forecast's named missing drivers, "
        "carried onto the signal — thin data stays named"
    )
    reasoning: list[str] = Field(
        description="The reasoning lines, on the signal's face: "
        "inputs, thresholds, what decided it, caps, scope"
    )
    pack_version: str
    scope_note: str


def signal_content_id(signal: BuySignal) -> str:
    """The content address of a signal, recomputed from its fields."""
    payload = signal.model_dump(mode="json", exclude={"signal_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "SIG-" + hashlib.sha256(canonical.encode()).hexdigest()[:16]
