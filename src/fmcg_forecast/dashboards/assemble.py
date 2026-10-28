"""The assembler: spec panels -> figures, from artefacts only.

Each spec panel re-resolves to the CURRENT head of its artefact
family at assembly time: a forecast panel reads the series'
head forecast under the pack's head rule, a sentiment panel the
latest stored index, a scenario panel the named run. Bindings
the re-resolution replaced are named on the panel as
superseded. A panel whose data is not on record becomes a
rendered gap — the named thing that would answer it, never a
number. The diff against the previous assembly is computed
here: changed figures, superseded bindings, panels that
flipped between gap and rendered.

Resolution is also the assembler's re-performance: figures are
read from the stored artefacts through the same code the
verifier re-runs, and the family verifiers (forecast
decomposition, index recomputation, the scenario diff) stand
behind them in verify.py.
"""

from __future__ import annotations

from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.dashboards import lineage
from fmcg_forecast.dashboards.models import (
    AssemblyDiffEntry,
    DashboardAssembly,
    DashboardFigure,
    ResolvedPanel,
    SpecPanel,
)
from fmcg_forecast.dashboards.pack import DashboardPack
from fmcg_forecast.events.service import EventService
from fmcg_forecast.forecast.models import Forecast
from fmcg_forecast.scenarios.diff import compute_diff

_VIEW_KINDS = {
    "draft": "scenario_draft",
    "adopted": "adopted_scenario",
    "superseded": "superseded_scenario",
}


class AssemblyError(RuntimeError):
    """A stored artefact does not re-perform at assembly time —
    the dashboard is refused whole, never rendered partial."""


def head_forecast(store, commodity: str, market: str) -> Forecast | None:
    """The series' current forecast artefact, under the pack's
    head rule: official outranks draft, then greatest as_of,
    then greatest content address."""
    candidates = store.list_forecasts(commodity, market)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda f: (f.status == "official", f.as_of, f.forecast_id),
    )


def _gap_panel(panel: SpecPanel, needed: str) -> ResolvedPanel:
    return ResolvedPanel(
        panel_no=panel.panel_no,
        kind=panel.kind,
        title=panel.title,
        state="gap",
        gap_needed=needed,
        figures=[],
        artefact_ids=[],
        superseded_from=[],
        note=None,
    )


def _figure(
    key: str,
    label: str,
    value,
    unit: str,
    artefact_id: str,
    facts: list,
) -> DashboardFigure:
    return DashboardFigure(
        key=key,
        label=label,
        value=value,
        unit=unit,
        artefact_id=artefact_id,
        lineage=facts,
    )


def resolve_forecast_panel(store, panel: SpecPanel) -> ResolvedPanel:
    commodity, market = panel.scope["commodity"], panel.scope["market"]
    display = BY_NAME[commodity].display
    head = head_forecast(store, commodity, market)
    if head is None:
        return _gap_panel(
            panel,
            f"a forecast run for {display} at {market} — none is "
            "on record",
        )
    facts = lineage.forecast_lineage(store, head)
    summaries = {s.horizon_days: s for s in head.horizons_summary}
    figures: list[DashboardFigure] = []
    for horizon in (7, 30, 90):
        summary = summaries[horizon]
        figures.append(
            _figure(
                f"p50_{horizon}d",
                f"P50 at {horizon} days ({summary.forecast_date.isoformat()})",
                summary.p50,
                "INR/quintal",
                head.forecast_id,
                facts,
            )
        )
    figures.append(
        _figure(
            "band_30d_low", "P10 at 30 days", summaries[30].p10,
            "INR/quintal", head.forecast_id, facts,
        )
    )
    figures.append(
        _figure(
            "band_30d_high", "P90 at 30 days", summaries[30].p90,
            "INR/quintal", head.forecast_id, facts,
        )
    )
    accuracy = head.accuracy
    record_ids: list[str] = []
    state_value: str = "unmeasured"
    state_artefact = head.forecast_id
    state_facts = facts
    mape_value: float | str = "unmeasured"
    mape_artefact = head.forecast_id
    mape_facts = facts
    if accuracy is not None:
        state_value = accuracy.state
        for slice_ in accuracy.per_horizon:
            if slice_.record_id is not None:
                record_ids.append(slice_.record_id)
            if slice_.horizon_days == 30 and slice_.record_id is not None:
                record = store.get_accuracy_record(
                    commodity, market, 30
                )
                if record is not None:
                    state_artefact = record.record_id
                    state_facts = lineage.accuracy_lineage(store, record)
                    mape_value = slice_.mape
                    mape_artefact = record.record_id
                    mape_facts = state_facts
    figures.append(
        _figure(
            "accuracy_state", "Backtest accuracy state", state_value,
            "state", state_artefact, state_facts,
        )
    )
    figures.append(
        _figure(
            "mape_30d", "Pooled MAPE at 30 days", mape_value,
            "%" if isinstance(mape_value, float) else "state",
            mape_artefact, mape_facts,
        )
    )
    notes: list[str] = []
    if accuracy is not None and accuracy.state == "degraded":
        notes.append(f"DEGRADED — {accuracy.note}")
    elif accuracy is not None:
        notes.append(accuracy.note)
    if head.missing_drivers:
        notes.append(
            "named gaps on the artefact: "
            + ", ".join(head.missing_drivers)
        )
    return ResolvedPanel(
        panel_no=panel.panel_no,
        kind=panel.kind,
        title=panel.title,
        state="rendered",
        gap_needed=None,
        figures=figures,
        artefact_ids=[head.forecast_id, *record_ids],
        superseded_from=[],
        note="; ".join(notes) if notes else None,
    )


def resolve_accuracy_panel(store, panel: SpecPanel) -> ResolvedPanel:
    commodity, market = panel.scope["commodity"], panel.scope["market"]
    display = BY_NAME[commodity].display
    records = {
        r.horizon_days: r for r in store.list_accuracy_records(commodity, market)
    }
    if not records:
        return _gap_panel(
            panel,
            f"backtest coverage for {display} at {market} — no "
            "accuracy records on record; run the backtest harness",
        )
    figures: list[DashboardFigure] = []
    for horizon in (7, 30, 90):
        record = records.get(horizon)
        if record is None:
            continue
        facts = lineage.accuracy_lineage(store, record)
        figures.append(
            _figure(
                f"mape_{horizon}d", f"Pooled MAPE at {horizon} days",
                record.mape, "%", record.record_id, facts,
            )
        )
        figures.append(
            _figure(
                f"state_{horizon}d", f"Accuracy state at {horizon} days",
                "degraded" if record.degraded else "measured",
                "state", record.record_id, facts,
            )
        )
        if horizon == 30:
            figures.append(
                _figure(
                    "mae_30d", "Pooled MAE at 30 days", record.mae,
                    "INR/quintal", record.record_id, facts,
                )
            )
            figures.append(
                _figure(
                    "coverage_30d", "Band coverage at 30 days",
                    record.coverage, "share", record.record_id, facts,
                )
            )
    unmeasured = [h for h in (7, 30, 90) if h not in records]
    note = None
    if unmeasured:
        note = (
            "no backtest coverage at the "
            + "/".join(str(h) for h in unmeasured)
            + "-day horizon(s) yet — unmeasured, named"
        )
    return ResolvedPanel(
        panel_no=panel.panel_no,
        kind=panel.kind,
        title=panel.title,
        state="rendered",
        gap_needed=None,
        figures=figures,
        artefact_ids=[records[h].record_id for h in sorted(records)],
        superseded_from=[],
        note=note,
    )


def resolve_sentiment_panel(store, panel: SpecPanel) -> ResolvedPanel:
    commodity = panel.scope["commodity"]
    display = BY_NAME[commodity].display
    indices = store.list_indices(commodity)
    if not indices:
        return _gap_panel(
            panel,
            f"a sentiment index for {display} — no week of "
            "record holds a classified item in its trailing "
            "window, so no index exists (absent, never zero)",
        )
    index = indices[-1]
    facts = lineage.index_lineage(store, index)
    figures = [
        _figure(
            "index_value",
            f"Sentiment index, week of {index.week_start.isoformat()}",
            index.value, "index", index.index_id, facts,
        ),
        _figure(
            "week_start", "Index week (Monday)",
            index.week_start.isoformat(), "week", index.index_id, facts,
        ),
        _figure(
            "n_items", "Classified items in the window",
            index.n_items, "items", index.index_id, facts,
        ),
    ]
    for aspect in sorted(index.aspect_values):
        figures.append(
            _figure(
                f"aspect_{aspect}", f"{aspect} sub-index",
                index.aspect_values[aspect], "index", index.index_id,
                facts,
            )
        )
    return ResolvedPanel(
        panel_no=panel.panel_no,
        kind=panel.kind,
        title=panel.title,
        state="rendered",
        gap_needed=None,
        figures=figures,
        artefact_ids=[index.index_id],
        superseded_from=[],
        note=(
            f"the latest index of record is the week of "
            f"{index.week_start.isoformat()}.."
            f"{index.week_end.isoformat()} — stated with its "
            "week on its face, never presented as current "
            "beyond it"
        ),
    )


def resolve_events_panel(
    store, events: EventService, panel: SpecPanel
) -> ResolvedPanel:
    commodity = panel.scope["commodity"]
    display = BY_NAME[commodity].display
    declared = store.list_market_events(commodity)
    if not declared:
        return _gap_panel(
            panel,
            f"a declared event for {display} — the registry "
            "holds none for this commodity",
        )
    figures: list[DashboardFigure] = []
    artefact_ids: list[str] = []
    unverified: list[str] = []
    for event in declared:
        verdict = events.verify_event(event.event_id)
        facts = lineage.event_lineage(store, event)
        artefact_ids.append(event.event_id)
        if verdict.status == "unverified":
            unverified.append(event.event_id)
        figures.append(
            _figure(
                f"claimed_peak:{event.event_id}",
                f"{event.event_class} ({event.window_start.isoformat()}) "
                "claimed peak",
                event.transmission.peak_log_price_effect,
                "log price effect", event.event_id, facts,
            )
        )
        figures.append(
            _figure(
                f"verification_status:{event.event_id}",
                f"{event.event_class} ({event.window_start.isoformat()}) "
                "transmission verdict",
                verdict.status, "verdict", event.event_id, facts,
            )
        )
        figures.append(
            _figure(
                f"measured_ratio:{event.event_id}",
                f"{event.event_class} ({event.window_start.isoformat()}) "
                "measured price ratio",
                verdict.measured_ratio
                if verdict.measured_ratio is not None
                else "not measurable",
                "ratio" if verdict.measured_ratio is not None else "state",
                event.event_id, facts,
            )
        )
    note = None
    if unverified:
        note = (
            "transmission unverified on the face of: "
            + ", ".join(unverified)
            + " — the claim and the measurement disagree"
        )
    return ResolvedPanel(
        panel_no=panel.panel_no,
        kind=panel.kind,
        title=panel.title,
        state="rendered",
        gap_needed=None,
        figures=figures,
        artefact_ids=artefact_ids,
        superseded_from=[],
        note=note,
    )


def resolve_scenario_panel(store, panel: SpecPanel) -> ResolvedPanel:
    run = None
    if panel.scope.get("scenario_id"):
        run = store.get_scenario(panel.scope["scenario_id"])
        if run is None:
            return _gap_panel(
                panel,
                f"the scenario {panel.scope['scenario_id']} — no "
                "such run is on record",
            )
    else:
        commodity, market = panel.scope["commodity"], panel.scope["market"]
        adopted = next(
            (
                s
                for s in store.list_scenarios(commodity, market)
                if s.status == "adopted"
            ),
            None,
        )
        if adopted is None:
            return _gap_panel(
                panel,
                f"an adopted scenario for {commodity} at "
                f"{market} — no scenario has been adopted for "
                "this series, and no draft is dressed up as one",
            )
        run = adopted
    base = store.get_forecast(run.base_forecast_id)
    if base is None:
        raise AssemblyError(
            f"scenario {run.scenario_id} pins base forecast "
            f"{run.base_forecast_id}, which is not on record — "
            "the fork cannot be stated"
        )
    diff, problems = compute_diff(run.scenario_id, base, run.fork)
    if problems:
        raise AssemblyError(
            f"scenario {run.scenario_id} does not diff cleanly "
            "against its base: " + "; ".join(problems)
        )
    facts = lineage.scenario_lineage(store, run)
    view_kind = _VIEW_KINDS[run.status]
    figures = [
        _figure(
            "view_kind", "Scenario view kind", view_kind, "state",
            run.scenario_id, facts,
        ),
        *[
            _figure(
                f"p50_diff_{h}d", f"P50 difference at {h} days",
                diff.at_horizons[str(h)], "INR/quintal",
                run.scenario_id, facts,
            )
            for h in (7, 30, 90)
        ],
        *[
            _figure(
                f"driver_total:{driver}", f"{driver} difference, whole horizon",
                total, "INR/quintal", run.scenario_id, facts,
            )
            for driver, total in sorted(diff.driver_totals.items())
        ],
        _figure(
            "events_total", "Events difference, whole horizon",
            diff.events_total, "INR/quintal", run.scenario_id, facts,
        ),
        _figure(
            "p50_total", "P50 difference, whole horizon",
            diff.p50_total, "INR/quintal", run.scenario_id, facts,
        ),
    ]
    return ResolvedPanel(
        panel_no=panel.panel_no,
        kind=panel.kind,
        title=panel.title,
        state="rendered",
        gap_needed=None,
        figures=figures,
        artefact_ids=[run.scenario_id, run.base_forecast_id],
        superseded_from=[],
        note=(
            f"a pinned fork of {run.base_forecast_id} (the base "
            f"forecast, status {base.status}) — a scenario is "
            f"not the desk's forecast; this one reads "
            f"'{view_kind}'"
        ),
    )


def resolve_panel(
    store, events: EventService, panel: SpecPanel
) -> ResolvedPanel:
    """Resolve one spec panel against the store as it stands."""
    if panel.kind == "gap":
        return _gap_panel(panel, panel.gap_needed or "not available")
    if panel.kind == "forecast":
        resolved = resolve_forecast_panel(store, panel)
    elif panel.kind == "accuracy":
        resolved = resolve_accuracy_panel(store, panel)
    elif panel.kind == "sentiment":
        resolved = resolve_sentiment_panel(store, panel)
    elif panel.kind == "events":
        resolved = resolve_events_panel(store, events, panel)
    elif panel.kind == "scenario_diff":
        resolved = resolve_scenario_panel(store, panel)
    else:  # pragma: no cover - the pack gate refuses unknown kinds
        raise AssemblyError(f"unknown panel kind {panel.kind!r}")
    # Supersession against the ask-time bindings: bindings the
    # re-resolution replaced are named on the panel.
    prior = set(panel.binding_artefact_ids)
    current = set(resolved.artefact_ids)
    if prior and prior != current:
        resolved.superseded_from = sorted(prior - current)
    return resolved


def binding_ids_for(store, panel: SpecPanel) -> list[str]:
    """The artefacts a panel binds right now (ask time), without
    building figures — the spec records these as its ask-time
    bindings, and assembly names supersession against them."""
    if panel.kind == "forecast":
        head = head_forecast(
            store, panel.scope["commodity"], panel.scope["market"]
        )
        return [head.forecast_id] if head is not None else []
    if panel.kind == "accuracy":
        return [
            r.record_id
            for r in store.list_accuracy_records(
                panel.scope["commodity"], panel.scope["market"]
            )
        ]
    if panel.kind == "sentiment":
        indices = store.list_indices(panel.scope["commodity"])
        return [indices[-1].index_id] if indices else []
    if panel.kind == "events":
        return [
            e.event_id
            for e in store.list_market_events(panel.scope["commodity"])
        ]
    if panel.kind == "scenario_diff":
        if panel.scope.get("scenario_id"):
            run = store.get_scenario(panel.scope["scenario_id"])
            return [run.scenario_id] if run is not None else []
        adopted = next(
            (
                s
                for s in store.list_scenarios(
                    panel.scope["commodity"], panel.scope["market"]
                )
                if s.status == "adopted"
            ),
            None,
        )
        return [adopted.scenario_id] if adopted is not None else []
    return []


def compute_assembly_diff(
    previous: DashboardAssembly | None,
    panels: list[ResolvedPanel],
) -> list[AssemblyDiffEntry]:
    """The computed diff against the previous assembly of the
    same spec: panels that flipped between gap and rendered,
    bindings superseded, figures whose value changed."""
    if previous is None:
        return []
    entries: list[AssemblyDiffEntry] = []
    prior_panels = {p.panel_no: p for p in previous.panels}
    for panel in panels:
        prior = prior_panels.get(panel.panel_no)
        if prior is None:
            continue
        if prior.state != panel.state:
            entries.append(
                AssemblyDiffEntry(
                    kind="panel_state_changed",
                    panel_no=panel.panel_no,
                    panel_title=panel.title,
                    before=prior.state,
                    after=panel.state,
                )
            )
        prior_ids = set(prior.artefact_ids)
        current_ids = set(panel.artefact_ids)
        if prior_ids != current_ids:
            entries.append(
                AssemblyDiffEntry(
                    kind="binding_superseded",
                    panel_no=panel.panel_no,
                    panel_title=panel.title,
                    before=sorted(prior_ids),
                    after=sorted(current_ids),
                )
            )
        prior_figures = {f.key: f for f in prior.figures}
        for figure in panel.figures:
            before = prior_figures.get(figure.key)
            if before is not None and before.value != figure.value:
                entries.append(
                    AssemblyDiffEntry(
                        kind="figure_changed",
                        panel_no=panel.panel_no,
                        panel_title=panel.title,
                        figure_key=figure.key,
                        label=figure.label,
                        before=before.value,
                        after=figure.value,
                    )
                )
    return entries
