"""Thin-data assessment artefacts.

An *assessment* is a stored, content-addressed artefact pinned
to one forecast: the forecast's id, the accuracy records its
tiers rest on, and the pack version it was computed under all
ride on its face. It states window evidence, not a padded
single number: operating-day coverage over the pack's stated
windows, every driver's state with its last observed date, and
a confidence tier per forecast horizon with the reasons that
tier was — and was not — higher.

The tiers, windows and driver states are all computed in code
from stored observations, the pinned forecast and the accuracy
ledger. Nothing here is authored: the same store and forecast
always recompute the same assessment, which is what lets the
verifier re-perform it field for field.
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


class WindowCoverage(BaseModel):
    """Operating-day coverage over one stated window."""

    window_days: int = Field(description="The window, in calendar days")
    start: date = Field(description="First day of the window (inclusive)")
    end: date = Field(description="The as_of the window ends on")
    operating_days: int = Field(
        description="Days the market reports in the window, "
        "under the catalogue's reporting pattern"
    )
    observed_days: int = Field(
        description="Operating days carrying a modal-price observation"
    )
    coverage: float = Field(
        description="observed / operating, 4dp (1.0 when the "
        "market reports no days in the window)"
    )
    missing_operating_dates: list[date] = Field(
        description="Every operating day in the window with no "
        "modal-price observation, named — never absorbed"
    )


class DriverState(BaseModel):
    """One driver's evidence state for the series."""

    driver: str
    status: Literal["present", "missing", "stale"] = Field(
        description="missing = the catalogue does not report it "
        "for this commodity, or no row stands in the store; "
        "stale = reported, but its last observation is older "
        "than the pack's staleness bar"
    )
    last_observed_date: date | None = Field(
        description="The driver's last observation on or before "
        "as_of (for sentiment: the last index week's end); None "
        "when nothing stands"
    )
    age_days: int | None = Field(
        description="Days from the last observation to as_of"
    )
    detail: str = Field(description="The state's reason, stated")


class HorizonConfidence(BaseModel):
    """One horizon's earned confidence tier, with its evidence."""

    horizon_days: int
    tier: str = Field(
        description="unproven | thin | guarded | established — "
        "the tier the stated evidence earns under the pack"
    )
    accuracy_state: str = Field(
        description="The pinned accuracy slice's state: "
        "measured | degraded | unmeasured"
    )
    accuracy_record_id: str | None = Field(
        description="The ledger record the tier rests on; None "
        "when the horizon is unmeasured"
    )
    mape: float | None = Field(description="The record's pooled MAPE, percent")
    band_coverage: float | None = Field(
        description="The record's realised P10-P90 band coverage"
    )
    window_coverage: float = Field(
        description="Operating-day coverage over the horizon's "
        "own window (the 7/30/90-day window of the same length)"
    )
    history_coverage: float = Field(
        description="Operating-day coverage over the 365-day window"
    )
    interval_width_pct: float = Field(
        description="The forecast band's width at this horizon: "
        "(P90 - P10) / P50 * 100"
    )
    realised_vol_width_pct: float | None = Field(
        description="The central-80% width the series' own "
        "realised daily volatility implies at this horizon, "
        "percent of price; None when the history cannot state it"
    )
    interval_to_realised_ratio: float | None = Field(
        description="interval width / realised-vol width — a "
        "band far narrower than the series' own history is "
        "overconfidence, and the ratio names it"
    )
    reasons: list[str] = Field(
        description="Every bar this horizon failed and every "
        "cap applied — why the tier is not higher, stated"
    )


class ThinAssessment(BaseModel):
    assessment_id: str = Field(description="Content address: THN-<sha256[:16]>")
    commodity: str
    market: str
    as_of: date = Field(description="The pinned forecast's as_of")
    forecast_id: str = Field(description="The forecast this assessment judges")
    accuracy_record_ids: dict[str, str | None] = Field(
        description="Horizon (as text) -> the accuracy record "
        "pinned on the forecast for it, or None"
    )
    pack_version: str
    windows: list[WindowCoverage]
    drivers: list[DriverState]
    horizons: list[HorizonConfidence]
    named_gaps: list[str] = Field(
        description="Every missing or stale driver, named with "
        "its last observed date — the gaps every consumer "
        "surface states, verbatim"
    )
    summary_tier: str = Field(
        description="The weakest horizon's tier — the series "
        "is only as confident as its least-earned horizon"
    )


def assessment_content_id(assessment: ThinAssessment) -> str:
    payload = assessment.model_dump(mode="json", exclude={"assessment_id"})
    return _content_id("THN-", payload)
