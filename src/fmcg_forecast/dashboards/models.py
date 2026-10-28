"""Dashboard artefacts (R7, Law 6).

A *dashboard spec* is the parse of a desk prompt: the original
words (verbatim), the panels they became under the dashboard
pack, each panel's scope and parse provenance, and the artefact
bindings resolved at ask time. A clause the catalogue cannot
state is a gap panel on the spec itself — named, never dropped.

A *dashboard assembly* is one rendering of a spec against the
store as it stands: every panel re-resolved to the current
head of its artefact family, every figure re-performed before
the page exists, a computed diff against the previous assembly
(changed figures, superseded bindings, panels that flipped
between gap and rendered), the provenance appendix (each
figure's lineage walk to stored facts) and the static HTML —
a pure function of the stored content, so a stored assembly
re-renders byte-for-byte.

A *saved view* is the named pointer that makes a spec
re-runnable by name. A *desk board* is the morning exception
inbox: rows derived from artefacts only, ranked exceptions
first, every row linked to the artefact behind it.

Specs, assemblies and boards are content-addressed and
insert-only, like every other artefact in this blueprint.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

# Fact kinds whose presence ends a lineage walk (mirrors the
# pack's TERMINAL_FACT_KINDS; stated here for the models).
FactKind = Literal[
    "forecast",
    "accuracy_record",
    "sentiment_index",
    "scenario_run",
    "observation_series",
    "sentiment_item",
    "event_declaration",
    "manifest",
]


class LineageFact(BaseModel):
    """One step of a figure's lineage walk.

    The walk reads figure -> artefact -> input facts -> source +
    date, and terminates at stored facts (observation rows,
    sentiment items, event declarations, the dataset manifest).
    Every fact is checkable against the store: an artefact fact
    names an artefact that must exist; a terminal fact carries
    the provenance (source, date — and, for an observation
    series, the row count and last observed date) the verifier
    re-checks against the stored rows.
    """

    kind: FactKind
    ref: str = Field(
        description="The artefact id, or the series key "
        "(commodity/market/driver) for an observation series, "
        "or the manifest digest prefix"
    )
    detail: str = Field(description="What this fact is, stated")
    source: str = Field(
        description="Provenance: where the fact came from (a "
        "source label, a declarer, the observation store)"
    )
    fact_date: date | None = Field(
        description="The fact's own date: an item's date, a "
        "declaration date, an index's week, a forecast's as_of"
    )
    count: int | None = Field(
        default=None,
        description="Observation series only: the stored row "
        "count the walk rests on",
    )
    last_date: date | None = Field(
        default=None,
        description="Observation series only: the last stored "
        "observation date the walk rests on",
    )


class DashboardFigure(BaseModel):
    """One figure on a rendered panel: a value read from one
    artefact, carrying its full lineage walk."""

    key: str = Field(description="The figure's name from the pack's panel catalogue")
    label: str = Field(description="The figure as the desk reads it")
    value: float | int | str = Field(
        description="The value exactly as the artefact carries "
        "it — a number, or a stated word (a state, a week, a "
        "named not-measurable) where the honest value is a word"
    )
    unit: str
    artefact_id: str = Field(description="The artefact the figure was read from")
    lineage: list[LineageFact] = Field(
        description="The walk from this figure to stored facts. "
        "Non-empty, every fact resolvable, and the walk ends at "
        "a terminal fact — a figure without a complete walk "
        "cannot render"
    )


class SpecPanel(BaseModel):
    """One panel of a spec, as parsed."""

    panel_no: int
    kind: str = Field(description="A kind from the pack's catalogue, or gap")
    title: str
    scope: dict = Field(
        description="commodity / market / scenario_id / "
        "scenario_ref, as the clause stated them (defaults "
        "applied are named in origin)"
    )
    clause: str = Field(description="The prompt clause this panel came from, verbatim")
    origin: dict = Field(
        description="Parse provenance: via (grammar), the rule "
        "that matched, and any pack default applied"
    )
    gap_needed: str | None = Field(
        default=None,
        description="For a gap panel: what would answer the "
        "request, named. None for a stated panel",
    )
    binding_artefact_ids: list[str] = Field(
        default_factory=list,
        description="The artefacts this panel bound at ask "
        "time; assembly re-resolves and names supersession "
        "against these",
    )


class DashboardSpec(BaseModel):
    """A prompt, parsed into a stated dashboard spec."""

    spec_id: str
    prompt: str = Field(description="The desk's words, verbatim")
    asked_by: str
    model_profile: str = Field(
        description="The model-port profile that produced the "
        "panel set (offline grammar or a hosted structured parse)"
    )
    pack_version: str
    created_on: date
    panels: list[SpecPanel]


def spec_content_id(spec: DashboardSpec) -> str:
    """The content address: over the ask — prompt, asker and the
    panels' kinds/scopes/clauses — not the id, not the day, and
    not the ask-time bindings (heads move; the ask does not)."""
    payload = spec.model_dump(
        mode="json",
        exclude={"spec_id", "created_on"},
    )
    for panel in payload["panels"]:
        panel.pop("binding_artefact_ids", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "DSPEC-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]


class ResolvedPanel(BaseModel):
    """One panel of an assembly: figures re-performed from the
    store, or a named gap where the data cannot answer."""

    panel_no: int
    kind: str = Field(description="The spec panel's kind (a rendered gap keeps its asked kind)")
    title: str
    state: Literal["rendered", "gap"]
    gap_needed: str | None = Field(
        default=None,
        description="For a gap: what would answer it, named — "
        "the missing artefact or figure, never a number",
    )
    figures: list[DashboardFigure] = Field(default_factory=list)
    artefact_ids: list[str] = Field(
        default_factory=list,
        description="The artefacts this panel resolved to at "
        "assembly time (the head bindings)",
    )
    superseded_from: list[str] = Field(
        default_factory=list,
        description="Binding artefact ids (at ask time or the "
        "previous assembly) that re-resolution replaced",
    )
    note: str | None = Field(
        default=None,
        description="A stated panel note: an unmeasured horizon, "
        "a scenario's hypothetical badge, an index's age",
    )


class AssemblyDiffEntry(BaseModel):
    """One line of an assembly's computed diff against the
    previous assembly of the same spec."""

    kind: Literal["figure_changed", "binding_superseded", "panel_state_changed"]
    panel_no: int
    panel_title: str
    figure_key: str | None = None
    label: str | None = None
    before: object = Field(default=None, description="The prior value / binding set / state")
    after: object = Field(default=None, description="The current value / binding set / state")


class DashboardAssembly(BaseModel):
    """One verified rendering of a spec, with its appendix and
    its diff. Insert-only; an identical re-assembly is the same
    artefact and is returned, not duplicated."""

    assembly_id: str
    spec_id: str
    seq: int = Field(description="This spec's assembly sequence (1-based, by insertion)")
    supersedes: str | None = Field(
        description="The previous assembly of this spec, by id; "
        "None for the first"
    )
    assembled_on: date
    pack_version: str
    panels: list[ResolvedPanel]
    diff: list[AssemblyDiffEntry]
    html: str = Field(
        description="The rendered static page — a pure function "
        "of the spec and the resolved panels, re-rendered "
        "byte-for-byte by the verifier"
    )


def assembly_content_id(assembly: DashboardAssembly) -> str:
    """The content address: over the spec, the resolved panels,
    the diff and the position in the spec's assembly chain —
    not the id or the day."""
    payload = assembly.model_dump(
        mode="json", exclude={"assembly_id", "assembled_on", "html"}
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "DASH-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]


class DashboardView(BaseModel):
    """A saved view: a name a desk user re-runs a spec by."""

    view_id: str
    spec_id: str
    name: str
    saved_by: str
    saved_on: date


def view_content_id(view: DashboardView) -> str:
    payload = view.model_dump(mode="json", exclude={"view_id", "saved_on"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "DVIEW-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]


class BoardRow(BaseModel):
    """One exception row of the morning desk board."""

    kind: Literal[
        "degraded", "pending_gate", "active_event", "forecast_change", "data_gap"
    ]
    commodity: str | None = None
    market: str | None = None
    headline: str = Field(description="The exception, stated in one line")
    artefact_id: str = Field(description="The artefact behind the row")
    artefact_ids: list[str] = Field(
        default_factory=list,
        description="Every artefact the row rests on (the "
        "primary first) — each must resolve in the store",
    )
    figures: dict[str, float | int | str] = Field(
        default_factory=dict,
        description="The row's stated figures, read from the "
        "artefacts named",
    )


class DeskBoard(BaseModel):
    """The morning desk board for one date: exceptions ranked
    first, derived from artefacts only."""

    board_id: str
    board_date: date
    pack_version: str
    rows: list[BoardRow]


def board_content_id(board: DeskBoard) -> str:
    payload = board.model_dump(mode="json", exclude={"board_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "BOARD-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]
