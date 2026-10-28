"""Event registry artefacts (R5, Law 4).

A *market event* is a declared shock: a named analyst's act,
recorded with its class, its effective window and its stated
transmission — which driver it moves, by what estimated peak
log-price effect, on what named basis. The registry is the only
way an event exists; nothing in this blueprint infers one from a
price move.

A *transmission verification* is the measurement layer's check of
a declared event against observed history: the claim on one side,
the seasonally-matched measured effect on the other, and a status
— verified, unverified (the flag rides on the event's face), or
not_measurable with the reason named. An *event impact* is the
desk's post-event review surface: the measured price path against
the no-event baseline projection over the window, both computed
in code from history.

Events are content-addressed like every other artefact in this
blueprint: the id hashes the full declaration, so a later edit to
a window, a magnitude or a basis breaks the id and is detectable.
Events are insert-only; a correction is a new declaration, never
an edit of the record.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

EventClass = Literal[
    "tariff_change",
    "export_restriction",
    "import_policy",
    "weather_shock",
    "logistics_disruption",
    "demand_shock",
]

EstimationBasis = Literal["announced_measure", "measured_analogue", "desk_estimate"]

EVENT_CLASSES: tuple[str, ...] = (
    "tariff_change",
    "export_restriction",
    "import_policy",
    "weather_shock",
    "logistics_disruption",
    "demand_shock",
)


class EventTransmission(BaseModel):
    """What a declaration claims the shock does, stated in full."""

    channel: str = Field(
        description="The driver the shock moves on its way to the "
        "price (one of the pack's channels for the event's class); "
        "modal_price is the direct price channel"
    )
    driver_effect: float | None = Field(
        description="The stated effect on the channel driver in "
        "its own terms where that is the measurable quantity "
        "(an export-flow multiplier of 0.05 for a ban, a "
        "weather-index deviation of -0.6 for a drought); None "
        "where the transmission is stated only in price terms"
    )
    peak_log_price_effect: float = Field(
        description="The signed peak effect on log price at the "
        "top of the ramp — the magnitude the forecast path "
        "carries and the verifier measures against"
    )
    basis: EstimationBasis = Field(
        description="The named estimation basis the magnitude rests on"
    )
    basis_detail: str = Field(
        description="The basis stated concretely: the announced "
        "measure and its size, the measured analogue, or the "
        "judgement — never a bare 'model estimate'"
    )


class MarketEvent(BaseModel):
    """One declared event in the registry."""

    event_id: str
    event_class: EventClass
    commodity: str = Field(description="Commodity scope: the event applies to every market of the commodity")
    window_start: date
    window_end: date | None = Field(
        description="The window's last day; None while the event "
        "is open-ended (still in force, no decay)"
    )
    direction: int = Field(description="+1 pushes prices up, -1 down — the sign of the claimed peak effect")
    transmission: EventTransmission
    decay_days: int = Field(
        description="After the window closes, the effect decays "
        "linearly to zero over this many days (the pack's path rule)"
    )
    description: str = Field(
        description="What happened, in generic terms — a tariff "
        "change, an export restriction — never a real programme, "
        "country measure name or company"
    )
    declared_by: str = Field(description="The named analyst (or record) that declared the event")
    declared_on: date
    pack_version: str
    origin: Literal["declared", "historical"] = Field(
        description="declared: a desk analyst's act. historical: "
        "seeded from the dataset manifest's planted record"
    )
    source_record_id: str | None = Field(
        description="For historical events, the manifest record "
        "the entry was seeded from (the R1 event / anomaly id)"
    )


def event_content_id(event: MarketEvent) -> str:
    """The content address: a hash over the whole declaration."""
    payload = event.model_dump(mode="json", exclude={"event_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "EVT-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]


class TransmissionVerification(BaseModel):
    """The measurement layer's verdict on one declared event.

    Computed from observed history at read time — history is
    insert-only, so the verdict is a pure function of the store.
    ``unverified`` is the flag the brief requires on the event's
    face: the claim and the measurement disagree, and the event
    says so wherever it is read.
    """

    event_id: str
    status: Literal["verified", "unverified", "not_measurable"]
    claimed_log_effect: float
    measured_log_effect: float | None = Field(
        description="Median across the commodity's markets of the "
        "per-market measured log effect; None when not measurable"
    )
    measured_ratio: float | None = Field(
        description="exp(measured_log_effect) — the measured price "
        "multiplier (x1.117 reads as an 11.7% rise)"
    )
    per_market_log_effects: dict[str, float | None] = Field(
        description="The measured log effect per market; None for "
        "a market whose measurement windows fall outside history"
    )
    ratio_to_claim: float | None = Field(
        description="measured / claimed — judged against the "
        "pack's stated band"
    )
    band: list[float] = Field(description="The pack's verification band [low, high]")
    reason: str = Field(description="Why the status is what it is, in one stated sentence")
    pack_version: str


class EventImpactDay(BaseModel):
    """One observed day of the what-happened view."""

    obs_date: date
    observed: float = Field(description="Observed modal price, INR/quintal")
    baseline_estimate: float = Field(
        description="The no-event baseline projection for that day, INR/quintal"
    )
    log_effect: float = Field(description="log(observed) - log(baseline_estimate)")


class EventImpact(BaseModel):
    """The post-event review surface for one event x market.

    The measured price path against the no-event baseline over
    the event window and its decay tail, both computed in code
    from history by the pack's stated impact rule. Distinct from
    the transmission verification: the impact view projects a
    baseline; the verification differences out seasonality with
    the year-over-year comparison. The two are separate reads and
    the docs say which is which.
    """

    event_id: str
    commodity: str
    market: str
    state: Literal["measured", "not_measurable"]
    reason: str
    window_start: date
    tail_end: date | None = Field(
        description="The last day of the review window (window end "
        "+ decay tail; the window start for an open-ended event "
        "is reviewed through the last observed day instead — "
        "stated on the artefact)"
    )
    days: list[EventImpactDay]
    mean_log_effect: float | None = Field(
        description="Mean log effect over the event window's observed days"
    )
    peak_log_effect: float | None = Field(
        description="The window day's log effect furthest from zero, signed"
    )
    mean_price_ratio: float | None = Field(description="exp(mean_log_effect)")
    fit_obs: int = Field(description="Pre-window observations the baseline was fitted on")
    fit_span_days: int
