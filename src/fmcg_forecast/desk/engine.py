"""The desk engine: chain resolution, the state folds,
the pack diff and the decision-log fold.

Resolution reads the target artefact of record and
nothing else: a forecast's conditional step is judged
from the accuracy attachment pinned on the forecast
itself, a coverage commitment's from the assessment's
own stated exposure against the pack's threshold. The
resolved steps and the facts are pinned on the decision,
so the fold that later strikes the acts never re-judges
— and the verifier re-performs the resolution from the
same faces and compares.

State is folded, never stored. A decision's fold walks
its acts in the record's canonical order — (decided_on,
act_id), the same order the decision log exports — and
derives open / in_progress / approved / rejected plus
the next step owed. A task's fold is its last act.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from fmcg_forecast.desk.models import (
    DecisionAct,
    DecisionCase,
    DecisionLog,
    DecisionLogEntry,
    PackDiffEntry,
    ResolutionFact,
    TaskAct,
    decision_log_content_id,
)
from fmcg_forecast.desk.pack import (
    TARGET_KIND_BY_DECISION,
    ChainStep,
    DeskPolicyPack,
)

if TYPE_CHECKING:
    from fmcg_forecast.store import Store


class DeskError(Exception):
    """A desk computation the record refuses."""


def _folded_name(name: str) -> str:
    """Names compare folded, the maker–checker rule from
    assisted intake: case and spacing are not identity."""
    return " ".join(name.split()).casefold()


# -- target resolution -------------------------------------------------


def target_for_decision(store: "Store", kind: str, target_id: str):
    """The artefact of record a decision kind governs.

    Raises DeskError when the kind is unknown to the pack
    or the artefact is not on record — a decision is
    never opened against a caller-supplied copy.
    """
    target_kind = TARGET_KIND_BY_DECISION.get(kind)
    if target_kind is None:
        raise DeskError(f"unknown decision kind {kind!r}")
    getters = {
        "policy_version": store.get_policy_version,
        "scenario": store.get_scenario,
        "forecast": store.get_forecast,
        "coverage_assessment": store.get_coverage_assessment,
    }
    target = getters[target_kind](target_id)
    if target is None:
        raise DeskError(f"no {target_kind} {target_id} on record")
    return target_kind, target


def resolve_chain(
    pack: DeskPolicyPack, kind: str, target
) -> tuple[list[ChainStep], list[ResolutionFact]]:
    """Resolve a kind's chain for one target, under one
    pack: keep each conditional step only when the
    target's own face meets its condition, and pin the
    facts the conditions were judged from."""
    chain = pack.chain_for(kind)
    facts: list[ResolutionFact] = []
    accuracy_state: str | None = None
    exposure_inr: float | None = None
    if kind == "forecast_approval":
        accuracy_state = (
            target.accuracy.state
            if target.accuracy is not None
            else "unmeasured"
        )
        facts.append(
            ResolutionFact(
                name="accuracy_state",
                value=accuracy_state,
                rule="forecast_degraded_or_unmeasured",
            )
        )
    if kind == "coverage_commitment":
        exposure_inr = target.total_exposure_inr
        facts.append(
            ResolutionFact(
                name="exposure_inr",
                value=f"{exposure_inr:.2f}",
                rule="exposure_above_threshold",
            )
        )
        facts.append(
            ResolutionFact(
                name="exposure_threshold_inr",
                value=f"{pack.exposure_threshold_inr:.2f}",
                rule="exposure_above_threshold",
            )
        )
    steps: list[ChainStep] = []
    for step in chain.steps:
        if step.when == "always":
            steps.append(step)
        elif step.when == "forecast_degraded_or_unmeasured":
            if accuracy_state in ("degraded", "unmeasured"):
                steps.append(step)
        elif step.when == "exposure_above_threshold":
            if (
                exposure_inr is not None
                and exposure_inr > pack.exposure_threshold_inr
            ):
                steps.append(step)
    if not steps:
        raise DeskError(
            f"chain for {kind!r} resolved to no steps under "
            f"pack {pack.version}"
        )
    return steps, facts


# -- the decision fold ---------------------------------------------------


def fold_decision(
    decision: DecisionCase, acts: list[DecisionAct]
) -> dict:
    """Fold a decision's acts into its state.

    Acts are taken in the record's canonical order. The
    fold is descriptive — it reports what the acts say;
    whether each act was lawful when struck is the
    verifier's question, re-performed in verify.py.
    """
    ordered = sorted(acts, key=lambda a: (a.decided_on, a.act_id))
    approvals = [a for a in ordered if a.outcome == "approve"]
    rejected = next(
        (a for a in ordered if a.outcome == "reject"), None
    )
    if rejected is not None:
        state = "rejected"
        next_step = None
    elif len(approvals) >= len(decision.steps):
        state = "approved"
        next_step = None
    elif ordered:
        state = "in_progress"
        next_step = (
            decision.steps[len(approvals)].step
            if len(approvals) < len(decision.steps)
            else None
        )
    else:
        state = "open"
        next_step = decision.steps[0].step if decision.steps else None
    return {
        "state": state,
        "next_step": next_step,
        "acts": ordered,
        "approvals": len(approvals),
        "rejected_by": rejected.actor if rejected else None,
    }


def check_act(
    pack: DeskPolicyPack,
    decision: DecisionCase,
    acts: list[DecisionAct],
    *,
    actor: str,
    role: str,
    outcome: str,
    decided_on: date,
) -> ChainStep:
    """Judge one proposed act against the chain, or raise
    DeskError naming the refusal. Returns the step the
    act lawfully strikes."""
    fold = fold_decision(decision, acts)
    if fold["state"] in ("approved", "rejected"):
        raise DeskError(
            f"decision {decision.decision_id} is already "
            f"{fold['state']} — a closed decision takes no acts"
        )
    if decided_on < decision.opened_on:
        raise DeskError(
            "an act cannot predate the decision it strikes "
            f"({decided_on} before {decision.opened_on})"
        )
    step = decision.steps[fold["approvals"]]
    if role != step.role:
        raise DeskError(
            f"step {step.step!r} is struck by role "
            f"{step.role!r}, not {role!r} — a chain cannot "
            "be skipped or re-roled"
        )
    chain = pack.chain_for(decision.kind)
    if chain.forbid_requester and _folded_name(actor) == _folded_name(
        decision.opened_by
    ):
        raise DeskError(
            f"{actor!r} opened this decision — the pack "
            "forbids the requester striking its steps "
            "(no self-approval)"
        )
    if chain.distinct_actors:
        prior = {_folded_name(a.actor) for a in fold["acts"]}
        if _folded_name(actor) in prior:
            raise DeskError(
                f"{actor!r} already struck a step of this "
                "decision — the pack's two-person rule "
                "forbids one actor striking twice"
            )
    return step


# -- the pack diff (F20-AD2) --------------------------------------------


def diff_packs(
    before: DeskPolicyPack, after: DeskPolicyPack
) -> list[PackDiffEntry]:
    """The field-by-field diff of one pack against
    another, over top-level fields, in field order."""
    before_dump = before.model_dump(mode="json")
    after_dump = after.model_dump(mode="json")
    entries: list[PackDiffEntry] = []
    for field in sorted(set(before_dump) | set(after_dump)):
        if field == "version":
            continue
        if before_dump.get(field) != after_dump.get(field):
            entries.append(
                PackDiffEntry(
                    field=field,
                    before=before_dump.get(field),
                    after=after_dump.get(field),
                )
            )
    return entries


# -- the decision log fold (F20-CA2) --------------------------------------


def build_decision_log(
    store: "Store", struck_on: date, fold_rule: str
) -> DecisionLog:
    """Fold every decision act on record up to the
    log's as-of into one gapless export."""
    decisions = {d.decision_id: d for d in store.list_decisions()}
    acts = [
        act
        for act in store.list_decision_acts()
        if act.decided_on <= struck_on
    ]
    acts.sort(key=lambda a: (a.decided_on, a.act_id))
    entries: list[DecisionLogEntry] = []
    for seq, act in enumerate(acts, start=1):
        decision = decisions.get(act.decision_id)
        if decision is None:
            raise DeskError(
                f"act {act.act_id} names decision "
                f"{act.decision_id}, which is not on record"
            )
        entries.append(
            DecisionLogEntry(
                seq=seq,
                act_id=act.act_id,
                decision_id=act.decision_id,
                kind=decision.kind,
                target_kind=decision.target_kind,
                target_id=decision.target_id,
                step=act.step,
                actor=act.actor,
                role=act.role,
                outcome=act.outcome,
                decided_on=act.decided_on,
            )
        )
    log = DecisionLog(
        log_id="", struck_on=struck_on, entries=entries,
        fold_rule=fold_rule,
    )
    return log.model_copy(
        update={"log_id": decision_log_content_id(log)}
    )


# -- annotation targets (F20-CA1) ------------------------------------------


def annotation_target(store: "Store", target_kind: str, target_id: str):
    """The artefact a comment or task pins to, or None."""
    getters = {
        "forecast": store.get_forecast,
        "scenario": store.get_scenario,
        "market_event": store.get_market_event,
        "alert": store.get_alert,
        "buy_signal": store.get_buy_signal,
        "dashboard_view": store.get_dashboard_view,
        "coverage_assessment": store.get_coverage_assessment,
        "basis_reading": store.get_basis_reading,
        "landed_comparison": store.get_landed_comparison,
        "market_map": store.get_market_map,
    }
    getter = getters.get(target_kind)
    if getter is None:
        return None
    return getter(target_id)


def target_superseded(store: "Store", target_kind: str, target) -> bool:
    """Whether the record has superseded this artefact.

    Among the annotatable kinds only a scenario carries
    a supersession lifecycle on its own face — it reads
    superseded once a later adoption supersedes it. The
    other kinds are single-version artefacts: nothing
    supersedes them, and the flag honestly reads False.
    """
    if target_kind == "scenario":
        return target.status == "superseded"
    return False


def fold_task(acts: list[TaskAct]) -> str:
    """A task's state: its last act's word, or open."""
    if not acts:
        return "open"
    ordered = sorted(acts, key=lambda a: (a.acted_on, a.act_id))
    return "closed" if ordered[-1].action == "close" else "open"
