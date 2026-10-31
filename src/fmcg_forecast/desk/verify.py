"""Re-performance for the desk layer.

Nothing here trusts a stored figure: a policy version's
diff is recomputed against the pack it supersedes, a
decision's chain is re-resolved from its target's face
under its pinned pack, every act is re-judged against
the chain rule that governed it, the decision log is
re-folded from the acts, and an annotation's target must
still be on record. A version reads standing only with
a completed pack-change chain behind it — standing
without its chain is itself a problem, named.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fmcg_forecast.desk.engine import (
    DeskError,
    _folded_name,
    annotation_target,
    build_decision_log,
    diff_packs,
    fold_decision,
    resolve_chain,
    target_for_decision,
)
from fmcg_forecast.desk.models import (
    ArtefactComment,
    DecisionAct,
    DecisionCase,
    DecisionLog,
    FollowUpTask,
    PolicyVersion,
    comment_content_id,
    decision_act_content_id,
    decision_content_id,
    decision_log_content_id,
    policy_version_content_id,
    task_act_content_id,
    task_content_id,
)
from fmcg_forecast.desk.pack import DeskPolicyPack, load_desk_pack

if TYPE_CHECKING:
    from fmcg_forecast.store import Store


def pack_by_label(
    store: "Store", label: str, genesis: DeskPolicyPack
) -> DeskPolicyPack | None:
    """The pack a label names: the genesis pack, or a
    stored version's pack. Insert-only record, so a
    label that once resolved always resolves."""
    if label == genesis.version:
        return genesis
    for version in store.list_policy_versions():
        if version.label == label:
            return version.pack
    return None


def verify_policy_version(
    store: "Store", version: PolicyVersion,
    genesis: DeskPolicyPack | None = None,
) -> list[str]:
    genesis = genesis or load_desk_pack()
    problems: list[str] = []
    if policy_version_content_id(version) != version.version_id:
        problems.append(
            f"policy version {version.version_id}: content "
            "address does not recompute"
        )
    if version.pack.version != version.label:
        problems.append(
            f"policy version {version.version_id}: label "
            f"{version.label!r} does not match its pack's "
            f"version {version.pack.version!r}"
        )
    if version.supersedes_version_id is None:
        base = genesis
    else:
        superseded = store.get_policy_version(
            version.supersedes_version_id
        )
        base = superseded.pack if superseded is not None else None
        if superseded is None:
            problems.append(
                f"policy version {version.version_id}: "
                f"supersedes {version.supersedes_version_id}, "
                "which is not on record"
            )
        elif superseded.label != version.supersedes_label:
            problems.append(
                f"policy version {version.version_id}: "
                "supersedes label does not match the "
                "superseded version's label"
            )
    if base is not None:
        if version.supersedes_label != base.version:
            problems.append(
                f"policy version {version.version_id}: "
                "diff base label disagrees with the pack "
                "it supersedes"
            )
        expected = diff_packs(base, version.pack)
        if expected != version.diff:
            problems.append(
                f"policy version {version.version_id}: "
                "stored diff disagrees with the recomputed "
                "diff against the superseded pack"
            )
    approved = _has_approved_pack_change(store, version.version_id)
    if version.status in ("standing", "superseded") and not approved:
        problems.append(
            f"policy version {version.version_id}: reads "
            f"{version.status} with no completed pack-change "
            "chain behind it"
        )
    if version.status == "proposed" and approved:
        problems.append(
            f"policy version {version.version_id}: its "
            "pack-change chain completed approved but the "
            "version does not stand"
        )
    return problems


def _has_approved_pack_change(store: "Store", version_id: str) -> bool:
    for decision in store.list_decisions(kind="pack_change"):
        if decision.target_id != version_id:
            continue
        acts = store.list_decision_acts(decision.decision_id)
        if fold_decision(decision, acts)["state"] == "approved":
            return True
    return False


def verify_decision(
    store: "Store", decision: DecisionCase,
    genesis: DeskPolicyPack | None = None,
) -> list[str]:
    genesis = genesis or load_desk_pack()
    problems: list[str] = []
    if decision_content_id(decision) != decision.decision_id:
        problems.append(
            f"decision {decision.decision_id}: content "
            "address does not recompute"
        )
    pack = pack_by_label(store, decision.pack_version, genesis)
    if pack is None:
        problems.append(
            f"decision {decision.decision_id}: pinned pack "
            f"{decision.pack_version!r} no longer resolves"
        )
        return problems
    if decision.pack_source_id is None:
        if decision.pack_version != genesis.version:
            problems.append(
                f"decision {decision.decision_id}: names no "
                "pack source but a non-genesis pack version"
            )
    else:
        source = store.get_policy_version(decision.pack_source_id)
        if source is None or source.label != decision.pack_version:
            problems.append(
                f"decision {decision.decision_id}: pack "
                "source does not carry the pinned label"
            )
    try:
        target_kind, target = target_for_decision(
            store, decision.kind, decision.target_id
        )
    except DeskError as exc:
        problems.append(
            f"decision {decision.decision_id}: target does "
            f"not resolve ({exc})"
        )
        return problems
    if target_kind != decision.target_kind:
        problems.append(
            f"decision {decision.decision_id}: target kind "
            "disagrees with the pack's assignment"
        )
    try:
        steps, facts = resolve_chain(pack, decision.kind, target)
        if steps != decision.steps:
            problems.append(
                f"decision {decision.decision_id}: pinned "
                "steps disagree with the chain re-resolved "
                "under its pack from the target's face"
            )
        if facts != decision.resolution:
            problems.append(
                f"decision {decision.decision_id}: pinned "
                "resolution facts disagree with re-performance"
            )
    except DeskError as exc:
        problems.append(
            f"decision {decision.decision_id}: chain does "
            f"not re-resolve ({exc})"
        )
    acts = store.list_decision_acts(decision.decision_id)
    problems.extend(
        _verify_acts(pack, decision, acts)
    )
    return problems


def _verify_acts(
    pack: DeskPolicyPack, decision: DecisionCase,
    acts: list[DecisionAct],
) -> list[str]:
    """Re-judge every act against the chain, in order."""
    problems: list[str] = []
    try:
        chain = pack.chain_for(decision.kind)
    except ValueError:
        return [
            f"decision {decision.decision_id}: the pinned "
            "pack carries no chain for its kind"
        ]
    ordered = sorted(acts, key=lambda a: (a.decided_on, a.act_id))
    approvals = 0
    closed: str | None = None
    seen: set[str] = set()
    for act in ordered:
        where = f"act {act.act_id} on decision {decision.decision_id}"
        if decision_act_content_id(act) != act.act_id:
            problems.append(f"{where}: content address does not recompute")
        if closed is not None:
            problems.append(
                f"{where}: struck after the decision closed "
                f"({closed})"
            )
            continue
        if act.decided_on < decision.opened_on:
            problems.append(f"{where}: predates the decision")
        if approvals >= len(decision.steps):
            problems.append(f"{where}: strikes beyond the chain")
            continue
        step = decision.steps[approvals]
        if act.step != step.step:
            problems.append(
                f"{where}: strikes step {act.step!r} where "
                f"the chain owed {step.step!r} — a skipped "
                "or reordered step"
            )
        if act.role != step.role:
            problems.append(
                f"{where}: struck in role {act.role!r} "
                f"where the step requires {step.role!r}"
            )
        if chain.forbid_requester and _folded_name(
            act.actor
        ) == _folded_name(decision.opened_by):
            problems.append(
                f"{where}: struck by the decision's opener "
                "— self-approval the pack forbids"
            )
        if chain.distinct_actors and _folded_name(act.actor) in seen:
            problems.append(
                f"{where}: actor already struck a step — "
                "the two-person rule is broken"
            )
        seen.add(_folded_name(act.actor))
        if act.outcome == "reject":
            closed = "rejected"
        elif act.outcome == "approve":
            approvals += 1
            if approvals >= len(decision.steps):
                closed = "approved"
    return problems


def verify_decision_log(
    store: "Store", log: DecisionLog
) -> list[str]:
    problems: list[str] = []
    if decision_log_content_id(log) != log.log_id:
        problems.append(
            f"decision log {log.log_id}: content address "
            "does not recompute"
        )
    try:
        rebuilt = build_decision_log(store, log.struck_on, log.fold_rule)
    except DeskError as exc:
        return problems + [
            f"decision log {log.log_id}: the record does "
            f"not re-fold ({exc})"
        ]
    if rebuilt.entries != log.entries:
        problems.append(
            f"decision log {log.log_id}: entries disagree "
            "with the re-folded record — an act is missing, "
            "added or altered"
        )
    seqs = [entry.seq for entry in log.entries]
    if seqs != list(range(1, len(seqs) + 1)):
        problems.append(
            f"decision log {log.log_id}: sequences are not "
            "gapless from 1"
        )
    return problems


def verify_comment(store: "Store", comment: ArtefactComment) -> list[str]:
    problems: list[str] = []
    if comment_content_id(comment) != comment.comment_id:
        problems.append(
            f"comment {comment.comment_id}: content address "
            "does not recompute"
        )
    if annotation_target(store, comment.target_kind, comment.target_id) is None:
        problems.append(
            f"comment {comment.comment_id}: target "
            f"{comment.target_kind} {comment.target_id} is "
            "not on record"
        )
    return problems


def verify_task(store: "Store", task: FollowUpTask) -> list[str]:
    problems: list[str] = []
    if task_content_id(task) != task.task_id:
        problems.append(
            f"task {task.task_id}: content address does "
            "not recompute"
        )
    if annotation_target(store, task.target_kind, task.target_id) is None:
        problems.append(
            f"task {task.task_id}: target "
            f"{task.target_kind} {task.target_id} is not "
            "on record"
        )
    state = "open"
    acts = sorted(
        store.list_task_acts(task.task_id),
        key=lambda a: (a.acted_on, a.act_id),
    )
    for act in acts:
        if task_act_content_id(act) != act.act_id:
            problems.append(
                f"task act {act.act_id}: content address "
                "does not recompute"
            )
        if act.acted_on < task.opened_on:
            problems.append(
                f"task act {act.act_id}: predates the task"
            )
        if act.action == "close" and state == "closed":
            problems.append(
                f"task act {act.act_id}: closes an already "
                "closed task"
            )
        if act.action == "reopen" and state == "open":
            problems.append(
                f"task act {act.act_id}: reopens an open task"
            )
        state = "closed" if act.action == "close" else "open"
    return problems


def verify_desk(store: "Store") -> list[str]:
    """Re-perform the whole desk layer."""
    genesis = load_desk_pack()
    problems: list[str] = []
    versions = store.list_policy_versions()
    standing = [v for v in versions if v.status == "standing"]
    if len(standing) > 1:
        problems.append(
            "more than one stored policy version reads standing"
        )
    labels = [v.label for v in versions]
    if len(set(labels)) != len(labels):
        problems.append("two stored policy versions share a label")
    for version in versions:
        problems.extend(verify_policy_version(store, version, genesis))
    for decision in store.list_decisions():
        problems.extend(verify_decision(store, decision, genesis))
    for log in store.list_decision_logs():
        problems.extend(verify_decision_log(store, log))
    for comment in store.list_comments():
        problems.extend(verify_comment(store, comment))
    for task in store.list_tasks():
        problems.extend(verify_task(store, task))
    return problems
