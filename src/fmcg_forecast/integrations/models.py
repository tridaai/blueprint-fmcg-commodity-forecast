"""Integration artefacts: tokens, subscriptions,
deliveries, board packs and export jobs.

A *token* is an integration's standing permission. It
carries the SHA-256 of its secret — never the secret,
which is shown once at issue and exists afterwards
only in the integration's own hands — the closed set
of surfaces it may read, and the named person who
issued it. Its state is not a field: it is the fold of
its *token acts*, of which revocation is the one act
this round strikes. A token with a revocation act is
dead; the act names who revoked it and why.

A *webhook subscription* is a standing instruction:
deliver these event kinds to this endpoint. Its shared
secret stands on the artefact because deliveries must
be signed and re-performed — and it is redacted on
every read surface, which show only that a secret is
set and the prefix of its hash. A *delivery* is one
attempt: the payload (the canonical JSON of the source
artefact's own read), the payload's hash, the
signature the secret produced over it, and the
outcome — delivered with its HTTP status, or failed
with its error named. Attempts are insert-only; a
(subscription, artefact) pair reads delivered when any
of its attempts delivered, and dispatch never strikes
a second delivered attempt for a pair already served.

A *board pack* is the DR2 file set struck as-of a
date: one CSV per section the pack states, a
print-ready PDF summary, and the checksum manifest.
The artefact stores every file's bytes (base64) beside
its hash and size, so the set can be re-performed
exactly and a tampered file named by its own hash. An
*export job* is a request for that build, and its
*job acts* are its lifecycle: a completion act naming
the pack produced, or a failure act naming the error.
The job's state is the fold of its acts — requested,
complete, failed — never a stored field.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


def _content_id(prefix: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return prefix + hashlib.sha256(canonical.encode()).hexdigest()[:16]


def canonical_payload(payload) -> str:
    """The canonical text a payload hash reads.

    One stated form — sorted keys, tight separators —
    so the same artefact reads byte-identically in
    every process: this is the exact text a webhook
    delivers and a signature signs.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    )


def payload_hash(payload) -> str:
    return hashlib.sha256(canonical_payload(payload).encode()).hexdigest()


def hash_secret(secret: str) -> str:
    """The only form of a token secret the store keeps."""
    return hashlib.sha256(secret.encode()).hexdigest()


def sign_payload(secret: str, payload_text: str) -> str:
    """HMAC-SHA256 over the payload bytes, hex — the
    signature a receiver re-derives from the secret and
    the bytes alone."""
    return hmac.new(
        secret.encode(), payload_text.encode(), hashlib.sha256
    ).hexdigest()


class IntegrationToken(BaseModel):
    """One integration's standing permission."""

    token_id: str = Field(description="Content address: TOK-<sha256[:16]>")
    name: str = Field(description="The integration's name, as issued")
    scopes: list[str] = Field(
        description="Surfaces from the pack's closed "
        "vocabulary this token may read"
    )
    secret_hash: str = Field(
        description="SHA-256 of the secret — the secret "
        "itself is never stored and shown only at issue"
    )
    issued_by: str = Field(description="The named person who issued it")
    issued_at: datetime
    pack_version: str


def token_content_id(token: IntegrationToken) -> str:
    payload = token.model_dump(mode="json", exclude={"token_id"})
    return _content_id("TOK-", payload)


class TokenAct(BaseModel):
    """One act on a token: revocation, the state-changing act."""

    act_id: str = Field(description="Content address: TOKA-<sha256[:16]>")
    token_id: str
    act: Literal["revoke"] = Field(
        description="revoke kills the token's secret from "
        "this act on"
    )
    actor: str = Field(description="The named person who acted")
    acted_at: datetime
    reason: str = Field(description="Why, stated by the actor")
    pack_version: str


def token_act_content_id(act: TokenAct) -> str:
    payload = act.model_dump(mode="json", exclude={"act_id"})
    return _content_id("TOKA-", payload)


class WebhookSubscription(BaseModel):
    """A standing delivery instruction."""

    subscription_id: str = Field(
        description="Content address: WHS-<sha256[:16]>"
    )
    name: str = Field(description="The subscriber's name, as struck")
    endpoint_url: str = Field(description="Where deliveries are posted")
    event_kinds: list[str] = Field(
        description="Event kinds from the pack's closed vocabulary"
    )
    secret: str = Field(
        description="The shared HMAC secret — server-side "
        "configuration on the artefact, redacted on every "
        "read (reads show its hash prefix only)"
    )
    created_by: str = Field(description="The named person who struck it")
    created_at: datetime
    pack_version: str


def subscription_content_id(subscription: WebhookSubscription) -> str:
    payload = subscription.model_dump(mode="json", exclude={"subscription_id"})
    return _content_id("WHS-", payload)


class WebhookDelivery(BaseModel):
    """One delivery attempt of one artefact to one subscription."""

    delivery_id: str = Field(
        description="Content address: WHD-<sha256[:16]>"
    )
    subscription_id: str
    event_kind: str = Field(description="One of the pack's event kinds")
    source_artefact_id: str = Field(
        description="The artefact delivered: an alert, an "
        "approval or a triage act"
    )
    attempt: int = Field(
        description="This attempt's ordinal among the "
        "pair's attempts, from one — a retried pair's "
        "attempts are distinct artefacts"
    )
    payload: str = Field(
        description="The canonical JSON of the source "
        "artefact's own read — the exact bytes posted"
    )
    payload_sha256: str = Field(description="SHA-256 of the payload")
    signature: str = Field(
        description="HMAC-SHA256 over the payload under the "
        "subscription's secret, hex"
    )
    attempted_at: datetime
    outcome: Literal["delivered", "failed"]
    http_status: int | None = Field(
        description="The endpoint's HTTP status when it "
        "answered; None when no answer arrived"
    )
    error: str | None = Field(
        description="Why the attempt failed, named; None "
        "when it delivered"
    )
    pack_version: str


def delivery_content_id(delivery: WebhookDelivery) -> str:
    """The attempt's address: over who was served, what,
    which bytes and when — the identity the delivery
    header carries before the attempt is made. The
    outcome fields (outcome, http_status, error) are
    the attempt's result and stand outside the address,
    so the id a receiver sees is the id on the record;
    the verifier re-derives the signature and payload
    hash to grade the result itself."""
    payload = delivery.model_dump(
        mode="json",
        exclude={"delivery_id", "outcome", "http_status", "error"},
    )
    return _content_id("WHD-", payload)


class PackFile(BaseModel):
    """One file of a board pack, bytes carried on the artefact."""

    name: str = Field(description="The file name in the set")
    media_type: str
    sha256: str = Field(description="SHA-256 of the file's bytes")
    size_bytes: int
    content_b64: str = Field(
        description="The file's bytes, base64 — the pack "
        "stores its whole set so it re-performs exactly"
    )


class BoardPack(BaseModel):
    """The DR2 board-pack export, struck as-of a date."""

    pack_id: str = Field(description="Content address: BPK-<sha256[:16]>")
    as_of: date = Field(description="The date the pack is struck for")
    struck_at: datetime = Field(description="When the build ran")
    sections: list[str] = Field(
        description="The section names folded, in pack order"
    )
    section_rows: dict[str, int] = Field(
        description="Rows folded per section — a section "
        "with no rows is named here with zero, never absent"
    )
    files: list[PackFile] = Field(
        description="The whole file set: the section CSVs, "
        "pack.pdf and manifest.json"
    )
    integrations_pack_version: str


def board_pack_content_id(pack: BoardPack) -> str:
    """The pack's address: over the pack's as-of, its
    sections and the files the manifest indexes.
    Two things stand outside the address, both stated:
    struck_at, so the same store built for the same
    as-of always strikes the same pack — that is what
    makes a job's output byte-identical to the
    synchronous build (the dashboard view's address
    excludes its saved_on for the same reason) — and
    manifest.json, which names the address it cannot
    itself be inside and is checked against the
    addressed files by the verifier instead."""
    payload = pack.model_dump(
        mode="json", exclude={"pack_id", "struck_at"}
    )
    payload["files"] = [
        f for f in payload["files"] if f["name"] != "manifest.json"
    ]
    return _content_id("BPK-", payload)


class ExportJob(BaseModel):
    """A request for a board pack, collected later."""

    job_id: str = Field(description="Content address: JOB-<sha256[:16]>")
    requested_by: str = Field(description="The named person who asked")
    requested_at: datetime
    as_of: date = Field(description="The pack date the job asks for")
    pack_version: str


def job_content_id(job: ExportJob) -> str:
    # The address excludes the request instant, on
    # purpose: a job IS its request — the same person
    # asking for the same as-of is the same job, struck
    # once and returned on repeat asks, not a queue of
    # duplicates. requested_at stays on the artefact as
    # the first ask's record.
    payload = job.model_dump(
        mode="json", exclude={"job_id", "requested_at"}
    )
    return _content_id("JOB-", payload)


class ExportJobAct(BaseModel):
    """One lifecycle act on an export job."""

    act_id: str = Field(description="Content address: JOBA-<sha256[:16]>")
    job_id: str
    act: Literal["complete", "fail"] = Field(
        description="complete names the pack produced; "
        "fail names the error the build raised"
    )
    acted_at: datetime
    board_pack_id: str | None = Field(
        description="Complete only: the pack the run produced"
    )
    error: str | None = Field(
        description="Fail only: why the build failed, named"
    )
    pack_version: str


def job_act_content_id(act: ExportJobAct) -> str:
    payload = act.model_dump(mode="json", exclude={"act_id"})
    return _content_id("JOBA-", payload)


def job_state(job: ExportJob, acts: list[ExportJobAct]) -> str:
    """The job's state: the fold of its acts, never a field."""
    state = "requested"
    for act in sorted(acts, key=lambda a: (a.acted_at, a.act_id)):
        state = "complete" if act.act == "complete" else "failed"
    return state
