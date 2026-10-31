"""The access artefacts: principal grants, read entries,
and the audit log.

A grant is a chain of acts over one folded name: each
act confers a role and a market scope, or confers
nothing (a repeal), and the standing grant is the
chain's head — a fold, never a stored column. An access
entry is one governed read, recorded before the answer
was given, carrying the grant it was judged under so
the verifier can re-judge the outcome against an
immutable artefact rather than a moving fold. The audit
log is a struck snapshot of the entries, folded in
strike order and numbered from 1 with no gaps — the
decision log's discipline, applied to reads.

Grants and entries carry a strike sequence assigned by
the service at strike time (the count of their kind on
record, plus one): it orders same-date acts and makes
two identical reads two entries, never one. The
sequence rides inside the content address, so a forged
insert that reuses a number collides with the record
it claims to extend and is named by the verifier's
gaplessness check.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from pydantic import BaseModel, Field


class PrincipalGrant(BaseModel):
    """One act over a name: a role and scope conferred,
    or a repeal (F20-AS1)."""

    grant_id: str = Field(
        description="Content address: GRT-<sha256[:16]>"
    )
    seq: int = Field(
        description="Strike order among grant acts, "
        "1-based and gapless"
    )
    subject: str = Field(description="The named principal")
    role: str | None = Field(
        description="The role conferred; None repeals — "
        "the name stands ungranted from this act"
    )
    markets: list[str] | None = Field(
        description="The markets the grant scopes the "
        "principal to; None covers all markets. A repeal "
        "carries None and scopes nothing"
    )
    granted_by: str = Field(description="The named granter")
    granted_on: date
    supersedes_grant_id: str | None = Field(
        description="The previous act over this folded "
        "name; None for the name's first act"
    )
    bootstrap: bool = Field(
        default=False,
        description="True only for the book's first act, "
        "struck by its own subject as desk head because "
        "an empty book has no one else to strike it",
    )
    pack_version: str = Field(
        description="The access pack the act was judged "
        "under, on its face"
    )


class AccessEntry(BaseModel):
    """One governed read, recorded before its answer."""

    entry_id: str = Field(
        description="Content address: ACC-<sha256[:16]>"
    )
    seq: int = Field(
        description="Strike order among entries, 1-based "
        "and gapless — the audit log's numbering"
    )
    principal: str = Field(
        description="The name the read was made under, "
        "as presented"
    )
    grant_id: str | None = Field(
        description="The standing grant the read was "
        "judged under; None when the name stood ungranted"
    )
    role: str | None = Field(
        description="The role on that grant; None when "
        "ungranted"
    )
    surface: str = Field(
        description="The governed surface read: forecast, "
        "dashboard or export"
    )
    target_kind: str = Field(
        description="The artefact kind read: forecast or "
        "dashboard_assembly"
    )
    target_id: str
    markets: list[str] = Field(
        description="The markets the artefact spans, as "
        "judged — the scope the outcome was decided on"
    )
    outcome: str = Field(
        description="allowed, or the hidden_* reason the "
        "read was refused — recorded here, never in the "
        "answer the reader got"
    )
    read_on: date = Field(
        description="The as-of the read was performed "
        "under — the artefact's own as-of"
    )
    pack_version: str


class AccessLogEntry(BaseModel):
    """One entry's line in the audit log."""

    seq: int = Field(description="1-based, gapless across the log")
    entry_id: str
    principal: str
    role: str | None
    surface: str
    target_kind: str
    target_id: str
    outcome: str
    read_on: date


class AccessLog(BaseModel):
    """The audit trail, folded into one artefact."""

    log_id: str = Field(description="Content address: ALOG-<sha256[:16]>")
    struck_on: date = Field(
        description="The log's as-of: every entry struck "
        "on or before the fold is in it, numbered in "
        "strike order"
    )
    upto_seq: int = Field(
        description="The last entry sequence folded in; "
        "0 for an empty log"
    )
    entries: list[AccessLogEntry]
    fold_rule: str = Field(
        description="How the entries were folded, stated"
    )


def _content_id(prefix: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return prefix + hashlib.sha256(canonical.encode()).hexdigest()[:16]


def grant_content_id(grant: PrincipalGrant) -> str:
    return _content_id(
        "GRT-", grant.model_dump(mode="json", exclude={"grant_id"})
    )


def entry_content_id(entry: AccessEntry) -> str:
    return _content_id(
        "ACC-", entry.model_dump(mode="json", exclude={"entry_id"})
    )


def access_log_content_id(log: AccessLog) -> str:
    return _content_id(
        "ALOG-", log.model_dump(mode="json", exclude={"log_id"})
    )
