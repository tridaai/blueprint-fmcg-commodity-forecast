"""Scenario artefacts (R6, Law 5).

A *scenario request* is the parse of a desk what-if: the original
text (verbatim), the lever set it parsed into under the scenario
pack, and the pack version. A request that does not fit the
catalogue never becomes an artefact — it is refused with the
offending clause named.

A *scenario run* is a pinned fork: it names its request, its base
forecast (by content address), the shifts the levers became (with
the history statistics they were computed from, so a verifier can
re-perform them), the scenario-local events it created (extensions
and hypotheticals — full registry-shaped artefacts that live on
the run, never in the registry), and the fork forecast itself —
a full forecast artefact, produced by the same engine, that lives
on the run and never enters the desk's forecast record. The base
forecast is never mutated by any of this.

An *adoption act* is the recorded human decision that makes a
scenario the desk's adopted view for its series. Adoption
supersedes the previously adopted scenario for the series by
link; the lifecycle status (draft -> adopted -> superseded) is
state about the artefact, flipped only by an adoption act, and —
like the forecast status — is kept out of the content address.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from fmcg_forecast.events.models import MarketEvent
from fmcg_forecast.forecast.models import Forecast


class LeverApplication(BaseModel):
    """One lever of a scenario, as parsed or as posted."""

    lever: str = Field(description="A name from the scenario pack's catalogue")
    value: float | None = Field(
        default=None,
        description="The lever's stated value in its pack unit "
        "(numeric levers; for hypothetical_event, the peak price "
        "effect in percent)",
    )
    event_id: str | None = Field(
        default=None,
        description="The registry event an event / event_extension "
        "lever names",
    )
    extra_days: int | None = Field(
        default=None, description="Days added by an event_extension lever"
    )
    event_class: str | None = Field(
        default=None, description="The class a hypothetical_event lever declares"
    )
    start_offset_days: int | None = Field(
        default=None,
        description="Days into the forecast horizon before a "
        "hypothetical event's window opens (0 = the window opens "
        "on the first forecast day, as_of + 1)",
    )
    duration_days: int | None = Field(
        default=None, description="A hypothetical event's window length in days"
    )
    decay_days: int | None = Field(
        default=None,
        description="A hypothetical event's decay; None takes the "
        "pack's stated default",
    )
    clause: str | None = Field(
        default=None,
        description="The source clause, verbatim, when the lever "
        "came from a text parse — the parse's provenance",
    )


class ScenarioRequest(BaseModel):
    """A what-if, parsed into the bounded lever catalogue."""

    request_id: str
    commodity: str
    market: str
    source_text: str | None = Field(
        description="The desk's words, verbatim, when the request "
        "was typed; None for a structured lever set posted directly"
    )
    intake: Literal["text", "structured"]
    model_profile: str = Field(
        description="The model-port profile that produced the "
        "lever set (offline grammar or a hosted structured parse)"
    )
    levers: list[LeverApplication]
    pack_version: str


def request_content_id(request: ScenarioRequest) -> str:
    """The content address: a hash over the parse, not the id."""
    payload = request.model_dump(mode="json", exclude={"request_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "SCRQ-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]


class AppliedShift(BaseModel):
    """What one numeric lever became inside the engine.

    Recorded on the run with the history statistics the conversion
    used, so the shift is re-performable from the store and the
    pack alone.
    """

    lever: str
    driver: str = Field(description="The forecast line the lever moves")
    mode: Literal["add", "add_clip", "set_start"] = Field(
        description="add: the value is added to the driver's input "
        "path on every horizon day. add_clip: added, then the path "
        "is clipped to the stated range. set_start: the path starts "
        "at the value and decays at the driver's persistence."
    )
    value: float = Field(description="The shift in the driver's input units")
    clip_min: float | None = None
    clip_max: float | None = None
    basis_stats: dict = Field(
        description="The stated statistics the conversion used "
        "(history sds, last observed flows), named"
    )


class ScenarioRun(BaseModel):
    """A pinned fork of a base forecast under a lever set."""

    scenario_id: str
    request_id: str
    base_forecast_id: str
    fork_forecast_id: str
    commodity: str
    market: str
    as_of: date = Field(description="The base forecast's as_of — the fork re-estimates nothing")
    author: str = Field(description="The named desk user who ran the scenario")
    created_on: date
    pack_version: str
    status: Literal["draft", "adopted", "superseded"] = "draft"
    shifts: list[AppliedShift]
    scenario_events: list[MarketEvent] = Field(
        description="Scenario-local events the levers created "
        "(extensions of registry events, hypothetical events) — "
        "full artefacts on the run; the registry itself is "
        "untouched by them"
    )
    fork: Forecast = Field(
        description="The fork forecast artefact: the base's "
        "estimation with the levers applied through the same "
        "contribution machinery. It lives here, never in the "
        "desk's forecast record, and its own status stays draft "
        "forever — adoption is the scenario's act, not a "
        "forecast approval."
    )


def scenario_content_id(run: ScenarioRun) -> str:
    """The content address: over the pin, the levers' effects and
    the fork — not the id, the lifecycle status, or the day the
    run happened to be made (a re-run of the same fork is the
    same artefact)."""
    payload = run.model_dump(
        mode="json", exclude={"scenario_id", "status", "created_on"}
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "SCN-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]


class ScenarioAdoption(BaseModel):
    """The recorded act that makes a scenario the desk's adopted view."""

    adoption_id: str
    scenario_id: str
    adopter: str
    role: str
    decided_on: date
    supersedes_scenario_id: str | None = Field(
        description="The previously adopted scenario for the "
        "series, superseded by this act; None for the first adoption"
    )


class ScenarioDiffDay(BaseModel):
    """One horizon day of the fork-vs-base difference."""

    forecast_date: date
    contributions: dict[str, float] = Field(
        description="Per-driver contribution difference (fork - "
        "base), INR/quintal, exact to the paisa"
    )
    events_adjustment: float = Field(description="Events difference (fork - base), INR/quintal")
    p50: float = Field(description="P50 difference (fork - base), INR/quintal")


class ScenarioDiff(BaseModel):
    """The diff view: fork against base, computed from the two
    stored artefacts — per-driver, per-day, summing exactly to
    the P50 difference because both decompositions are exact and
    the baseline is shared."""

    scenario_id: str
    base_forecast_id: str
    fork_forecast_id: str
    days: list[ScenarioDiffDay]
    driver_totals: dict[str, float] = Field(
        description="Per-driver sum of the daily differences over "
        "the whole horizon, INR/quintal"
    )
    events_total: float
    p50_total: float
    at_horizons: dict[str, float] = Field(
        description="P50 difference on the day each stated horizon closes"
    )
