"""The dashboard service: ask, save, assemble, board — one workflow.

Every surface (API, CLI, demo) shares this service. Its rules:

- **Ask is the model port's job, validation is the pack's.**
  A prompt goes through the model port (offline: the pack's
  stated grammar; hosted: structured outputs, fail-closed) into
  a panel set, and the set is validated against the dashboard
  pack before it becomes a spec artefact. The spec records the
  ask-time artefact bindings; a clause the catalogue cannot
  state is a named gap panel on the spec — never dropped.
- **Assembly is verified before it exists.** Panels re-resolve
  to the current heads of their artefact families, the diff
  against the previous assembly is computed, the page is
  rendered — and then the whole candidate passes
  re-performance + the lineage walk (verify.py) before it is
  stored. One problem refuses the dashboard; nothing partial
  is ever stored. An identical re-assembly returns the stored
  assembly — it is the same artefact.
- **Saved views are names, not copies.** A view points at a
  spec; re-running the view is a fresh assembly of that spec
  against the store as it now stands.
- **The board is an artefact.** The morning board for a date
  is computed from artefacts only, content-addressed, and
  stored insert-only; rebuilding the same board is a no-op.
"""

from __future__ import annotations

from datetime import date

from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.dashboards.assemble import (
    AssemblyError,
    binding_ids_for,
    compute_assembly_diff,
    resolve_panel,
)
from fmcg_forecast.dashboards.board import build_board
from fmcg_forecast.dashboards.models import (
    DashboardAssembly,
    DashboardSpec,
    DashboardView,
    DeskBoard,
    SpecPanel,
    assembly_content_id,
    spec_content_id,
    view_content_id,
)
from fmcg_forecast.dashboards.pack import (
    PANEL_KINDS,
    DashboardPack,
    load_dashboard_pack,
)
from fmcg_forecast.dashboards.render import render_board, render_dashboard
from fmcg_forecast.dashboards.verify import verify_assembly
from fmcg_forecast.events.service import EventService
from fmcg_forecast.modelport import ModelPort
from fmcg_forecast.sentiment.service import SentimentService

_PLACEHOLDERS = {"", "unknown", "n/a", "na", "tbd", "none", "-", "null", "anon", "anonymous"}


class DashboardError(RuntimeError):
    """Base for dashboard refusals."""


class DashboardParseError(DashboardError):
    """The model port refused the prompt; the reason is named."""


class DashboardValidationError(DashboardError):
    """The panel set or the act itself is malformed."""


class DashboardNotFoundError(DashboardError):
    """No spec / assembly / view with that id."""


class DashboardVerificationError(DashboardError):
    """A candidate assembly failed re-performance or the
    lineage walk; the problems are named and nothing was stored."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _require_named(value: str, field: str) -> str:
    cleaned = value.strip()
    if cleaned.lower() in _PLACEHOLDERS:
        raise DashboardValidationError(
            f"{field} must name a person of record, not {value!r}"
        )
    return cleaned


class DashboardService:
    def __init__(
        self,
        store,
        model: ModelPort,
        events: EventService,
        sentiment: SentimentService,
        pack: DashboardPack | None = None,
    ):
        self.store = store
        self.model = model
        self.events = events
        self.sentiment = sentiment
        self.pack = pack or load_dashboard_pack()

    # -- ask ------------------------------------------------------------
    def ask(
        self, prompt: str, asked_by: str, created_on: date
    ) -> DashboardSpec:
        asked_by = _require_named(asked_by, "asked_by")
        adopted = {
            f"{s.commodity}/{s.market}": s.scenario_id
            for s in self.store.list_scenarios()
            if s.status == "adopted"
        }
        result = self.model.parse_dashboard(
            text=prompt, context={"adopted_scenarios": adopted}
        )
        if result.get("status") != "parsed":
            raise DashboardParseError(
                str(result.get("reason", "the parse was refused"))
            )
        panels: list[SpecPanel] = []
        for panel_no, raw in enumerate(result["panels"], start=1):
            panel = SpecPanel(panel_no=panel_no, **raw)
            self._validate_panel(panel)
            panel.binding_artefact_ids = binding_ids_for(self.store, panel)
            panels.append(panel)
        spec = DashboardSpec(
            spec_id="DSPEC-pending",
            prompt=prompt,
            asked_by=asked_by,
            model_profile=self.model.profile_name,
            pack_version=self.pack.version,
            created_on=created_on,
            panels=panels,
        )
        spec.spec_id = spec_content_id(spec)
        existing = self.store.get_dashboard_spec(spec.spec_id)
        if existing is not None:
            return existing
        self.store.insert_dashboard_spec(spec)
        return spec

    def _validate_panel(self, panel: SpecPanel) -> None:
        if panel.kind not in PANEL_KINDS:
            raise DashboardValidationError(
                f"unknown panel kind {panel.kind!r}; the dashboard "
                f"pack's catalogue states {sorted(PANEL_KINDS)}"
            )
        scope = panel.scope
        if panel.kind in ("forecast", "accuracy"):
            commodity, market = scope.get("commodity"), scope.get("market")
            if commodity not in BY_NAME or market not in {
                m.market for m in BY_NAME[commodity].markets
            }:
                raise DashboardValidationError(
                    f"panel {panel.panel_no}: scope "
                    f"{commodity}/{market} is not a series the "
                    "catalogue states"
                )
        elif panel.kind in ("sentiment", "events"):
            if scope.get("commodity") not in BY_NAME:
                raise DashboardValidationError(
                    f"panel {panel.panel_no}: commodity "
                    f"{scope.get('commodity')!r} is not in the catalogue"
                )
        elif panel.kind == "scenario_diff":
            if not scope.get("scenario_id") and scope.get(
                "scenario_ref"
            ) != "adopted":
                raise DashboardValidationError(
                    f"panel {panel.panel_no}: a scenario panel "
                    "must name a scenario (by id, or as the "
                    "adopted scenario for a series)"
                )

    def get_spec(self, spec_id: str) -> DashboardSpec:
        spec = self.store.get_dashboard_spec(spec_id)
        if spec is None:
            raise DashboardNotFoundError(f"unknown dashboard spec {spec_id}")
        return spec

    def list_specs(self) -> list[DashboardSpec]:
        return self.store.list_dashboard_specs()

    # -- saved views ------------------------------------------------------
    def save_view(
        self, spec_id: str, name: str, saved_by: str, saved_on: date
    ) -> DashboardView:
        self.get_spec(spec_id)
        name = name.strip()
        if not name:
            raise DashboardValidationError("a saved view needs a name")
        saved_by = _require_named(saved_by, "saved_by")
        view = DashboardView(
            view_id="DVIEW-pending",
            spec_id=spec_id,
            name=name,
            saved_by=saved_by,
            saved_on=saved_on,
        )
        view.view_id = view_content_id(view)
        existing = self.store.get_dashboard_view(view.view_id)
        if existing is not None:
            return existing
        self.store.insert_dashboard_view(view)
        return view

    def list_views(self, name: str | None = None) -> list[DashboardView]:
        return self.store.list_dashboard_views(name)

    def get_view(self, view_id: str) -> DashboardView:
        view = self.store.get_dashboard_view(view_id)
        if view is None:
            raise DashboardNotFoundError(f"unknown dashboard view {view_id}")
        return view

    # -- assembly -----------------------------------------------------------
    def assemble(
        self, spec_id: str, assembled_on: date
    ) -> DashboardAssembly:
        spec = self.get_spec(spec_id)
        try:
            panels = [
                resolve_panel(self.store, self.events, panel)
                for panel in spec.panels
            ]
        except AssemblyError as exc:
            raise DashboardVerificationError([str(exc)]) from exc
        assemblies = self.store.list_dashboard_assemblies(spec_id)
        previous = assemblies[-1] if assemblies else None
        if previous is not None and previous.panels == panels:
            return previous  # identical re-assembly: the same artefact
        diff = compute_assembly_diff(previous, panels)
        assembly = DashboardAssembly(
            assembly_id="DASH-pending",
            spec_id=spec_id,
            seq=(previous.seq + 1) if previous is not None else 1,
            supersedes=previous.assembly_id if previous is not None else None,
            assembled_on=assembled_on,
            pack_version=self.pack.version,
            panels=panels,
            diff=diff,
            html="",
        )
        assembly.assembly_id = assembly_content_id(assembly)
        assembly.html = render_dashboard(spec, assembly)
        problems = verify_assembly(
            self.store,
            self.events,
            self.sentiment.pack,
            self.pack,
            spec,
            assembly,
        )
        if problems:
            raise DashboardVerificationError(problems)
        existing = self.store.get_dashboard_assembly(assembly.assembly_id)
        if existing is not None:
            return existing
        self.store.insert_dashboard_assembly(assembly)
        return assembly

    def get_assembly(self, assembly_id: str) -> DashboardAssembly:
        assembly = self.store.get_dashboard_assembly(assembly_id)
        if assembly is None:
            raise DashboardNotFoundError(
                f"unknown dashboard assembly {assembly_id}"
            )
        return assembly

    def list_assemblies(
        self, spec_id: str | None = None
    ) -> list[DashboardAssembly]:
        return self.store.list_dashboard_assemblies(spec_id)

    def appendix(self, assembly_id: str) -> dict:
        """The provenance appendix as data (F20-DR3): every
        rendered figure with its artefact and its full lineage
        walk to stored facts."""
        assembly = self.get_assembly(assembly_id)
        return {
            "assembly_id": assembly.assembly_id,
            "spec_id": assembly.spec_id,
            "panels": [
                {
                    "panel_no": panel.panel_no,
                    "title": panel.title,
                    "state": panel.state,
                    "gap_needed": panel.gap_needed,
                    "figures": [
                        {
                            "key": figure.key,
                            "label": figure.label,
                            "value": figure.value,
                            "unit": figure.unit,
                            "artefact_id": figure.artefact_id,
                            "lineage": [
                                fact.model_dump(mode="json")
                                for fact in figure.lineage
                            ],
                        }
                        for figure in panel.figures
                    ],
                }
                for panel in assembly.panels
            ],
        }

    def verify_stored(self, assembly_id: str) -> list[str]:
        assembly = self.get_assembly(assembly_id)
        spec = self.get_spec(assembly.spec_id)
        return verify_assembly(
            self.store,
            self.events,
            self.sentiment.pack,
            self.pack,
            spec,
            assembly,
        )

    # -- the morning board --------------------------------------------------
    def board(self, board_date: date | None = None) -> DeskBoard:
        if board_date is None:
            manifest = self.store.get_manifest()
            if manifest is None:
                raise DashboardValidationError(
                    "dataset not loaded; run the ingest workflow first"
                )
            board_date = manifest.history_end
        board = build_board(self.store, self.events, self.pack, board_date)
        existing = self.store.get_desk_board(board.board_id)
        if existing is not None:
            return existing
        self.store.insert_desk_board(board)
        return board

    def board_view(self, board_date: date | None = None) -> dict:
        board = self.board(board_date)
        sections: dict[str, list[dict]] = {}
        for section in self.pack.board_sections:
            sections[section] = [
                row.model_dump(mode="json")
                for row in board.rows
                if row.kind == section
            ]
        # Row kinds outside the pack's section list (R8 signal
        # rows, appended by their own pack) surface under their
        # own section key rather than being dropped from the view.
        # The signal section is always present, like the pack's
        # own sections — empty when no signal row stands.
        sections["signal"] = [
            row.model_dump(mode="json")
            for row in board.rows
            if row.kind == "signal"
        ]
        for row in board.rows:
            if row.kind not in sections:
                sections[row.kind] = [
                    r.model_dump(mode="json")
                    for r in board.rows
                    if r.kind == row.kind
                ]
        return {
            "board": board.model_dump(mode="json"),
            "sections": sections,
            "html": render_board(board, self.pack),
        }
