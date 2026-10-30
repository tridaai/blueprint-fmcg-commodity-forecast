"""The ingest pack — the data plane's rules, as data.

Which sources are registered, what a connector row must carry,
the value range each driver may state, and the exact vocabulary
of reasons a row can be quarantined for or a batch refused:
stated here, versioned, never buried in code. A change to any
of it is a new pack version, and every batch, quarantine record
and correction names the version it was judged under — the
verifier re-performs under exactly that pack.

The rules, as the pack states them:

- **Provenance is the price of admission.** A batch arrives
  under a registered source with a stated as-of date; an API
  row must additionally carry its own source and as-of, equal
  to the batch's. A row without provenance is refused at the
  port, never loaded and argued about later.
- **Units are a batch contract.** Every row states its unit;
  the registry states the unit each source uses per driver.
  One mismatched unit refuses the whole batch — a file in the
  wrong unit is never partially loaded at the wrong scale.
- **Bad rows quarantine, they do not vanish and they do not
  land.** Each quarantined row names every reason that applies,
  from the pack's vocabulary. Zero quarantined rows reach an
  engine input: engines read the observations table, and a
  quarantined row is never written to it.
- **History is never edited.** A wrong landed figure is
  corrected by a new artefact that supersedes by link; the
  stored observation keeps the value it landed with, and the
  effective value is the fold of the correction chain.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from fmcg_forecast.models import DRIVER_UNITS

CONNECTOR_KINDS: tuple[str, ...] = ("file_drop", "scheduled_pull", "api_push")

# The per-row quarantine vocabulary, in the order reasons are
# collected on a record. A row may carry several; a fixture row
# in the gate trips exactly the ones it was planted to trip.
QUARANTINE_REASONS: tuple[str, ...] = (
    "malformed_row",
    "missing_provenance",
    "unknown_commodity",
    "unknown_market",
    "driver_not_reported",
    "driver_not_covered",
    "future_date",
    "value_out_of_range",
    "duplicate_conflicting",
    "conflicts_with_landed",
)

# The whole-batch refusal vocabulary: these are not row faults,
# they are contract faults, and no row of the batch lands.
BATCH_REFUSAL_REASONS: tuple[str, ...] = (
    "unknown_source",
    "batch_missing_provenance",
    "unit_mismatch",
    "empty_batch",
)


class ValueRule(BaseModel):
    """One driver's admissible range, stated."""

    driver: str
    min_value: float
    min_exclusive: bool = Field(
        description="True when the minimum itself is inadmissible "
        "(a price of zero is not a price)"
    )
    max_value: float


class BuiltinSource(BaseModel):
    """A source the pack itself registers, before any desk act."""

    source_id: str
    kind: str = Field(description="file_drop | scheduled_pull | api_push")
    display: str
    owner: str = Field(description="The named desk that owns the feed")
    cadence: str
    drivers: list[str]
    licence_note: str


class IngestPack(BaseModel):
    version: str
    value_rules: list[ValueRule]
    quarantine_reasons: list[str]
    batch_refusal_reasons: list[str]
    builtin_sources: list[BuiltinSource]
    rules: str = Field(description="The data-plane rules, stated")


def _units_for(drivers: list[str]) -> dict[str, str]:
    return {d: DRIVER_UNITS[d] for d in drivers}


_ALL = ["modal_price", "arrivals", "stock_level", "import_flow", "export_flow", "weather_index"]

INGEST_PACK_V1 = IngestPack(
    version="2026.10.1",
    value_rules=[
        ValueRule(driver="modal_price", min_value=0.0, min_exclusive=True, max_value=1_000_000.0),
        ValueRule(driver="arrivals", min_value=0.0, min_exclusive=False, max_value=500_000.0),
        ValueRule(driver="stock_level", min_value=0.0, min_exclusive=False, max_value=160.0),
        ValueRule(driver="import_flow", min_value=0.0, min_exclusive=False, max_value=500_000.0),
        ValueRule(driver="export_flow", min_value=0.0, min_exclusive=False, max_value=500_000.0),
        ValueRule(driver="weather_index", min_value=-1.0, min_exclusive=False, max_value=1.0),
    ],
    quarantine_reasons=list(QUARANTINE_REASONS),
    batch_refusal_reasons=list(BATCH_REFUSAL_REASONS),
    builtin_sources=[
        BuiltinSource(
            source_id="agmarknet_file_drop",
            kind="file_drop",
            display="Agmarknet daily mandi file drop",
            owner="market data desk",
            cadence="daily",
            drivers=list(_ALL),
            licence_note="GODL-India open data terms (data.gov.in)",
        ),
        BuiltinSource(
            source_id="exchange_bhavcopy_drop",
            kind="file_drop",
            display="Exchange daily bhavcopy file drop",
            owner="market data desk",
            cadence="daily",
            drivers=["modal_price"],
            licence_note="Exchange public bhavcopy, internal use",
        ),
        BuiltinSource(
            source_id="trade_flow_file_drop",
            kind="file_drop",
            display="Trade flow file drop (imports / exports)",
            owner="trade desk",
            cadence="weekly",
            drivers=["import_flow", "export_flow"],
            licence_note="Compiled from published trade statistics",
        ),
        BuiltinSource(
            source_id="weather_service_pull",
            kind="scheduled_pull",
            display="Weather service scheduled pull",
            owner="market data desk",
            cadence="daily",
            drivers=["weather_index"],
            licence_note="Weather provider licence, derived index only",
        ),
        BuiltinSource(
            source_id="mandi_api_push",
            kind="api_push",
            display="Partner mandi API push",
            owner="partner feed desk",
            cadence="hourly",
            drivers=["modal_price", "arrivals"],
            licence_note="Partner feed agreement, Verdanta internal use",
        ),
        BuiltinSource(
            source_id="verdanta_generated_history",
            kind="file_drop",
            display="Generated history bootstrap (the in-repo dataset)",
            owner="verdanta data desk",
            cadence="once",
            drivers=list(_ALL),
            licence_note="Generated in-repo for this blueprint; graded "
            "against its manifest, never presented as market data",
        ),
    ],
    rules=(
        "provenance is the price of admission (a batch under a "
        "registered source with a stated as-of; API rows carry "
        "their own source and as-of, equal to the batch's); "
        "units are a batch contract (one mismatch refuses the "
        "whole batch); bad rows quarantine with named reasons "
        "and never reach an engine input; a landed key is never "
        "overwritten — a conflict quarantines, a correction "
        "supersedes by link; replaying a batch lands nothing twice"
    ),
)


def builtin_registration(source: BuiltinSource, pack: IngestPack):
    """The registry view of a pack built-in: pack-stamped, unstored."""
    from fmcg_forecast.ingest.models import SourceRegistration

    return SourceRegistration(
        source_id=source.source_id,
        kind=source.kind,
        display=source.display,
        owner=source.owner,
        cadence=source.cadence,
        drivers=list(source.drivers),
        units=_units_for(list(source.drivers)),
        licence_note=source.licence_note,
        registered_by="ingest_pack",
        registered_at=None,
        pack_version=pack.version,
    )


def load_ingest_pack(version: str | None = None) -> IngestPack:
    """Load the ingest pack, fail-closed.

    An unknown version is an error, never a silent fallback —
    a batch judged under one pack must never be quietly
    re-read under another.
    """
    if version is None or version == INGEST_PACK_V1.version:
        return INGEST_PACK_V1
    raise ValueError(f"unknown ingest pack version: {version!r}")
