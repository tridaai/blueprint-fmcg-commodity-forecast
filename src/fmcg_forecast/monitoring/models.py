"""Monitoring artefacts: run records and boards.

A *run record* is one completed model-port call, priced.
It carries the profile that served the call, the purpose
from the monitoring pack's closed vocabulary, the
SHA-256 of the canonical request and response — never
their text, so the ledger can re-identify and re-price
any call without becoming a second copy of the desk's
words — the character counts the pack's estimator read,
the token figures it derived, and the cost in integer
nano-USD at the pack's reference rates. An unrated
profile's record carries cost None: never zero, because
the ledger sums costs and a zero would silently price
the call. Records are content-addressed and insert-only,
like every artefact in this repo.

A *monitoring board* is the service's state of health
struck as-of one stated instant: a usage section folding
every run record at or before that instant into per
profile x purpose rows with totals that are the exact
sum of the records folded, and a freshness section
folding the ingest registry and batch artefacts into
one row per registered source — its job totals, its
last loaded batch, and its freshness verdict under the
pack's cadence windows. Breaches and never-loaded
sources are collected on the board's face, named, never
left to be inferred from an absent row. Nothing in a
board is authored: the same store at the same as-of
always strikes the same board, which is what lets the
verifier re-perform it field for field.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


def _content_id(prefix: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return prefix + hashlib.sha256(canonical.encode()).hexdigest()[:16]


def canonical_payload(payload) -> str:
    """The canonical text a hash and a character count read.

    One stated form — sorted keys, tight separators — so
    the same call hashes and measures identically on
    every profile and in every process.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    )


def payload_hash(payload) -> str:
    return hashlib.sha256(canonical_payload(payload).encode()).hexdigest()


class RunRecord(BaseModel):
    """One completed model-port call, priced by the pack."""

    run_id: str = Field(description="Content address: RUN-<sha256[:16]>")
    called_at: datetime = Field(description="When the call completed")
    profile: str = Field(description="The model profile that served it")
    purpose: str = Field(
        description="One of the pack's closed purposes"
    )
    request_hash: str = Field(
        description="SHA-256 of the canonical request payload"
    )
    response_hash: str = Field(
        description="SHA-256 of the canonical response payload"
    )
    request_chars: int
    response_chars: int
    request_tokens: int = Field(
        description="Estimated by the pack's stated estimator"
    )
    response_tokens: int = Field(
        description="Estimated by the pack's stated estimator"
    )
    cost_nano_usd: int | None = Field(
        description="Integer nano-USD at the pack's reference "
        "rates; None for an unrated profile — never zero"
    )
    cost_basis: str = Field(
        description="reference_rate | unrated_profile"
    )
    pack_version: str


def run_content_id(record: RunRecord) -> str:
    payload = record.model_dump(mode="json", exclude={"run_id"})
    return _content_id("RUN-", payload)


class UsageRow(BaseModel):
    """One profile x purpose fold of the run ledger."""

    profile: str
    purpose: str
    n_calls: int
    request_tokens: int
    response_tokens: int
    cost_nano_usd: int | None = Field(
        description="The exact sum of the folded records' "
        "costs; None when the profile is unrated"
    )


class FreshnessRow(BaseModel):
    """One registered source's job totals and freshness verdict."""

    source_id: str
    display: str
    owner: str
    cadence: str
    state: Literal["fresh", "late", "never_loaded", "one_off"]
    max_age_hours: int | None = Field(
        description="The pack's window for this cadence; None "
        "when the cadence owes no window"
    )
    last_batch_id: str | None = Field(
        description="The most recent LOADED batch at the "
        "board's as-of; None when the source has never loaded"
    )
    last_received_at: datetime | None
    last_as_of: date | None = Field(
        description="The last loaded batch's stated as-of"
    )
    age_hours: float | None = Field(
        description="Hours from the last loaded batch's "
        "receipt to the board's as-of, 1dp; None when the "
        "source has never loaded"
    )
    n_batches: int = Field(description="Batches at or before the as-of")
    n_refused: int = Field(description="Of those, refused whole")
    rows_received: int
    rows_loaded: int
    rows_quarantined: int
    note: str = Field(description="How the row reads, stated")


class MonitoringBoard(BaseModel):
    """Cost, usage and freshness, struck as-of one instant."""

    board_id: str = Field(description="Content address: MON-<sha256[:16]>")
    struck_at: datetime = Field(
        description="The board's as-of: only records and "
        "batches at or before it are folded"
    )
    monitoring_pack_version: str
    ingest_pack_version: str = Field(
        description="The ingest pack the registry and batches "
        "were struck under, as the artefacts name it"
    )
    usage: list[UsageRow]
    total_calls: int
    total_request_tokens: int
    total_response_tokens: int
    rated_calls: int = Field(
        description="Calls priced at a reference rate"
    )
    unrated_calls: int = Field(
        description="Calls on unrated profiles — counted, "
        "never priced, never in the cost total"
    )
    total_cost_nano_usd: int = Field(
        description="The exact sum of the RATED records' "
        "costs folded into this board"
    )
    freshness: list[FreshnessRow]
    breaches: list[str] = Field(
        description="Source ids in the late state — the "
        "freshness breaches, named"
    )
    never_loaded: list[str] = Field(
        description="Source ids that have never loaded — "
        "named on every board, never absent"
    )


def board_content_id(board: MonitoringBoard) -> str:
    payload = board.model_dump(mode="json", exclude={"board_id"})
    return _content_id("MON-", payload)
