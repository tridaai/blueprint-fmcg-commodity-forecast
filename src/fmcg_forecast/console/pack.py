"""The console pack — how the desk works its queues, as data.

R13's rules are stated here, versioned, never buried in code:
the order the forecast review queue is worked in, the
vocabulary a rejection must name its reason from, the acts an
event can be triaged by, and the bars a coverage pre-flight
judges a series against before a run. A change to any of it is
a new pack version, and every act and pre-flight report names
the version it was struck under — the verifier re-performs
under exactly that pack.

Nothing in this pack softens a judgement another layer made:
the queue orders by the accuracy ledger's own states, the
triage gate reads the events layer's own transmission
verdicts, and the pre-flight names gaps — it never fills them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# The rejection vocabulary: a reviewer who sends a forecast
# back names why, from this stated list. "other_stated_reason"
# is admissible only with the reason spelled out in the act's
# note — a bare "other" is not a reason.
REJECTION_REASONS: tuple[str, ...] = (
    "stale_inputs",
    "accuracy_not_credible",
    "event_basis_unaccepted",
    "duplicate_of_newer_run",
    "other_stated_reason",
)

# The triage acts an event can receive. Confirm clears an
# event for the official view on a named analyst's judgement,
# amend replaces its declaration (a new declaration, never an
# edit), retire withdraws it. Superseded is not an act — it is
# the state an event is left in by an amend.
TRIAGE_ACTS: tuple[str, ...] = ("confirm", "amend", "retire")


class ConsolePack(BaseModel):
    version: str
    rejection_reasons: list[str] = Field(
        description="The stated vocabulary a forecast rejection "
        "must name its reason from"
    )
    triage_acts: list[str] = Field(
        description="The acts the event triage queue admits"
    )
    queue_state_order: list[str] = Field(
        description="The review queue works accuracy states in "
        "this order — degraded first, because a degraded draft "
        "is the one the desk must not wave through, then "
        "unmeasured, then measured"
    )
    obs_fresh_days: int = Field(
        description="A driver whose last observation is within "
        "this many calendar days of the pre-flight's as-of "
        "reads present; older reads stale. Four days covers "
        "both reporting patterns in the catalogue — the "
        "Mon–Sat weekend gap is two days, coffee's Tue/Fri "
        "gap is four"
    )
    sentiment_fresh_days: int = Field(
        description="A commodity whose newest sentiment index "
        "week ended within this many days of the as-of reads "
        "current; older reads stale. Twenty-eight days "
        "mirrors the sentiment pack's own estimation recency "
        "floor, so the pre-flight and the engine judge "
        "recency by the same bar"
    )
    queue_rule: str = Field(
        description="The review-queue rule, stated — the "
        "engine performs exactly this"
    )
    rejection_rule: str = Field(
        description="The rejection rule, stated"
    )
    triage_rule: str = Field(
        description="The triage and official-view gate rule, "
        "stated"
    )
    preflight_rule: str = Field(
        description="The pre-flight rule, stated — including "
        "how a run carries the named gaps"
    )


CONSOLE_PACK_V1 = ConsolePack(
    version="2026.10.1",
    rejection_reasons=list(REJECTION_REASONS),
    triage_acts=list(TRIAGE_ACTS),
    queue_state_order=["degraded", "unmeasured", "measured"],
    obs_fresh_days=4,
    sentiment_fresh_days=28,
    queue_rule=(
        "The review queue holds every draft forecast no "
        "rejection act stands against, ordered by the accuracy "
        "state the ledger pinned on it — degraded first, then "
        "unmeasured, then measured — and inside a state by "
        "as-of ascending (the longest-waiting draft first), "
        "then forecast id. Each row carries the forecast's own "
        "figures (the P50 at each horizon and the 30-day "
        "contribution lines), the series' current official "
        "forecast beside it with the 30-day P50 difference, the "
        "triage and verification state of every event it "
        "applies, and the blockers that would refuse its "
        "approval today. A rejected draft leaves the queue: "
        "it has been reviewed, and its record is the rejection "
        "act, not a queue row."
    ),
    rejection_rule=(
        "Rejecting a forecast is a named reviewer's act with a "
        "reason from the pack's vocabulary (a note is required "
        "when the reason is other_stated_reason, and the "
        "reason must be spelled out there). A rejection stands "
        "against the draft it names: an official forecast "
        "cannot be rejected, a rejected forecast cannot be "
        "rejected again, and a rejected forecast can never be "
        "approved — approval of it is refused naming the "
        "rejection, and the desk's remedy is a new run, which "
        "is a new artefact the rejection does not touch. The "
        "approval act pins the exact artefact reviewed because "
        "forecasts are content-addressed: the id approved is "
        "the decomposition the reviewer read, and no other."
    ),
    triage_rule=(
        "A declared event lands in the triage queue in the "
        "lane its transmission verdict names — verified, "
        "unverified or not_measurable — and its triage state "
        "is the fold of its triage acts: declared with none, "
        "then the latest act by (acted_on, act_id) decides — "
        "confirm leaves it confirmed, retire leaves it "
        "retired, amend leaves it superseded by the "
        "replacement declaration the act records. An event "
        "enters the official view only when it is officially "
        "clear: its transmission verdict is verified, or a "
        "named analyst has confirmed it in triage. A retired "
        "or superseded event is never clear, and approval of a "
        "forecast carrying an event that is not clear is "
        "refused naming each blocking event. Until cleared, "
        "an event still contributes its full amount to draft "
        "forecasts — with its verdict and triage state "
        "labelled on every read — and retired or superseded "
        "events are excluded from new runs altogether: their "
        "replacement (for an amend) is what the registry "
        "feeds the engine."
    ),
    preflight_rule=(
        "A pre-flight is struck per series at an as-of, from "
        "the store alone: for every driver in the catalogue's "
        "full driver list, present (last observed within the "
        "pack's freshness bar), stale (older, with the last "
        "observed date and its age) or missing (the series "
        "does not report it, or has never reported it); the "
        "sentiment index's recency against the pack's "
        "sentiment bar (current, stale, or absent when no "
        "index week stands); and the backtest coverage per "
        "horizon from the accuracy ledger (measured, degraded "
        "or unmeasured). Every failed check is a named gap, in "
        "a stated order — drivers in catalogue order, then "
        "sentiment, then coverage by horizon — and the "
        "checklist is gapped when the list is non-empty, clear "
        "when it is empty. A forecast run may pin a pre-flight "
        "struck for its own series and as-of: the run then "
        "carries the checklist's named gaps verbatim on the "
        "artefact beside its own missing-driver list — the "
        "run-anyway path, with the gaps on the record rather "
        "than discovered after the number is quoted. A "
        "pre-flight struck for another series or another "
        "as-of cannot be pinned."
    ),
)


def load_console_pack(version: str | None = None) -> ConsolePack:
    """Load the console pack, fail-closed.

    An unknown version is an error, never a silent fallback —
    an act or report struck under one pack must never be
    quietly re-read under another.
    """
    if version is None or version == CONSOLE_PACK_V1.version:
        return CONSOLE_PACK_V1
    raise ValueError(f"unknown console pack version: {version!r}")
