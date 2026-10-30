"""Operator console artefacts (R13: F20-OW2, F20-OW3, F20-OW4).

Three stored families, all content-addressed and insert-only:

- a *forecast rejection* — the review queue's second act
  (F20-OW2). Approval has been a recorded act since R2;
  rejection is now one too, with a reason from the console
  pack's vocabulary. A forecast's review state is the fold of
  its acts: draft, official (approval stands), or rejected
  (rejection stands) — and a rejected draft can never cross
  to official; the remedy is a new run.
- an *event triage act* — confirm, amend or retire
  (F20-OW3), recorded against a declared event. The event's
  triage state is the fold of its acts; an amend act names
  the replacement declaration it struck, and the event it
  leaves behind reads superseded.
- a *pre-flight report* — the coverage checklist for one
  series at one as-of (F20-OW4): per-driver states, sentiment
  recency and backtest coverage, with every failed check a
  named gap. A forecast run may pin the report; the pin
  (report id, pack version, the gaps verbatim) rides on the
  forecast artefact.

The queue rows and the console view are derived reads, never
stored: they recompute from the artefacts of record on every
call, so the console can show nothing the record does not
support.
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


class ForecastRejection(BaseModel):
    """The act that sends a draft forecast back (F20-OW2)."""

    rejection_id: str = Field(description="Content address: REJ-<sha256[:16]>")
    forecast_id: str
    rejected_by: str = Field(description="The named reviewer who rejected it")
    role: str
    decided_on: date
    reason: str = Field(
        description="One of the console pack's stated rejection "
        "reasons"
    )
    note: str = Field(
        default="",
        description="The reviewer's note; required, with the "
        "reason spelled out, when the reason is "
        "other_stated_reason",
    )
    pack_version: str


def rejection_content_id(rejection: ForecastRejection) -> str:
    payload = rejection.model_dump(mode="json", exclude={"rejection_id"})
    return _content_id("REJ-", payload)


class EventTriageAct(BaseModel):
    """One triage act on a declared event (F20-OW3)."""

    act_id: str = Field(description="Content address: TRI-<sha256[:16]>")
    event_id: str
    act: Literal["confirm", "amend", "retire"] = Field(
        description="confirm clears the event for the official "
        "view on the actor's judgement; amend replaces its "
        "declaration; retire withdraws it"
    )
    actor: str = Field(description="The named analyst who acted")
    role: str
    acted_on: date
    replacement_event_id: str | None = Field(
        default=None,
        description="Amend only: the new declaration that "
        "replaces the triaged event",
    )
    note: str = ""
    pack_version: str


def triage_act_content_id(act: EventTriageAct) -> str:
    payload = act.model_dump(mode="json", exclude={"act_id"})
    return _content_id("TRI-", payload)


class DriverCheck(BaseModel):
    """One driver's line on a pre-flight checklist."""

    driver: str
    state: Literal["present", "stale", "missing"] = Field(
        description="present: observed within the pack's "
        "freshness bar; stale: observed, but older; missing: "
        "the series does not report the driver, or has never "
        "reported it"
    )
    last_observed_date: date | None
    age_days: int | None = Field(
        description="Days from the last observation to the "
        "as-of; None when never observed"
    )


class SentimentCheck(BaseModel):
    """The sentiment line on a pre-flight checklist."""

    state: Literal["current", "stale", "absent"] = Field(
        description="current: the newest index week ended "
        "within the pack's sentiment bar; stale: older; "
        "absent: no index week stands for the commodity"
    )
    last_index_week_end: date | None
    age_days: int | None = Field(
        description="Days from the newest index week's end to "
        "the as-of; None when absent"
    )
    n_index_weeks: int


class HorizonCoverage(BaseModel):
    """One horizon's backtest coverage on a pre-flight."""

    horizon_days: int
    state: Literal["measured", "degraded", "unmeasured"] = Field(
        description="The accuracy ledger's own state for the "
        "series at this horizon: degraded where its record is "
        "stamped degraded, unmeasured where no record stands"
    )
    record_id: str | None
    n_origins: int
    mape: float | None


class PreflightReport(BaseModel):
    """The coverage pre-flight for one series at one as-of."""

    report_id: str = Field(description="Content address: PRE-<sha256[:16]>")
    pack_version: str
    commodity: str
    market: str
    as_of: date
    last_observation_date: date | None = Field(
        description="The series' last modal-price observation "
        "on or before the as-of"
    )
    drivers: list[DriverCheck] = Field(
        description="Every driver in the catalogue's full "
        "driver list, in catalogue order"
    )
    sentiment: SentimentCheck
    coverage: list[HorizonCoverage] = Field(
        description="One line per forecast horizon, ascending"
    )
    gaps: list[str] = Field(
        description="Every failed check, named, in the pack's "
        "stated order — the list a pinned run carries verbatim"
    )
    state: Literal["clear", "gapped"] = Field(
        description="clear when the gap list is empty"
    )


def preflight_content_id(report: PreflightReport) -> str:
    payload = report.model_dump(mode="json", exclude={"report_id"})
    return _content_id("PRE-", payload)


class AppliedEventFlag(BaseModel):
    """One applied event's standing, on a review-queue row."""

    event_id: str
    verification_status: str = Field(
        description="The events layer's transmission verdict: "
        "verified | unverified | not_measurable — or "
        "not_in_registry for an adjustment no declaration "
        "stands behind"
    )
    triage_state: str = Field(
        description="declared | confirmed | retired | "
        "superseded | not_in_registry"
    )


class ReviewQueueRow(BaseModel):
    """One draft awaiting review, with its comparison beside it."""

    forecast_id: str
    commodity: str
    market: str
    as_of: date
    accuracy_state: str = Field(
        description="The accuracy state the ledger pinned on "
        "the forecast: degraded | unmeasured | measured"
    )
    degraded_horizons: list[int]
    p50_by_horizon: dict[str, float] = Field(
        description="The forecast's P50 at the 7/30/90-day "
        "horizons, INR/quintal"
    )
    contributions_30d: dict[str, float] = Field(
        description="The 30-day contribution per driver line, "
        "INR/quintal — the side-by-side the reviewer reads"
    )
    prior_official_id: str | None = Field(
        description="The series' current official forecast, "
        "or None when none stands"
    )
    prior_official_as_of: date | None
    prior_p50_30: float | None
    delta_p50_30: float | None = Field(
        description="This draft's 30-day P50 minus the prior "
        "official's, INR/quintal; None when no official stands"
    )
    events: list[AppliedEventFlag]
    blockers: list[str] = Field(
        description="The reasons approval would be refused "
        "today — unconfirmed, retired or superseded events "
        "the forecast carries, each named"
    )
    preflight_id: str | None = Field(
        description="The pre-flight the run pinned, if any"
    )


class TriageQueueRow(BaseModel):
    """One event awaiting triage, in its verdict's lane."""

    event_id: str
    event_class: str
    commodity: str
    window_start: date
    window_end: date | None
    claimed_peak_log: float
    basis: str
    declared_by: str
    declared_on: date
    verification_status: Literal["verified", "unverified", "not_measurable"]
    measured_ratio: float | None
    triage_state: str
    lane: Literal["verified", "unverified", "not_measurable"] = Field(
        description="The lane is the verdict's own word — "
        "unverified-transmission events sit visibly apart "
        "from verified ones"
    )
