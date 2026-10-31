"""The desk workflow every surface shares.

Proposing a policy version is a desk act: a named
proposer, a complete pack, a label the record has never
carried — stored with its diff against the standing
pack, computed here. Nothing about a proposal makes it
govern: a version stands only when a pack-change
decision over it completes its chain, and the completing
act flips the status in the same strike.

Opening a decision reads the target artefact of record,
resolves its chain under the standing pack, and pins
both on the decision's face. Striking an act is judged
against that pinned chain before it lands. Comments and
tasks pin to an artefact by its content address, which
the store must be able to resolve — an annotation over
nothing is refused at the door.
"""

from __future__ import annotations

from datetime import date

from pydantic import ValidationError

from fmcg_forecast.desk.engine import (
    DeskError,
    annotation_target,
    build_decision_log,
    check_act,
    diff_packs,
    fold_decision,
    fold_task,
    resolve_chain,
    target_for_decision,
    target_superseded,
)
from fmcg_forecast.desk.models import (
    ANNOTATION_TARGET_KINDS,
    ArtefactComment,
    DecisionAct,
    DecisionCase,
    DecisionLog,
    FollowUpTask,
    PolicyVersion,
    TaskAct,
    comment_content_id,
    decision_act_content_id,
    decision_content_id,
    policy_version_content_id,
    task_act_content_id,
    task_content_id,
)
from fmcg_forecast.desk.pack import (
    DESK_SCOPE_NOTE,
    DeskPolicyPack,
    load_desk_pack,
)
from fmcg_forecast.desk.verify import verify_desk
from fmcg_forecast.store import Store


class DeskNotFoundError(LookupError):
    """No desk artefact with that id."""


class DeskValidationError(ValueError):
    """A desk act or proposal the pack refuses."""


def _require_named(value: str, what: str) -> str:
    if not value or not value.strip():
        raise DeskValidationError(f"a {what} must be named")
    return value.strip()


class DeskService:
    def __init__(self, store: Store, genesis: DeskPolicyPack | None = None):
        self.store = store
        self.genesis = genesis or load_desk_pack()

    # -- the standing pack ---------------------------------------------

    def standing(self) -> dict:
        """The pack that governs now: the standing stored
        version's, or the genesis pack in code."""
        for version in self.store.list_policy_versions():
            if version.status == "standing":
                return {
                    "pack": version.pack,
                    "label": version.label,
                    "source_version_id": version.version_id,
                }
        return {
            "pack": self.genesis,
            "label": self.genesis.version,
            "source_version_id": None,
        }

    def standing_pack(self) -> DeskPolicyPack:
        return self.standing()["pack"]

    # -- policy versions (F20-AD2) ---------------------------------------

    def propose_policy_version(
        self,
        label: str,
        pack: DeskPolicyPack | dict,
        proposed_by: str,
        proposed_on: date,
    ) -> PolicyVersion:
        proposer = _require_named(proposed_by, "proposer")
        if isinstance(pack, dict):
            try:
                pack = DeskPolicyPack.model_validate(pack)
            except ValidationError as exc:
                raise DeskValidationError(
                    f"the proposed pack does not validate: {exc}"
                ) from exc
        if pack.version != label:
            raise DeskValidationError(
                f"label {label!r} does not match the pack's "
                f"own version {pack.version!r} — a version is "
                "named by its pack"
            )
        standing = self.standing()
        for existing in self.store.list_policy_versions():
            if existing.label == label:
                raise DeskValidationError(
                    f"pack version {label!r} is already on "
                    "record — versions are never re-proposed "
                    "or edited in place"
                )
        if label == self.genesis.version:
            raise DeskValidationError(
                f"pack version {label!r} is the genesis "
                "version — a stored version never takes the "
                "genesis label"
            )
        diff = diff_packs(standing["pack"], pack)
        if not diff:
            raise DeskValidationError(
                "the proposal changes nothing against the "
                "standing pack — a version that changes "
                "nothing is not a version"
            )
        version = PolicyVersion(
            version_id="",
            label=label,
            supersedes_version_id=standing["source_version_id"],
            supersedes_label=standing["label"],
            pack=pack,
            diff=diff,
            proposed_by=proposer,
            proposed_on=proposed_on,
            status="proposed",
        )
        version = version.model_copy(
            update={"version_id": policy_version_content_id(version)}
        )
        if self.store.get_policy_version(version.version_id) is None:
            self.store.insert_policy_version(version)
        return self.store.get_policy_version(version.version_id)

    def get_policy_version(self, version_id: str) -> PolicyVersion:
        version = self.store.get_policy_version(version_id)
        if version is None:
            raise DeskNotFoundError(f"no policy version {version_id}")
        return version

    def list_policy_versions(self) -> list[PolicyVersion]:
        return self.store.list_policy_versions()

    def policy_version_view(self, version_id: str) -> dict:
        from fmcg_forecast.desk.verify import verify_policy_version

        version = self.get_policy_version(version_id)
        view = version.model_dump(mode="json")
        view["problems"] = verify_policy_version(
            self.store, version, self.genesis
        )
        view["is_standing"] = (
            self.standing()["source_version_id"] == version_id
        )
        return view

    # -- decisions (F20-CA2) ----------------------------------------------

    def open_decision(
        self,
        kind: str,
        target_id: str,
        opened_by: str,
        opened_on: date,
        purpose: str,
    ) -> DecisionCase:
        opener = _require_named(opened_by, "opener")
        purpose = _require_named(purpose, "purpose")
        try:
            target_kind, target = target_for_decision(
                self.store, kind, target_id
            )
        except DeskError as exc:
            raise DeskValidationError(str(exc)) from exc
        if kind == "pack_change" and target.status != "proposed":
            raise DeskValidationError(
                f"policy version {target_id} reads "
                f"{target.status} — a pack-change decision "
                "governs a proposal, not a version that "
                "already stands or stood"
            )
        standing = self.standing()
        pack = standing["pack"]
        try:
            steps, facts = resolve_chain(pack, kind, target)
        except DeskError as exc:
            raise DeskValidationError(str(exc)) from exc
        decision = DecisionCase(
            decision_id="",
            kind=kind,
            target_kind=target_kind,
            target_id=target_id,
            opened_by=opener,
            opened_on=opened_on,
            purpose=purpose,
            pack_version=standing["label"],
            pack_source_id=standing["source_version_id"],
            steps=steps,
            resolution=facts,
            scope_note=DESK_SCOPE_NOTE,
        )
        decision = decision.model_copy(
            update={"decision_id": decision_content_id(decision)}
        )
        if self.store.get_decision(decision.decision_id) is None:
            self.store.insert_decision(decision)
        return decision

    def strike_act(
        self,
        decision_id: str,
        actor: str,
        role: str,
        outcome: str,
        decided_on: date,
        note: str = "",
    ) -> DecisionAct:
        decision = self.get_decision(decision_id)
        actor = _require_named(actor, "actor")
        role = _require_named(role, "role")
        if outcome not in ("approve", "reject"):
            raise DeskValidationError(
                f"outcome {outcome!r} is not an act's word — "
                "an act approves or rejects"
            )
        pack = self._pack_for(decision)
        acts = self.store.list_decision_acts(decision_id)
        try:
            step = check_act(
                pack,
                decision,
                acts,
                actor=actor,
                role=role,
                outcome=outcome,
                decided_on=decided_on,
            )
        except DeskError as exc:
            raise DeskValidationError(str(exc)) from exc
        act = DecisionAct(
            act_id="",
            decision_id=decision_id,
            step=step.step,
            actor=actor,
            role=role,
            outcome=outcome,  # type: ignore[arg-type]
            decided_on=decided_on,
            note=note,
        )
        act = act.model_copy(
            update={"act_id": decision_act_content_id(act)}
        )
        if self.store.get_decision_act(act.act_id) is None:
            self.store.insert_decision_act(act)
        # The completing act of a pack-change chain is the
        # activation: flip the version to standing and the
        # previously standing stored version to superseded,
        # in the same strike — the pack's stated rule.
        fold = fold_decision(decision, [*acts, act])
        if fold["state"] == "approved" and decision.kind == "pack_change":
            self._activate(decision.target_id)
        return act

    def _activate(self, version_id: str) -> None:
        for version in self.store.list_policy_versions():
            if version.status == "standing" and version.version_id != version_id:
                self.store.set_policy_version_status(
                    version.version_id, "superseded"
                )
        self.store.set_policy_version_status(version_id, "standing")

    def _pack_for(self, decision: DecisionCase) -> DeskPolicyPack:
        from fmcg_forecast.desk.verify import pack_by_label

        pack = pack_by_label(
            self.store, decision.pack_version, self.genesis
        )
        if pack is None:
            raise DeskValidationError(
                f"decision {decision.decision_id} pins pack "
                f"{decision.pack_version!r}, which no longer "
                "resolves"
            )
        return pack

    def get_decision(self, decision_id: str) -> DecisionCase:
        decision = self.store.get_decision(decision_id)
        if decision is None:
            raise DeskNotFoundError(f"no decision {decision_id}")
        return decision

    def list_decisions(
        self, kind: str | None = None, target_id: str | None = None
    ) -> list[DecisionCase]:
        return self.store.list_decisions(kind, target_id)

    def decision_view(self, decision_id: str) -> dict:
        from fmcg_forecast.desk.verify import verify_decision

        decision = self.get_decision(decision_id)
        acts = self.store.list_decision_acts(decision_id)
        fold = fold_decision(decision, acts)
        view = decision.model_dump(mode="json")
        view["state"] = fold["state"]
        view["next_step"] = fold["next_step"]
        view["acts"] = [
            a.model_dump(mode="json") for a in fold["acts"]
        ]
        view["problems"] = verify_decision(
            self.store, decision, self.genesis
        )
        return view

    # -- the decision log (F20-CA2) ----------------------------------------

    def strike_decision_log(self, struck_on: date) -> DecisionLog:
        standing = self.standing()
        log = build_decision_log(
            self.store, struck_on, standing["pack"].log_rule
        )
        if self.store.get_decision_log(log.log_id) is None:
            self.store.insert_decision_log(log)
        return log

    def get_decision_log(self, log_id: str) -> DecisionLog:
        log = self.store.get_decision_log(log_id)
        if log is None:
            raise DeskNotFoundError(f"no decision log {log_id}")
        return log

    def list_decision_logs(self) -> list[DecisionLog]:
        return self.store.list_decision_logs()

    def decision_log_view(self, log_id: str) -> dict:
        from fmcg_forecast.desk.verify import verify_decision_log

        log = self.get_decision_log(log_id)
        view = log.model_dump(mode="json")
        view["problems"] = verify_decision_log(self.store, log)
        return view

    # -- comments & tasks (F20-CA1) -----------------------------------------

    def _annotation_target(self, target_kind: str, target_id: str):
        if target_kind not in ANNOTATION_TARGET_KINDS:
            raise DeskValidationError(
                f"target kind {target_kind!r} cannot be "
                f"annotated — the kinds are "
                f"{list(ANNOTATION_TARGET_KINDS)}"
            )
        target = annotation_target(self.store, target_kind, target_id)
        if target is None:
            raise DeskValidationError(
                f"no {target_kind} {target_id} on record — "
                "an annotation pins to an artefact that exists"
            )
        return target

    def add_comment(
        self,
        target_kind: str,
        target_id: str,
        author: str,
        body: str,
        commented_on: date,
    ) -> ArtefactComment:
        author = _require_named(author, "author")
        body = _require_named(body, "comment body")
        self._annotation_target(target_kind, target_id)
        comment = ArtefactComment(
            comment_id="",
            target_kind=target_kind,
            target_id=target_id,
            author=author,
            body=body,
            commented_on=commented_on,
        )
        comment = comment.model_copy(
            update={"comment_id": comment_content_id(comment)}
        )
        if self.store.get_comment(comment.comment_id) is None:
            self.store.insert_comment(comment)
        return comment

    def list_comments(
        self, target_kind: str, target_id: str
    ) -> list[ArtefactComment]:
        return self.store.list_comments(target_kind, target_id)

    def open_task(
        self,
        target_kind: str,
        target_id: str,
        title: str,
        opened_by: str,
        assignee: str,
        opened_on: date,
    ) -> FollowUpTask:
        opener = _require_named(opened_by, "opener")
        assignee = _require_named(assignee, "assignee")
        title = _require_named(title, "task title")
        self._annotation_target(target_kind, target_id)
        task = FollowUpTask(
            task_id="",
            target_kind=target_kind,
            target_id=target_id,
            title=title,
            opened_by=opener,
            assignee=assignee,
            opened_on=opened_on,
        )
        task = task.model_copy(
            update={"task_id": task_content_id(task)}
        )
        if self.store.get_task(task.task_id) is None:
            self.store.insert_task(task)
        return task

    def strike_task_act(
        self,
        task_id: str,
        action: str,
        actor: str,
        acted_on: date,
        note: str = "",
    ) -> TaskAct:
        task = self.get_task(task_id)
        actor = _require_named(actor, "actor")
        if action not in ("close", "reopen"):
            raise DeskValidationError(
                f"task action {action!r} is not an act — a "
                "task act closes or reopens"
            )
        if acted_on < task.opened_on:
            raise DeskValidationError(
                "a task act cannot predate the task"
            )
        state = fold_task(self.store.list_task_acts(task_id))
        if action == "close" and state == "closed":
            raise DeskValidationError(
                f"task {task_id} is already closed"
            )
        if action == "reopen" and state == "open":
            raise DeskValidationError(
                f"task {task_id} is already open"
            )
        act = TaskAct(
            act_id="",
            task_id=task_id,
            action=action,  # type: ignore[arg-type]
            actor=actor,
            acted_on=acted_on,
            note=note,
        )
        act = act.model_copy(
            update={"act_id": task_act_content_id(act)}
        )
        if self.store.get_task_act(act.act_id) is None:
            self.store.insert_task_act(act)
        return act

    def get_task(self, task_id: str) -> FollowUpTask:
        task = self.store.get_task(task_id)
        if task is None:
            raise DeskNotFoundError(f"no task {task_id}")
        return task

    def list_tasks(
        self, target_kind: str | None = None,
        target_id: str | None = None,
    ) -> list[FollowUpTask]:
        return self.store.list_tasks(target_kind, target_id)

    def task_view(self, task_id: str) -> dict:
        from fmcg_forecast.desk.verify import verify_task

        task = self.get_task(task_id)
        acts = sorted(
            self.store.list_task_acts(task_id),
            key=lambda a: (a.acted_on, a.act_id),
        )
        target = annotation_target(
            self.store, task.target_kind, task.target_id
        )
        view = task.model_dump(mode="json")
        view["state"] = fold_task(acts)
        view["acts"] = [a.model_dump(mode="json") for a in acts]
        view["target_superseded"] = (
            target_superseded(self.store, task.target_kind, target)
            if target is not None
            else None
        )
        view["problems"] = verify_task(self.store, task)
        return view

    # -- verification -------------------------------------------------------

    def verify_all(self) -> list[str]:
        return verify_desk(self.store)


__all__ = [
    "DeskError",
    "DeskNotFoundError",
    "DeskService",
    "DeskValidationError",
]
