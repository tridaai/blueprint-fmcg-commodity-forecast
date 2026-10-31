"""The desk artefacts: policy versions, chain decisions
and their acts, the decision log, comments and tasks.

A policy version is a proposal that may come to govern:
its pack payload and its diff against the version it
would supersede are content-addressed and insert-only;
only its lifecycle status moves, and only in the store's
status column, flipped when its pack-change chain
completes — the forecast status precedent (draft ->
official) applied to the desk's own rules.

A decision is a governance case over one artefact of
record. It is content-addressed over everything pinned
at open time — the pack version, the resolved chain, the
facts the chain was judged from — and its state is a
fold over its acts, derived at read, never stored. An
act is a named person's word on one step: who, in what
role, approve or reject, on what date.

The decision log is a struck snapshot of that fold over
the whole record. A comment pins to one artefact by its
content address. A follow-up task pins the same way and
carries its own open/close acts; its state is a fold
too, and its read flags a target the record has since
superseded.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from fmcg_forecast.desk.pack import ChainStep, DeskPolicyPack

# The artefact kinds a comment or task may pin to. Each
# resolves through a store getter, so an annotation over
# an artefact that does not exist cannot be struck.
ANNOTATION_TARGET_KINDS: tuple[str, ...] = (
    "forecast",
    "scenario",
    "market_event",
    "alert",
    "buy_signal",
    "dashboard_view",
    "coverage_assessment",
    "basis_reading",
    "landed_comparison",
    "market_map",
)


class PackDiffEntry(BaseModel):
    """One top-level pack field a proposal changes."""

    field: str
    before: Any = Field(
        description="The standing pack's value, as JSON; "
        "None when the field is absent there"
    )
    after: Any = Field(
        description="The proposed pack's value, as JSON; "
        "None when the field is absent there"
    )


class PolicyVersion(BaseModel):
    """One proposed desk policy pack version (F20-AD2)."""

    version_id: str = Field(
        description="Content address: POL-<sha256[:16]>"
    )
    label: str = Field(
        description="The pack version label — the proposed "
        "pack's own version string"
    )
    supersedes_version_id: str | None = Field(
        description="The stored version standing when this "
        "was proposed; None when the genesis pack in code "
        "was standing"
    )
    supersedes_label: str = Field(
        description="The standing pack's label at proposal "
        "time — the version this proposal's diff is "
        "computed against"
    )
    pack: DeskPolicyPack = Field(
        description="The proposed pack, whole — a version "
        "is a complete pack, never a patch"
    )
    diff: list[PackDiffEntry] = Field(
        description="The field-by-field diff against the "
        "superseded pack, computed at proposal time and "
        "re-performed by the verifier"
    )
    proposed_by: str = Field(description="The named proposer")
    proposed_on: date
    status: Literal["proposed", "standing", "superseded"] = Field(
        default="proposed",
        description="Lifecycle, carried in the store's "
        "status column and synced onto the artefact at "
        "read — excluded from the content address, the "
        "way a forecast's status is",
    )


class ResolutionFact(BaseModel):
    """One fact a chain's conditional steps were judged
    from, pinned on the decision's face."""

    name: str
    value: str = Field(
        description="The fact as read off the target "
        "artefact, rendered exactly"
    )
    rule: str = Field(
        description="The pack condition that consumed it"
    )


class DecisionCase(BaseModel):
    """One approval-chain case over an artefact of record
    (F20-CA2)."""

    decision_id: str = Field(
        description="Content address: DEC-<sha256[:16]>"
    )
    kind: str = Field(description="The decision kind the pack names")
    target_kind: str = Field(
        description="The artefact kind the pack assigns this kind"
    )
    target_id: str = Field(description="The artefact governed")
    opened_by: str = Field(description="The named opener — the requester")
    opened_on: date
    purpose: str = Field(
        description="Why the desk is being asked, in the opener's words"
    )
    pack_version: str = Field(
        description="The standing pack's label at open "
        "time — the version this decision runs under, on "
        "its face"
    )
    pack_source_id: str | None = Field(
        description="The stored policy version the pack "
        "was read from; None when the genesis pack in "
        "code was standing"
    )
    steps: list[ChainStep] = Field(
        description="The chain as resolved for this "
        "target at open time — conditional steps kept or "
        "dropped by the target's own facts, pinned here"
    )
    resolution: list[ResolutionFact] = Field(
        description="The facts the resolution was judged from"
    )
    scope_note: str


class DecisionAct(BaseModel):
    """One named person's word on one step of a decision."""

    act_id: str = Field(description="Content address: DACT-<sha256[:16]>")
    decision_id: str
    step: str = Field(description="The chain step this act strikes")
    actor: str = Field(description="The named actor")
    role: str = Field(description="The role the actor struck it in")
    outcome: Literal["approve", "reject"]
    decided_on: date
    note: str = ""


class DecisionLogEntry(BaseModel):
    """One act's line in the decision log."""

    seq: int = Field(description="1-based, gapless across the log")
    act_id: str
    decision_id: str
    kind: str
    target_kind: str
    target_id: str
    step: str
    actor: str
    role: str
    outcome: str
    decided_on: date


class DecisionLog(BaseModel):
    """The whole decision record, folded into one export
    (F20-CA2)."""

    log_id: str = Field(description="Content address: DLOG-<sha256[:16]>")
    struck_on: date = Field(
        description="The log's as-of: every act decided on "
        "or before this date is in it, and no other"
    )
    entries: list[DecisionLogEntry]
    fold_rule: str = Field(
        description="How the entries were folded, stated"
    )


class ArtefactComment(BaseModel):
    """One named comment pinned to one artefact version
    (F20-CA1)."""

    comment_id: str = Field(
        description="Content address: CMT-<sha256[:16]>"
    )
    target_kind: str
    target_id: str = Field(
        description="The exact artefact the comment was "
        "written against — it renders there or nowhere"
    )
    author: str = Field(description="The named author")
    body: str
    commented_on: date


class FollowUpTask(BaseModel):
    """One follow-up task pinned to one artefact version
    (F20-CA1)."""

    task_id: str = Field(description="Content address: TSK-<sha256[:16]>")
    target_kind: str
    target_id: str
    title: str
    opened_by: str = Field(description="The named opener")
    assignee: str = Field(description="The named person who owns it")
    opened_on: date


class TaskAct(BaseModel):
    """One act on a task: closing it, or reopening it."""

    act_id: str = Field(description="Content address: TACT-<sha256[:16]>")
    task_id: str
    action: Literal["close", "reopen"]
    actor: str = Field(description="The named actor")
    acted_on: date
    note: str = ""


def _content_id(prefix: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return prefix + hashlib.sha256(canonical.encode()).hexdigest()[:16]


def policy_version_content_id(version: PolicyVersion) -> str:
    return _content_id(
        "POL-",
        version.model_dump(
            mode="json", exclude={"version_id", "status"}
        ),
    )


def decision_content_id(decision: DecisionCase) -> str:
    return _content_id(
        "DEC-", decision.model_dump(mode="json", exclude={"decision_id"})
    )


def decision_act_content_id(act: DecisionAct) -> str:
    return _content_id(
        "DACT-", act.model_dump(mode="json", exclude={"act_id"})
    )


def decision_log_content_id(log: DecisionLog) -> str:
    return _content_id(
        "DLOG-", log.model_dump(mode="json", exclude={"log_id"})
    )


def comment_content_id(comment: ArtefactComment) -> str:
    return _content_id(
        "CMT-", comment.model_dump(mode="json", exclude={"comment_id"})
    )


def task_content_id(task: FollowUpTask) -> str:
    return _content_id(
        "TSK-", task.model_dump(mode="json", exclude={"task_id"})
    )


def task_act_content_id(act: TaskAct) -> str:
    return _content_id(
        "TACT-", act.model_dump(mode="json", exclude={"act_id"})
    )
