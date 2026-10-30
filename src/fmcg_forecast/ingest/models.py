"""Data-plane artefacts: sources, batches, rows, quarantine,
provenance, corrections and backfill replays.

A *source registration* states who may feed the store: the
source's id, its connector kind, the named desk that owns it,
its cadence, the drivers it carries with their units, and its
licence note. The pack registers six built-ins; a desk may
register more by a named act. A registration is an artefact,
never a config edit.

A *candidate row* is one row as a connector delivered it —
the raw text of every field kept, so validation verdicts can
be re-performed from the stored row alone, years later, under
the pack version that judged it.

An *ingest batch* is the delivery as a whole: content-addressed
over its source and its exact candidate set, so re-delivering
the same file lands on the same artefact and loads nothing
twice. A batch is ``loaded`` (its clean rows landed, its bad
rows quarantined) or ``refused`` whole, with the refusal named
on its face — a refusal is a recorded outcome, never an
exception swallowed by a log.

A *quarantine record* pins one candidate row and every reason
it failed. It lives outside the observations table by
construction: engines read observations, and a quarantined
row is never written there.

A *provenance row* binds one landed observation to the source
and batch row that delivered it — every connector-landed fact
carries its source id on a row of its own.

A *correction* is the only way a landed figure changes: an
insert-only artefact naming the target fact's natural key, the
corrected value, a stated reason and a named corrector,
superseding the previous correction for that key by link. The
stored observation is never rewritten; the *effective fact*
is the fold — the landed value, then each correction in
chain order.

A *backfill replay* records a backtest replay over backfilled
origins: the results it stored, the origins it skipped with
the engine's refusal named, and the ledger records the series
earned — re-performable from the stored results alone.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from pydantic import BaseModel, Field


def _content_id(prefix: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return prefix + hashlib.sha256(canonical.encode()).hexdigest()[:16]


class SourceRegistration(BaseModel):
    source_id: str
    kind: str = Field(description="file_drop | scheduled_pull | api_push")
    display: str
    owner: str = Field(description="The named desk that owns the feed")
    cadence: str
    drivers: list[str]
    units: dict[str, str] = Field(
        description="The unit this source states per driver — "
        "the batch contract rows are judged against"
    )
    licence_note: str
    registered_by: str = Field(
        description="The named person who registered the source, "
        "or 'ingest_pack' for a pack built-in"
    )
    registered_at: datetime | None = Field(
        description="When the registration act landed; None for "
        "a pack built-in, which the pack itself states"
    )
    pack_version: str


def registration_content_id(registration: SourceRegistration) -> str:
    payload = registration.model_dump(mode="json")
    return _content_id("SRC-", payload)


class CandidateRow(BaseModel):
    """One delivered row, raw text kept for re-performance."""

    row_index: int
    commodity: str = ""
    market: str = ""
    obs_date_text: str = ""
    driver: str = ""
    value_text: str = ""
    unit: str = ""
    source_text: str = Field(
        default="",
        description="The row's own source claim (API rows); "
        "empty for file rows, whose provenance is the batch's",
    )
    as_of_text: str = Field(
        default="",
        description="The row's own as-of claim (API rows); empty "
        "for file rows, whose provenance is the batch's",
    )

    def parsed_date(self) -> date | None:
        try:
            return date.fromisoformat(self.obs_date_text.strip())
        except (ValueError, AttributeError):
            return None

    def parsed_value(self) -> float | None:
        try:
            return float(self.value_text.strip())
        except (ValueError, AttributeError):
            return None


def natural_key(row: CandidateRow) -> tuple | None:
    """The row's fact key, when its fields are legible enough
    to name one: (commodity, market, obs_date, driver)."""
    parsed = row.parsed_date()
    if (
        parsed is None
        or not row.commodity.strip()
        or not row.market.strip()
        or not row.driver.strip()
    ):
        return None
    return (row.commodity.strip(), row.market.strip(), parsed, row.driver.strip())


def candidates_digest(rows: list[CandidateRow]) -> str:
    canonical = json.dumps(
        [r.model_dump(mode="json") for r in rows],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class IngestBatch(BaseModel):
    batch_id: str = Field(description="Content address: BCH-<sha256[:16]>")
    source_id: str
    connector_kind: str
    received_by: str = Field(description="The named person who ran the load")
    received_at: datetime
    as_of: date | None = Field(
        description="The batch's stated as-of; None only on a "
        "batch refused for missing provenance"
    )
    pack_version: str
    status: str = Field(description="loaded | refused")
    refusal_reason: str = Field(
        description="The batch refusal reason; empty when loaded"
    )
    rows_received: int
    rows_loaded: int
    rows_quarantined: int
    rows_duplicate: int
    content_digest: str = Field(
        description="SHA-256 over the canonical candidate set — "
        "the verifier recomputes it from the stored rows"
    )


def batch_content_id(
    source_id: str,
    connector_kind: str,
    as_of: date | None,
    digest: str,
    pack_version: str,
) -> str:
    payload = {
        "source_id": source_id,
        "connector_kind": connector_kind,
        "as_of": as_of.isoformat() if as_of else None,
        "content_digest": digest,
        "pack_version": pack_version,
    }
    return _content_id("BCH-", payload)


class QuarantineRecord(BaseModel):
    quarantine_id: str = Field(description="Content address: QRN-<sha256[:16]>")
    batch_id: str
    row_index: int
    reasons: list[str] = Field(
        description="Every pack reason that applies, in pack order"
    )
    candidate: CandidateRow = Field(
        description="The row as delivered — the snapshot the "
        "verifier re-judges under the batch's pack"
    )
    pack_version: str


def quarantine_content_id(record: QuarantineRecord) -> str:
    payload = record.model_dump(mode="json", exclude={"quarantine_id"})
    return _content_id("QRN-", payload)


class ProvenanceRow(BaseModel):
    """One landed observation's delivery lineage."""

    commodity: str
    market: str
    obs_date: date
    driver: str
    source_id: str
    batch_id: str
    row_index: int


class Correction(BaseModel):
    correction_id: str = Field(description="Content address: COR-<sha256[:16]>")
    commodity: str
    market: str
    obs_date: date
    driver: str
    corrected_value: float
    reason: str = Field(description="Why the figure was wrong, stated")
    corrected_by: str = Field(description="The named corrector")
    corrected_by_role: str
    corrected_at: datetime
    supersedes_correction_id: str | None = Field(
        description="The previous correction for this key, by "
        "link; None on the chain's first correction"
    )
    corrects_quarantine_id: str | None = Field(
        description="The quarantine record this correction "
        "answers, when the wrong figure never landed; None when "
        "it corrects a landed fact"
    )
    pack_version: str


def correction_content_id(correction: Correction) -> str:
    payload = correction.model_dump(mode="json", exclude={"correction_id"})
    return _content_id("COR-", payload)


class BackfillReplay(BaseModel):
    replay_id: str = Field(description="Content address: RPL-<sha256[:16]>")
    commodity: str
    market: str
    origins: list[date] = Field(description="The origins replayed, ascending")
    accuracy_pack_version: str
    results_stored: int
    results_already_on_record: int
    skipped: list[dict] = Field(
        description="Origins the engine refused, with the refusal named"
    )
    result_ids: list[str]
    ledger_record_ids: list[str] = Field(
        description="The accuracy records the replay's rebuild "
        "left standing for the series"
    )
    replayed_by: str = Field(description="The named person who ran the replay")
    replayed_at: datetime


def replay_content_id(replay: BackfillReplay) -> str:
    payload = replay.model_dump(mode="json", exclude={"replay_id"})
    return _content_id("RPL-", payload)
