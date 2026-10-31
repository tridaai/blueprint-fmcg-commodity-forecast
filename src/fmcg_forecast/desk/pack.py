"""The desk policy pack — how the desk governs itself, as data.

Every rule that decides *who must agree before the desk
commits* is stated here, versioned, never buried in code:
the approval chains per decision kind (which steps, in
which order, struck by which role), the conditions under
which a chain grows its desk-head step (a forecast whose
measured accuracy is degraded or unmeasured; a coverage
commitment whose uncovered exposure clears the pack's
threshold), the two-person and no-self-approval rules,
and the rule that a policy change itself only stands
when its own chain completes.

The pack in this file is the genesis version. From
Round 15 the pack is also the desk's runtime
configuration (F20-AD2): a named desk user proposes a new
version as a stored artefact carrying its field-by-field
diff against the standing version — never an in-place
edit — and the proposal stands only when a pack-change
chain decision over it completes approved. Decisions
opened under a version name that version on their face
and are re-performed under exactly it, so a threshold
change reaches only decisions opened after it stands;
the record struck under the old version keeps the old
version on its face.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DecisionKind = Literal[
    "pack_change",
    "scenario_adoption",
    "forecast_approval",
    "coverage_commitment",
]

DECISION_KINDS: tuple[str, ...] = (
    "pack_change",
    "scenario_adoption",
    "forecast_approval",
    "coverage_commitment",
)

# Which artefact kind each decision kind governs. A
# decision's target is always an artefact of record, read
# back from the store at open time — never a caller-
# supplied copy of it.
TARGET_KIND_BY_DECISION: dict[str, str] = {
    "pack_change": "policy_version",
    "scenario_adoption": "scenario",
    "forecast_approval": "forecast",
    "coverage_commitment": "coverage_assessment",
}


class ChainStep(BaseModel):
    """One step of an approval chain, as the pack states it."""

    model_config = ConfigDict(extra="forbid")

    step: str = Field(description="The step's name, struck on its acts")
    role: str = Field(
        description="The only role whose act may strike this step"
    )
    when: Literal[
        "always", "forecast_degraded_or_unmeasured",
        "exposure_above_threshold",
    ] = Field(
        description="The condition under which this step is "
        "in the chain for a given target, judged at open "
        "time from the target artefact's own face"
    )
    rule: str = Field(description="Why this step exists, stated")


class ChainSpec(BaseModel):
    """One decision kind's chain, as the pack states it."""

    model_config = ConfigDict(extra="forbid")

    kind: DecisionKind
    steps: list[ChainStep] = Field(
        description="The chain's steps in strike order — "
        "an act may only strike the step the fold says is "
        "next, so a chain cannot be skipped"
    )
    distinct_actors: bool = Field(
        description="When true, no actor may strike two "
        "steps of one decision — the two-person rule"
    )
    forbid_requester: bool = Field(
        description="When true, the person who opened the "
        "decision may strike none of its steps — no "
        "self-approval"
    )
    rule: str = Field(description="What this chain governs, stated")


class DeskPolicyPack(BaseModel):
    """The desk's governing rules, as one versioned pack."""

    model_config = ConfigDict(extra="forbid")

    version: str
    exposure_threshold_inr: float = Field(
        description="A coverage commitment whose target's "
        "uncovered exposure is above this figure (INR, "
        "the assessment's own unit) grows the desk-head "
        "step in its chain"
    )
    chains: list[ChainSpec] = Field(
        description="One chain per decision kind — the "
        "loader refuses a pack that drops or duplicates one"
    )
    chain_rule: str = Field(
        description="How a chain is resolved and struck, stated"
    )
    activation_rule: str = Field(
        description="How a proposed policy version comes "
        "to stand, stated"
    )
    diff_rule: str = Field(
        description="How a proposal's diff against the "
        "standing version is computed, stated"
    )
    log_rule: str = Field(
        description="How the decision log folds the acts, stated"
    )
    annotation_rule: str = Field(
        description="How comments and follow-up tasks pin "
        "to artefacts, stated"
    )
    scope_note: str

    @model_validator(mode="after")
    def _chains_cover_every_kind(self) -> "DeskPolicyPack":
        kinds = [chain.kind for chain in self.chains]
        if sorted(kinds) != sorted(DECISION_KINDS):
            raise ValueError(
                "a desk policy pack carries exactly one chain "
                f"per decision kind {DECISION_KINDS}, got {kinds}"
            )
        for chain in self.chains:
            if not chain.steps:
                raise ValueError(
                    f"chain {chain.kind!r} carries no steps"
                )
            names = [step.step for step in chain.steps]
            if len(set(names)) != len(names):
                raise ValueError(
                    f"chain {chain.kind!r} repeats a step name"
                )
        if self.exposure_threshold_inr <= 0:
            raise ValueError("the exposure threshold must be positive")
        return self

    def chain_for(self, kind: str) -> ChainSpec:
        for chain in self.chains:
            if chain.kind == kind:
                return chain
        raise ValueError(f"no chain for decision kind {kind!r}")


DESK_SCOPE_NOTE = (
    "governance only — a decision records who agreed, it "
    "places no trade and moves no money; procurement "
    "execution is out of scope by design"
)


DESK_PACK_V1 = DeskPolicyPack(
    version="2026.10.1",
    exposure_threshold_inr=5_000_000.0,
    chains=[
        ChainSpec(
            kind="pack_change",
            steps=[
                ChainStep(
                    step="review",
                    role="analyst",
                    when="always",
                    rule="A named analyst reads the proposal "
                    "and its diff before anyone signs it off.",
                ),
                ChainStep(
                    step="sign_off",
                    role="desk_head",
                    when="always",
                    rule="Only a desk head's sign-off can put "
                    "new governing rules over the desk.",
                ),
            ],
            distinct_actors=True,
            forbid_requester=True,
            rule=(
                "Changing the desk's own rules takes an "
                "analyst's review and a desk head's sign-off, "
                "from two different people, neither of them "
                "the proposer. The completing sign-off is "
                "the act that makes the version stand."
            ),
        ),
        ChainSpec(
            kind="scenario_adoption",
            steps=[
                ChainStep(
                    step="adoption_review",
                    role="analyst",
                    when="always",
                    rule="A named analyst reviews the "
                    "scenario and its diff against the base "
                    "forecast before adoption is confirmed.",
                ),
                ChainStep(
                    step="adoption_confirm",
                    role="desk_head",
                    when="always",
                    rule="Adopting a scenario as the desk "
                    "view takes a second person, a desk "
                    "head, confirming the review.",
                ),
            ],
            distinct_actors=True,
            forbid_requester=True,
            rule=(
                "The two-person rule for adopting a "
                "scenario: review and confirmation by two "
                "different people, neither of them the "
                "person who opened the decision."
            ),
        ),
        ChainSpec(
            kind="forecast_approval",
            steps=[
                ChainStep(
                    step="review",
                    role="analyst",
                    when="always",
                    rule="A named analyst reviews the draft "
                    "forecast — its contributions, events "
                    "and accuracy attachment.",
                ),
                ChainStep(
                    step="desk_head_sign_off",
                    role="desk_head",
                    when="forecast_degraded_or_unmeasured",
                    rule="A forecast whose measured accuracy "
                    "is degraded, or which carries no "
                    "measurement at all, may not become the "
                    "desk's word on one person's review: a "
                    "desk head signs it off as well.",
                ),
            ],
            distinct_actors=True,
            forbid_requester=True,
            rule=(
                "A measured forecast is approved on an "
                "analyst's review. A degraded or unmeasured "
                "one grows a desk-head step — the weaker "
                "the measurement behind a number, the more "
                "senior the agreement it needs."
            ),
        ),
        ChainSpec(
            kind="coverage_commitment",
            steps=[
                ChainStep(
                    step="commit_review",
                    role="analyst",
                    when="always",
                    rule="A named analyst reviews the "
                    "coverage assessment — its plan, its "
                    "basis forecast and its options.",
                ),
                ChainStep(
                    step="desk_head_sign_off",
                    role="desk_head",
                    when="exposure_above_threshold",
                    rule="Above the pack's exposure "
                    "threshold the commitment is the desk's "
                    "money at risk, and a desk head signs "
                    "it off as well.",
                ),
            ],
            distinct_actors=True,
            forbid_requester=True,
            rule=(
                "A coverage commitment is reviewed by an "
                "analyst; when the assessment's uncovered "
                "exposure clears the pack's threshold, a "
                "desk head must also sign — approval above "
                "a stated exposure, as the desk's rule "
                "states it."
            ),
        ),
    ],
    chain_rule=(
        "A decision is opened against one artefact of "
        "record under the standing pack. Its chain is "
        "resolved at open time: the pack's steps for the "
        "kind, keeping a conditional step only when the "
        "target's own face meets the condition (a forecast "
        "whose accuracy attachment reads degraded or "
        "unmeasured; a coverage assessment whose uncovered "
        "exposure is above the pack's threshold). The "
        "resolved steps and the facts they were judged "
        "from are pinned on the decision's face, next to "
        "the pack version they were resolved under. An act "
        "strikes exactly the next unfilled step, by a "
        "named actor carrying that step's role; where the "
        "chain states it, no actor strikes twice and the "
        "opener strikes nothing. A rejection at any step "
        "closes the decision rejected. The decision's "
        "state is a fold over its acts, never a stored "
        "column."
    ),
    activation_rule=(
        "A proposed policy version stands only when a "
        "pack-change decision over it, opened under the "
        "then-standing pack, completes approved — the "
        "completing act flips it to standing and the "
        "previously standing stored version to superseded "
        "in the same strike. Until then the genesis pack "
        "in code, or the standing stored version, governs. "
        "There is no other path to standing: no surface "
        "activates a version directly."
    ),
    diff_rule=(
        "A proposal's diff is computed field by field over "
        "the pack's top-level fields, against the standing "
        "pack at proposal time: each changed field names "
        "its before and after values, and a changed chain "
        "diffs as its whole stated value. A proposal whose "
        "diff is empty is refused — a version that changes "
        "nothing is not a version."
    ),
    log_rule=(
        "The decision log folds every decision act struck "
        "on or before its as-of, in (decided_on, act_id) "
        "order, numbering them from 1 with no gaps. It is "
        "itself a struck artefact: re-striking after new "
        "acts lands on a new content address, and the "
        "verifier re-folds the record and compares entry "
        "for entry."
    ),
    annotation_rule=(
        "A comment or a follow-up task pins to one "
        "artefact by its exact content address — the "
        "artefact version it was written against. Artefact "
        "ids are never reused, so an annotation can never "
        "drift onto a later version: it renders on its own "
        "artefact or not at all. A task's state is a fold "
        "over its open/close acts. Where the pinned "
        "artefact itself carries a supersession lifecycle "
        "(a scenario reads superseded once a later adoption "
        "supersedes it), the task's read flags it — the "
        "task is never silently moved to the successor."
    ),
    scope_note=DESK_SCOPE_NOTE,
)


def load_desk_pack(version: str | None = None) -> DeskPolicyPack:
    """Load the genesis desk policy pack, fail-closed.

    An unknown version is an error, never a silent
    fallback — a decision struck under one pack must
    never be quietly re-read under another. Stored
    versions are loaded through the desk service, which
    reads them from their artefacts of record.
    """
    if version is None or version == DESK_PACK_V1.version:
        return DESK_PACK_V1
    raise ValueError(f"unknown desk policy pack version: {version!r}")
