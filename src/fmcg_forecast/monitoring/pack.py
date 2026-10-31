"""The monitoring pack — what the service owes its
operators, as data.

F20-AM2's three questions, and the discipline that lets
each be answered from artefacts rather than asserted:

- **What did the model cost?** Every call the system
  makes through its model port is recorded, one run
  record per completed call: the profile that served it,
  the purpose it served, hashes of the request and the
  response — never their text — character counts, token
  figures from the pack's stated estimator, and a cost
  in integer nano-USD priced at the pack's stated
  reference rates. A board's cost total is the exact
  sum of its run records, or it does not verify.
- **What did the feeds do?** Ingest batches are the job
  records — the board folds them per source: batches,
  rows received, loaded, quarantined, refusals — from
  the batch artefacts themselves, never from a log.
- **What is late?** Each registered source carries a
  cadence in the ingest registry; the pack states the
  freshness window each cadence is owed, in hours. A
  source whose last loaded batch is older than its
  window at the board's as-of is a breach, named on the
  board. A source that has never loaded is named
  never-loaded on every board, never silently absent.
  A one-off source owes no window and reads as such.

The stated rules:

- **Purposes are a closed vocabulary**, one per model
  port method: sentiment_extraction, commentary_drafting,
  scenario_parsing, dashboard_parsing. A run record
  naming anything else does not verify.
- **Tokens are estimated, never invented.** The
  estimator is stated: tokens = ceil(characters / 4)
  over the canonical JSON of the request or response.
  It is a sizing rule for cost estimation, not a
  provider's tokenizer count, and the pack says so.
- **Rates are reference figures.** The pack states a
  rate card per hosted profile for estimation. They
  are the pack's figures, not a provider quote and
  never a billed amount; a deployment replaces them
  with its contracted rates by striking a new pack
  version. The offline profile is UNRATED: its calls
  carry cost None — never zero, because free-to-run
  locally is a fact about the deployment, not a price
  of zero the ledger may sum into a total.
- **Only completed calls are recorded.** A port call
  that raises — a hosted profile refusing until
  configured, a transport failure — strikes no record:
  the ledger prices work done, and a refusal consumes
  nothing. The refusal itself is the caller's error to
  surface, exactly as the port raises it.
- **The ledger stores hashes, never text.** A prompt
  may carry a corpus headline or a desk's what-if; the
  run record keeps the SHA-256 of its canonical form
  and its size, so any call can be re-identified and
  re-priced without the ledger becoming a second copy
  of the desk's words.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

PURPOSES: tuple[str, ...] = (
    "sentiment_extraction",
    "commentary_drafting",
    "scenario_parsing",
    "dashboard_parsing",
)

# The port method each purpose prices — the recording
# port strikes exactly one record per method call.
PURPOSE_BY_METHOD: dict[str, str] = {
    "extract_sentiment": "sentiment_extraction",
    "draft_commentary": "commentary_drafting",
    "parse_scenario": "scenario_parsing",
    "parse_dashboard": "dashboard_parsing",
}

COST_BASIS_RATED = "reference_rate"
COST_BASIS_UNRATED = "unrated_profile"


class ProfileRate(BaseModel):
    """One profile's place on the pack's rate card."""

    profile: str
    rated: bool = Field(
        description="False when the profile carries no rate: "
        "its calls record cost None, never zero"
    )
    input_nano_usd_per_million: int = Field(
        description="Reference rate per million estimated "
        "request tokens, integer nano-USD; 0 when unrated"
    )
    output_nano_usd_per_million: int = Field(
        description="Reference rate per million estimated "
        "response tokens, integer nano-USD; 0 when unrated"
    )
    note: str = Field(description="What this rate is, stated")


class CadenceWindow(BaseModel):
    """The freshness window one cadence is owed."""

    cadence: str
    max_age_hours: int | None = Field(
        description="The oldest a source's last loaded batch "
        "may be at a board's as-of before the board names it "
        "late; None when the cadence owes no window (a "
        "one-off bootstrap), which reads one_off on the board"
    )


class MonitoringPack(BaseModel):
    version: str
    purposes: list[str]
    chars_per_token: int = Field(
        description="The stated token estimator: estimated "
        "tokens = ceil(characters / chars_per_token) over the "
        "canonical payload text"
    )
    rates: list[ProfileRate]
    cadence_windows: list[CadenceWindow]
    rules: str = Field(description="The monitoring discipline, stated")


MONITORING_PACK_V1 = MonitoringPack(
    version="2026.10.1",
    purposes=list(PURPOSES),
    chars_per_token=4,
    rates=[
        ProfileRate(
            profile="offline",
            rated=False,
            input_nano_usd_per_million=0,
            output_nano_usd_per_million=0,
            note="the offline profile runs in-process and carries "
            "no rate — its calls record cost None, never zero",
        ),
        ProfileRate(
            profile="anthropic",
            rated=True,
            input_nano_usd_per_million=3_000_000_000,
            output_nano_usd_per_million=15_000_000_000,
            note="pack-stated reference figure for estimation "
            "(USD 3 / USD 15 per million tokens); not a "
            "provider quote, never a billed amount",
        ),
        ProfileRate(
            profile="bedrock",
            rated=True,
            input_nano_usd_per_million=3_000_000_000,
            output_nano_usd_per_million=15_000_000_000,
            note="pack-stated reference figure for estimation "
            "(USD 3 / USD 15 per million tokens); not a "
            "provider quote, never a billed amount",
        ),
        ProfileRate(
            profile="nim",
            rated=True,
            input_nano_usd_per_million=500_000_000,
            output_nano_usd_per_million=2_000_000_000,
            note="pack-stated reference figure for estimation "
            "(USD 0.50 / USD 2 per million tokens); not a "
            "provider quote, never a billed amount",
        ),
    ],
    cadence_windows=[
        CadenceWindow(cadence="hourly", max_age_hours=3),
        CadenceWindow(cadence="daily", max_age_hours=36),
        CadenceWindow(cadence="weekly", max_age_hours=240),
        CadenceWindow(cadence="once", max_age_hours=None),
    ],
    rules=(
        "every completed model-port call strikes exactly one "
        "run record — profile, purpose from the closed "
        "vocabulary, SHA-256 hashes of the canonical request "
        "and response (never their text), character counts, "
        "token figures from the stated estimator "
        "(ceil(chars / 4)) and a cost in integer nano-USD at "
        "the pack's reference rates; an unrated profile's "
        "calls carry cost None, never zero; a call that "
        "raises strikes no record; a board is struck as-of a "
        "stated instant and folds only records and batches "
        "at or before it; board cost totals are the exact "
        "sum of the rated run records they fold, with "
        "unrated calls counted separately and never priced; "
        "freshness is judged per registered source against "
        "the pack's cadence windows — late sources are "
        "named as breaches, never-loaded sources are named "
        "on every board, and a one-off source owes no window"
    ),
)


def load_monitoring_pack(version: str | None = None) -> MonitoringPack:
    """Load the monitoring pack, fail-closed.

    An unknown version is an error, never a silent
    fallback — a run record must name the pack it was
    priced under, and a board the pack it was judged
    under.
    """
    if version is None or version == MONITORING_PACK_V1.version:
        return MONITORING_PACK_V1
    raise ValueError(f"unknown monitoring pack version: {version!r}")


def rate_for(pack: MonitoringPack, profile: str) -> ProfileRate | None:
    for rate in pack.rates:
        if rate.profile == profile:
            return rate
    return None


def window_for(pack: MonitoringPack, cadence: str) -> CadenceWindow | None:
    for window in pack.cadence_windows:
        if window.cadence == cadence:
            return window
    return None
