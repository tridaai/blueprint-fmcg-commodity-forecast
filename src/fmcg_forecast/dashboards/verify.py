"""Dashboard verification: re-performance + the lineage walk.

Two checks stand between a spec and a page, run at assembly
time before anything is stored, and again on any stored
assembly a caller asks to verify:

1. **Re-performance.** Every resolved panel is re-resolved
   from the store and compared figure for figure — and behind
   the resolution, the family verifiers re-perform the
   artefacts themselves: a forecast panel's artefact must pass
   the forecast verifier (decomposition + content address), an
   accuracy figure's record must re-perform from the backtest
   results of record, a sentiment figure's index must
   recompute from the stored extractions, a scenario panel's
   run must pass the scenario verifier. One mismatch refuses
   the whole dashboard.

2. **The lineage walk (F20-DR3).** Every figure's lineage is
   walked against the store: the figure's own artefact is on
   its walk; every artefact fact names an artefact that
   exists; every terminal fact's stated provenance (source,
   date — and for an observation series, the row count and
   last observed date) re-checks against the stored rows; and
   the walk contains a terminal fact to end on. A figure
   without a complete walk cannot render.

The rendered HTML is a pure function of the spec and the
resolved panels, so a stored assembly also re-renders
byte-for-byte.
"""

from __future__ import annotations

from fmcg_forecast.backtest.pack import load_accuracy_pack
from fmcg_forecast.backtest.verify import verify_accuracy_record
from fmcg_forecast.dashboards.assemble import resolve_panel
from fmcg_forecast.dashboards.models import (
    DashboardAssembly,
    DashboardFigure,
    DashboardSpec,
    LineageFact,
    assembly_content_id,
    spec_content_id,
)
from fmcg_forecast.dashboards.pack import TERMINAL_FACT_KINDS, DashboardPack
from fmcg_forecast.dashboards.render import render_dashboard
from fmcg_forecast.events.service import EventService
from fmcg_forecast.forecast.verify import verify_forecast
from fmcg_forecast.scenarios.pack import load_scenario_pack
from fmcg_forecast.scenarios.verify import verify_scenario
from fmcg_forecast.sentiment.index import compute_index
from fmcg_forecast.sentiment.pack import SentimentPack


def _fact_problems(store, figure: DashboardFigure, fact: LineageFact) -> list[str]:
    where = f"figure {figure.key}"
    if fact.kind == "forecast":
        if store.get_forecast(fact.ref) is None:
            return [f"{where}: lineage names forecast {fact.ref}, not on record"]
    elif fact.kind == "accuracy_record":
        found = any(
            r.record_id == fact.ref for r in store.list_accuracy_records()
        )
        if not found:
            return [
                f"{where}: lineage names accuracy record {fact.ref}, "
                "not on record"
            ]
    elif fact.kind == "sentiment_index":
        from fmcg_forecast.catalogue import COMMODITIES

        found = any(
            idx.index_id == fact.ref
            for spec in COMMODITIES
            for idx in store.list_indices(spec.commodity)
        )
        if not found:
            return [
                f"{where}: lineage names sentiment index {fact.ref}, "
                "not on record"
            ]
    elif fact.kind == "scenario_run":
        if store.get_scenario(fact.ref) is None:
            return [
                f"{where}: lineage names scenario {fact.ref}, not on record"
            ]
    elif fact.kind == "observation_series":
        parts = fact.ref.split("/")
        if len(parts) != 3:
            return [f"{where}: malformed observation series ref {fact.ref!r}"]
        commodity, market, driver = parts
        rows = store.series(commodity, market, driver, end=fact.last_date)
        if not rows:
            return [
                f"{where}: lineage rests on observation series "
                f"{fact.ref}, which holds no rows"
            ]
        if fact.count is not None and fact.count != len(rows):
            return [
                f"{where}: lineage states {fact.count} rows for "
                f"{fact.ref} up to {fact.last_date}; the store "
                f"holds {len(rows)}"
            ]
        if fact.last_date is not None and rows[-1].obs_date != fact.last_date:
            return [
                f"{where}: lineage states last observation "
                f"{fact.last_date} for {fact.ref}; the store's "
                f"last is {rows[-1].obs_date}"
            ]
    elif fact.kind == "sentiment_item":
        item = store.get_sentiment_item(fact.ref)
        if item is None:
            return [
                f"{where}: lineage names sentiment item {fact.ref}, "
                "not on record"
            ]
        if item.source != fact.source or item.item_date != fact.fact_date:
            return [
                f"{where}: lineage states item {fact.ref} from "
                f"{fact.source!r} on {fact.fact_date}; the stored "
                f"item is from {item.source!r} on {item.item_date}"
            ]
    elif fact.kind == "event_declaration":
        event = store.get_market_event(fact.ref)
        if event is None:
            return [
                f"{where}: lineage names event {fact.ref}, not on record"
            ]
        if (
            fact.source != f"declared by {event.declared_by}"
            or fact.fact_date != event.declared_on
        ):
            return [
                f"{where}: lineage states event {fact.ref} "
                f"declared by {fact.source!r} on {fact.fact_date}; "
                f"the stored declaration is by {event.declared_by!r} "
                f"on {event.declared_on}"
            ]
    elif fact.kind == "manifest":
        manifest = store.get_manifest()
        if manifest is None or not manifest.history_digest.startswith(fact.ref):
            return [f"{where}: lineage names a dataset manifest not on record"]
    return []


def lineage_problems(store, figure: DashboardFigure) -> list[str]:
    """Walk one figure's lineage against the store."""
    problems: list[str] = []
    if not figure.lineage:
        problems.append(f"figure {figure.key}: no lineage — it cannot render")
        return problems
    refs = {fact.ref for fact in figure.lineage}
    if figure.artefact_id not in refs:
        problems.append(
            f"figure {figure.key}: its artefact {figure.artefact_id} "
            "is not on its own lineage walk"
        )
    if not any(fact.kind in TERMINAL_FACT_KINDS for fact in figure.lineage):
        problems.append(
            f"figure {figure.key}: the walk never terminates at a "
            "stored fact (observation series, sentiment item, "
            "event declaration or manifest)"
        )
    for fact in figure.lineage:
        problems.extend(_fact_problems(store, figure, fact))
    return problems


def _family_problems(
    store,
    events: EventService,
    sentiment_pack: SentimentPack,
    spec_panel,
    panel,
) -> list[str]:
    """Re-perform the artefacts behind one rendered panel with
    their own family verifiers. Kind and scope come from the
    spec panel; the resolved panel carries the artefacts."""
    problems: list[str] = []
    if spec_panel.kind == "forecast":
        from fmcg_forecast.dashboards.assemble import head_forecast

        head = head_forecast(
            store, spec_panel.scope["commodity"], spec_panel.scope["market"]
        )
        if head is not None:
            problems.extend(
                f"forecast {head.forecast_id}: {p}"
                for p in verify_forecast(head)
            )
    elif spec_panel.kind == "accuracy":
        pack = load_accuracy_pack()
        for record in store.list_accuracy_records(
            spec_panel.scope["commodity"], spec_panel.scope["market"]
        ):
            results = store.list_backtest_results(
                record.commodity, record.market, record.horizon_days
            )
            problems.extend(
                f"accuracy record {record.record_id}: {p}"
                for p in verify_accuracy_record(record, results, pack)
            )
    elif spec_panel.kind == "sentiment":
        indices = store.list_indices(spec_panel.scope["commodity"])
        if indices:
            index = indices[-1]
            recomputed = compute_index(
                index.commodity,
                index.week_start,
                store.list_extractions(index.commodity),
                sentiment_pack,
            )
            if recomputed is None or recomputed.index_id != index.index_id:
                problems.append(
                    f"sentiment index {index.index_id} does not "
                    "recompute from the stored extractions"
                )
    elif spec_panel.kind == "events":
        from fmcg_forecast.events.verify import verify_market_event

        for event in store.list_market_events(
            commodity=spec_panel.scope["commodity"]
        ):
            problems.extend(
                f"event {event.event_id}: {p}"
                for p in verify_market_event(event, events.pack)
            )
    elif spec_panel.kind == "scenario_diff":
        if panel.state == "rendered" and panel.artefact_ids:
            run = store.get_scenario(panel.artefact_ids[0])
            if run is not None:
                request = store.get_scenario_request(run.request_id)
                base = store.get_forecast(run.base_forecast_id)
                if request is not None and base is not None:
                    problems.extend(
                        f"scenario {run.scenario_id}: {p}"
                        for p in verify_scenario(
                            store,
                            run,
                            request,
                            base,
                            load_scenario_pack(),
                            events.pack,
                        )
                    )
    return problems


def verify_assembly(
    store,
    events: EventService,
    sentiment_pack: SentimentPack,
    pack: DashboardPack,
    spec: DashboardSpec,
    assembly: DashboardAssembly,
) -> list[str]:
    """Re-perform a candidate or stored assembly, whole.

    Returns the problems; an empty list means the dashboard may
    exist. Used by the service at assembly time (any problem
    refuses the dashboard before it is stored) and by the
    verify read on a stored assembly.
    """
    problems: list[str] = []
    if assembly.spec_id != spec.spec_id:
        problems.append(
            f"assembly {assembly.assembly_id} belongs to spec "
            f"{assembly.spec_id}, not {spec.spec_id}"
        )
        return problems
    if spec_content_id(spec) != spec.spec_id:
        problems.append(f"spec {spec.spec_id}: content address does not match")
    if assembly_content_id(assembly) != assembly.assembly_id:
        problems.append(
            f"assembly {assembly.assembly_id}: content address does not match"
        )
    if assembly.pack_version != pack.version or spec.pack_version != pack.version:
        problems.append("pack version mismatch between spec, assembly and pack")
    spec_panels = {p.panel_no: p for p in spec.panels}
    if {p.panel_no for p in assembly.panels} != set(spec_panels):
        problems.append("assembly panels do not match the spec's panels")
        return problems
    for resolved in assembly.panels:
        spec_panel = spec_panels[resolved.panel_no]
        try:
            fresh = resolve_panel(store, events, spec_panel)
        except Exception as exc:  # a broken artefact refuses the whole page
            problems.append(
                f"panel {resolved.panel_no} ({resolved.title}): "
                f"re-resolution failed: {exc}"
            )
            continue
        if fresh.state != resolved.state:
            problems.append(
                f"panel {resolved.panel_no} ({resolved.title}): stored "
                f"state {resolved.state} != re-resolved {fresh.state}"
            )
            continue
        if resolved.state == "gap":
            if fresh.gap_needed != resolved.gap_needed:
                problems.append(
                    f"panel {resolved.panel_no} ({resolved.title}): gap "
                    "statement does not re-perform"
                )
            continue
        if fresh.artefact_ids != resolved.artefact_ids:
            problems.append(
                f"panel {resolved.panel_no} ({resolved.title}): bound "
                f"artefacts {resolved.artefact_ids} != re-resolved "
                f"{fresh.artefact_ids}"
            )
        fresh_figures = {f.key: f for f in fresh.figures}
        if set(fresh_figures) != {f.key for f in resolved.figures}:
            problems.append(
                f"panel {resolved.panel_no} ({resolved.title}): figure "
                "set does not re-perform"
            )
        for figure in resolved.figures:
            fresh_figure = fresh_figures.get(figure.key)
            if fresh_figure is not None and (
                fresh_figure.value != figure.value
                or fresh_figure.artefact_id != figure.artefact_id
            ):
                problems.append(
                    f"panel {resolved.panel_no} figure {figure.key}: "
                    f"stored value {figure.value!r} from "
                    f"{figure.artefact_id} != re-performed "
                    f"{fresh_figure.value!r} from "
                    f"{fresh_figure.artefact_id}"
                )
            problems.extend(
                f"panel {resolved.panel_no}: {p}"
                for p in lineage_problems(store, figure)
            )
        problems.extend(
            _family_problems(store, events, sentiment_pack, spec_panel, resolved)
        )
    if render_dashboard(spec, assembly) != assembly.html:
        problems.append(
            "the stored HTML does not re-render byte-for-byte from "
            "the spec and panels"
        )
    return problems
