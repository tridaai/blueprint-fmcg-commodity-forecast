"""The integrations pack — how the desk's systems may
plug into this one, as data.

F20-IA1, F20-IA2 and F20-DR2 share one question: what
leaves this system, in whose name, and how does anyone
prove later what was sent? The pack states the rules
each surface is judged under:

- **Scoped tokens (IA1).** An integration presents a
  bearer secret. The token artefact stores the
  secret's SHA-256 and nothing else about it — the
  secret itself is shown exactly once, at issue, and
  no read surface can return it. A token names a
  closed set of surfaces from the pack's vocabulary;
  presenting the token binds the request to those
  surfaces: an out-of-scope read is refused 403, an
  unknown or revoked secret is refused 401. A request
  presenting NO token keeps the local posture the
  desk's own reads have always had — the token
  discipline binds integrations that present one, and
  the pack says so rather than pretending the local
  surface is authenticated. Revocation is an act by a
  named person; a revoked token's secret is dead from
  the act on, and the fold of its acts is its state.
- **Signed webhooks (IA1).** A subscription names an
  endpoint, a shared secret and a closed set of event
  kinds: alert_raised, forecast_approved,
  event_triaged — the three moments the desk's other
  tools asked to react to. A delivery's payload is the
  canonical JSON of the source artefact's own read:
  what a subscriber receives is byte-for-byte what the
  API would return for that artefact, never a second
  summary that could drift from it. The signature is
  HMAC-SHA256 over the payload bytes under the
  subscription's secret, sent in the pack's stated
  header, so a receiver verifies with the secret and
  the bytes alone. The subscription secret is
  server-side configuration: it stands on the
  artefact so deliveries can be signed and
  re-performed, and it is redacted on every read —
  reads show that a secret is set and its hash prefix,
  never the secret. Every delivery attempt is an
  artefact: the payload, its hash, its signature, the
  outcome. A failed attempt is recorded with its
  error named, never dropped; dispatch is idempotent
  — a (subscription, artefact) pair with a delivered
  attempt is never delivered twice.
- **Board-pack exports (DR2).** A pack export is a
  file set struck as-of a stated date from artefacts
  only: the official forecasts section (every approved
  forecast's full day path), the accuracy summary (the
  ledger as it stands), the active events section
  (registry events in force on the date, retired
  events excluded, triage state on the row) and the
  buy signals section. Each section renders as CSV;
  the set also carries a print-ready PDF summary and a
  checksum manifest naming every other file's SHA-256
  and size. The pack artefact stores the whole file
  set, so a pack can be re-performed byte for byte:
  rebuild at the same as-of over the same store and
  the files must match exactly, and a single altered
  byte in any stored file breaks its manifest hash
  and is named.
- **Export jobs (IA2).** A job is requested as an
  artefact and completed by an act: the request and
  the output are separate artefacts joined by the
  completion act, so the desk can ask now and collect
  later, and the job's state is the fold of its acts.
  A completed job's pack is the same build the
  synchronous path strikes for the same as-of — byte
  identical, because both call the one builder.
- **Tools (IA2).** The read tools are catalogued as
  data in the repo's MCP shape — name, stated purpose,
  input schema, the surface they read. A tool response
  carries figures only as (name, value, artefact id)
  triples: no figure travels without the artefact it
  was read from, and a tool asked for an artefact that
  does not exist refuses by name rather than inventing
  a figure.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# The surfaces a token may be scoped to — the API's
# route families, as the pack names them. A route not
# in ROUTE_SURFACES and not open is judged under
# DEFAULT_SURFACE.
SURFACES: tuple[str, ...] = (
    "forecasts",
    "dashboards",
    "board",
    "signals",
    "planning",
    "events",
    "scenarios",
    "alerts",
    "console",
    "data",
    "operations",
    "admin",
)

# Route prefix -> surface. Longest matching prefix
# wins. /health and /readiness carry no surface: they
# answer under any token or none.
ROUTE_SURFACES: tuple[tuple[str, str], ...] = (
    ("/integrations", "admin"),
    ("/access", "admin"),
    ("/desk", "admin"),
    ("/masterdata", "admin"),
    ("/forecasts", "forecasts"),
    ("/backtests", "forecasts"),
    ("/accuracy", "forecasts"),
    ("/dashboards", "dashboards"),
    ("/board", "board"),
    ("/signals", "signals"),
    ("/planning", "planning"),
    ("/market-events", "events"),
    ("/events", "events"),
    ("/scenarios", "scenarios"),
    ("/alerts", "alerts"),
    ("/console", "console"),
    ("/catalogue", "data"),
    ("/series", "data"),
    ("/coverage", "data"),
    ("/manifest", "data"),
    ("/ingest", "operations"),
    ("/analytics", "operations"),
    ("/geo", "operations"),
    ("/thin-data", "operations"),
    ("/intake", "operations"),
    ("/sentiment", "operations"),
    ("/screening", "operations"),
    ("/monitoring", "operations"),
)
OPEN_PATHS: tuple[str, ...] = ("/health", "/readiness")
DEFAULT_SURFACE = "data"

EVENT_KINDS: tuple[str, ...] = (
    "alert_raised",
    "forecast_approved",
    "event_triaged",
)

SIGNATURE_HEADER = "x-fmcg-signature"
EVENT_HEADER = "x-fmcg-event"
DELIVERY_HEADER = "x-fmcg-delivery"
SIGNATURE_ALGORITHM = "hmac-sha256"

TOKEN_SECRET_BYTES = 24  # secrets.token_urlsafe(24) -> 32 chars


class ExportSection(BaseModel):
    """One section of the board pack, as the pack states it."""

    name: str = Field(description="The section and file stem")
    title: str = Field(description="What the section holds, stated")
    columns: list[str] = Field(description="The CSV columns, in order")
    source: str = Field(
        description="The artefacts the section folds, stated"
    )


class IntegrationsPack(BaseModel):
    version: str
    surfaces: list[str]
    event_kinds: list[str]
    signature_header: str
    signature_algorithm: str
    token_secret_bytes: int = Field(
        description="Entropy of a token or subscription "
        "secret at issue, in urlsafe-base64 source bytes"
    )
    sections: list[ExportSection]
    rules: str = Field(description="The integration discipline, stated")


INTEGRATIONS_PACK_V1 = IntegrationsPack(
    version="2026.10.1",
    surfaces=list(SURFACES),
    event_kinds=list(EVENT_KINDS),
    signature_header=SIGNATURE_HEADER,
    signature_algorithm=SIGNATURE_ALGORITHM,
    token_secret_bytes=TOKEN_SECRET_BYTES,
    sections=[
        ExportSection(
            name="official_forecasts",
            title="Official forecasts — every approved forecast's day path",
            columns=[
                "forecast_id", "commodity", "market", "forecast_as_of",
                "approved_by", "decided_on", "forecast_date",
                "p10_inr", "p50_inr", "p90_inr",
            ],
            source="forecasts whose approval stands with "
            "decided_on on or before the pack date, one row "
            "per forecast day, figures read from the "
            "forecast artefact's own days",
        ),
        ExportSection(
            name="accuracy_summary",
            title="Accuracy summary — the ledger as it stands",
            columns=[
                "record_id", "commodity", "market", "horizon_days",
                "n_results", "n_days", "mae_inr", "mape_pct",
                "bias_inr", "coverage", "degraded",
            ],
            source="every standing accuracy ledger record, "
            "figures read from the record artefact",
        ),
        ExportSection(
            name="active_events",
            title="Active events — registry events in force on the date",
            columns=[
                "event_id", "event_class", "commodity", "window_start",
                "window_end", "direction", "declared_by", "declared_on",
                "triage_state",
            ],
            source="registry events whose window covers the "
            "pack date, excluding events whose triage fold "
            "reads retired, each row carrying its triage state",
        ),
        ExportSection(
            name="buy_signals",
            title="Buy signals — the desk's standing calls",
            columns=[
                "signal_id", "commodity", "market", "forecast_id",
                "as_of", "horizon_days", "spot_inr", "p50_horizon_inr",
                "drift_pct", "band_width_pct", "value", "accuracy_state",
            ],
            source="buy signals struck on or before the pack "
            "date, figures read from the signal artefact",
        ),
    ],
    rules=(
        "a token artefact stores only the SHA-256 of its "
        "secret — the secret is shown once at issue and "
        "no read returns it; presenting a token binds "
        "the request to the token's scopes: out of scope "
        "is refused 403, an unknown or revoked secret "
        "401; presenting no token keeps the local "
        "posture; revocation is a named act and the "
        "token's state is the fold of its acts; a "
        "webhook payload is the canonical JSON of the "
        "source artefact's own read and its signature "
        "is HMAC-SHA256 over those bytes under the "
        "subscription's secret, whose value is redacted "
        "on every read; every delivery attempt is an "
        "artefact with its outcome, failures named, and "
        "a delivered (subscription, artefact) pair is "
        "never delivered twice; a board pack is struck "
        "as-of a stated date from artefacts only and "
        "stores its whole file set — CSV sections, the "
        "PDF summary and a checksum manifest — so it "
        "re-performs byte for byte; an export job's "
        "completion act names the pack it produced, and "
        "that pack is byte-identical to the synchronous "
        "build for the same as-of; a tool figure always "
        "carries the id of the artefact it was read from"
    ),
)


def load_integrations_pack(version: str | None = None) -> IntegrationsPack:
    """Load the integrations pack, fail-closed.

    An unknown version is an error, never a silent
    fallback — an artefact must name the pack it was
    struck under, and a judgement the pack it was
    judged under.
    """
    if version is None or version == INTEGRATIONS_PACK_V1.version:
        return INTEGRATIONS_PACK_V1
    raise ValueError(f"unknown integrations pack version: {version!r}")


def surface_for_path(pack: IntegrationsPack, path: str) -> str | None:
    """The surface a request path is judged under.

    None for the pack's open paths; the longest
    matching route prefix otherwise; the pack's
    default surface for anything unlisted.
    """
    if path in OPEN_PATHS:
        return None
    best: tuple[str, str] | None = None
    for prefix, surface in ROUTE_SURFACES:
        if path == prefix or path.startswith(prefix + "/"):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, surface)
    if best is not None:
        return best[1]
    return DEFAULT_SURFACE


def section_for(pack: IntegrationsPack, name: str) -> ExportSection | None:
    for section in pack.sections:
        if section.name == name:
            return section
    return None
