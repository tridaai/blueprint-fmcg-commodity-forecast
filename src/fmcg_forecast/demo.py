"""Demo: generate the dataset, load it, and print the planted checks.

Runs against a fresh demo SQLite file so the walkthrough always
shows the current generator. The checks printed here are the same
planted truths the eval gate grades with zero tolerance.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from fmcg_forecast.config import Settings
from fmcg_forecast.store import build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset


def _mean_price(store, commodity, market, start, end) -> float:
    rows = store.series(commodity, market, "modal_price", start, end)
    return sum(r.value for r in rows) / len(rows)


def main() -> int:
    settings = Settings.from_env()
    demo_db = Path("./data/demo-fmcg.db")
    if demo_db.exists():
        demo_db.unlink()
    store = build_store(str(demo_db))
    truth_store = build_truth_store(str(demo_db))
    state = load_dataset(store, truth_store, settings.dataset_seed)
    manifest = store.get_manifest()
    assert manifest is not None

    from fmcg_forecast.modelport import build_model_port
    from fmcg_forecast.sentiment.grading import build_sentiment_grading_store
    from fmcg_forecast.sentiment.load import load_sentiment_corpus
    from fmcg_forecast.sentiment.service import SentimentService

    grading_store = build_sentiment_grading_store(str(demo_db))
    load_sentiment_corpus(store, grading_store, settings.dataset_seed)
    sentiment = SentimentService(store, build_model_port(settings))
    pipeline = sentiment.run_pipeline()

    print(f"generator {manifest.generator_version} seed {manifest.seed}")
    print(f"history rows: {manifest.history_rows}  future (sealed truth) rows: {manifest.future_rows}")
    print(f"history digest: {manifest.history_digest[:16]}…")
    print("\nrows per commodity:")
    for commodity, count in store.row_counts().items():
        print(f"  {commodity:<14} {count}")

    def yoy_effect(commodity, market, start, post_end):
        def window_ratio(shift):
            pre = _mean_price(store, commodity, market, start - timedelta(days=25 + shift), start - timedelta(days=5 + shift))
            post = _mean_price(store, commodity, market, start + timedelta(days=5) - timedelta(days=shift), post_end - timedelta(days=shift))
            return post / pre

        return window_ratio(0) / window_ratio(365)

    tariff = next(e for e in manifest.events if e.kind == "tariff_shock")
    effect = yoy_effect("soybean", "indore", tariff.start_date, tariff.start_date + timedelta(days=20))
    print(f"\ntariff shock ({tariff.event_id}): soybean/indore seasonally-matched price effect "
          f"x{effect:.3f} (planted peak +16% decaying over 45 days)")

    ban = next(e for e in manifest.events if e.kind == "export_ban")
    effect = yoy_effect("basmati_rice", "delhi_khari_baoli", ban.start_date, ban.end_date - timedelta(days=10))
    print(f"export ban ({ban.event_id}): basmati/delhi seasonally-matched price effect "
          f"x{effect:.3f} (planted -11% for the window)")

    harvest = store.series("wheat", "delhi_khari_baoli", "arrivals", date(2024, 4, 1), date(2024, 6, 30))
    lean = store.series("wheat", "delhi_khari_baoli", "arrivals", date(2024, 10, 1), date(2024, 12, 31))
    h = sum(r.value for r in harvest) / len(harvest)
    l = sum(r.value for r in lean) / len(lean)
    print(f"seasonality: wheat arrivals harvest season {h:.0f}/day vs lean {l:.0f}/day (x{h / l:.2f})")

    coffee = next(c for c in manifest.commodities if c.commodity == "coffee")
    disruption_rows = store.series(
        "coffee", "bengaluru", "modal_price",
        manifest.coffee_disruption_start, manifest.coffee_disruption_end,
    )
    print(f"coffee (thin data): {coffee.history_days_per_market} reporting days, "
          f"{coffee.history_rows} rows, missing drivers named: {coffee.missing_drivers}, "
          f"rows inside the planted disruption window: {len(disruption_rows)}")

    print("\n--- forecast engine (R2): computed, decomposed, gated ---")
    from fmcg_forecast.forecast.service import ForecastService

    service = ForecastService(
        store,
        build_model_port(settings),
        sentiment_provider=sentiment.forecast_input,
        sentiment_claim_verifier=sentiment.verify_claims,
    )
    wheat = service.run_forecast("wheat", "delhi_khari_baoli")
    print(f"wheat/delhi forecast {wheat.forecast_id} as of {wheat.as_of} (status: {wheat.status})")
    for summary in wheat.horizons_summary:
        drivers = ", ".join(
            f"{name} {value:+.2f}" for name, value in summary.contributions.items()
        )
        print(f"  {summary.horizon_days:>2}d {summary.forecast_date}: baseline {summary.baseline:.2f} "
              f"-> P50 {summary.p50:.2f} (P10 {summary.p10:.2f} / P90 {summary.p90:.2f}); {drivers}")
    problems = service.verify_stored(wheat.forecast_id)
    print(f"  re-performance verification of the stored artefact: {len(problems)} problems")
    commentary = service.draft_commentary(wheat.forecast_id)
    print(f"  commentary (model profile {commentary.model_profile}, figures verified):")
    print(f"    {commentary.text}")
    approval = service.approve(
        wheat.forecast_id, approver="r.menon", role="Head of Trading Desk",
        decided_on=date(2026, 1, 2),
    )
    print(f"  approval act {approval.approval_id}: {approval.approver} ({approval.role}) "
          f"made it the official view on {approval.decided_on}")

    coffee_fc = service.run_forecast("coffee", "bengaluru")
    h30 = next(s for s in coffee_fc.horizons_summary if s.horizon_days == 30)
    print(f"coffee/bengaluru forecast {coffee_fc.forecast_id}: missing drivers named "
          f"{coffee_fc.missing_drivers}; sparsity widening x{coffee_fc.method.sparsity.multiplier} "
          f"(wheat x{wheat.method.sparsity.multiplier}); 30d band {h30.p10:.2f}..{h30.p90:.2f} "
          f"around P50 {h30.p50:.2f}")
    print(f"  note: those forecasts were run before any backtest existed — their "
          f"accuracy reads '{coffee_fc.accuracy.state}', named on the artefact")

    print("\n--- backtesting + the accuracy ledger (R3): every forecast carries its measured accuracy ---")
    from fmcg_forecast.backtest.harness import run_all

    report, records = run_all(store)
    print(f"harness: {report.engine_runs} engine runs at monthly 2025 origins, "
          f"{report.results_stored} results stored, {len(report.skipped)} origins skipped")
    for skip in report.skipped:
        print(f"  skipped {skip['commodity']}/{skip['market']} @ {skip['origin']}: "
              f"{skip['reason'].split(';')[0]}")
    print(f"ledger: {len(records)} accuracy records (14 series x 3 horizons), pooled "
          f"over the most recent 6 origins, degraded bar = pooled MAPE above 5.0%")
    for record in records:
        if record.commodity in ("wheat", "chili", "coffee"):
            flag = "  <-- DEGRADED" if record.degraded else ""
            print(f"  {record.commodity}/{record.market} {record.horizon_days:>2}d: "
                  f"MAPE {record.mape:.2f}%  bias {record.bias:+.2f}  coverage "
                  f"{record.coverage:.2f}  over {record.n_results} origins{flag}")

    chili = service.run_forecast("chili", "guntur")
    print(f"\nchili/guntur forecast {chili.forecast_id} carries accuracy: {chili.accuracy.state}")
    print(f"  {chili.accuracy.note}")
    chili_commentary = service.draft_commentary(chili.forecast_id)
    print(f"  commentary states it too: 'Backtest accuracy state: degraded' "
          f"in text -> {'Backtest accuracy state: degraded' in chili_commentary.text}")
    wheat2 = service.run_forecast("wheat", "indore")
    print(f"wheat/indore forecast {wheat2.forecast_id} carries accuracy: "
          f"{wheat2.accuracy.state} (a fresh run pins the ledger as it now stands; "
          f"the pre-backtest run above keeps its unmeasured snapshot)")

    print("\n--- sentiment (R4, Law 3): extracted, indexed, cited — never asserted ---")
    print(f"corpus: {pipeline['items']} planted items -> {pipeline['extractions_new']} "
          f"extractions ({pipeline['unclassified']} unclassified, reasons on record), "
          f"{pipeline['indices_new']} weekly indices")
    graded = sentiment_grading_check(sentiment, grading_store)
    print(f"extraction vs planted intent: {graded} disagreements across the whole corpus")
    wheat_line = next(l for l in wheat.lines if l.driver == "sentiment")
    print(f"wheat forecast sentiment line: {wheat_line.input_summary['state']}, "
          f"coefficient {wheat_line.coefficient:+.4f} on the weekly index, latest week "
          f"{wheat_line.input_summary['latest_index_value']:+.4f} citing "
          f"{', '.join(wheat_line.input_summary['cited_item_ids'])}")
    reading = next(
        (s for s in commentary.text.split('. ') if 'Sentiment reading' in s), None
    )
    print(f"  commentary carries the reading with its items: {reading}")
    coffee_line = next(l for l in coffee_fc.lines if l.driver == "sentiment")
    print(f"coffee forecast sentiment line: {coffee_line.input_summary['state']} — "
          f"{coffee_line.input_summary['reason']}")
    stored = sentiment.verify_stored()
    print(f"  re-performance of every stored extraction and index: "
          f"{len(stored['problems'])} problems")

    print("\n--- event registry (R5, Law 4): declared shocks, measured claims, separate lines ---")
    from fmcg_forecast.events.service import EventService

    events = EventService(store)
    seeded = events.seed_historical(manifest)
    print(f"historical seeding from the manifest: {len(seeded['seeded'])} planted "
          f"shocks registered ({seeded['total_on_record']} on record)")
    for event in events.list_events():
        verdict = events.verify_event(event.event_id)
        print(f"  {event.event_class:<19} {event.commodity:<13} "
              f"{event.window_start}..{event.window_end} claimed "
              f"{event.transmission.peak_log_price_effect:+.3f} log via "
              f"{event.transmission.channel} -> {verdict.status}"
              + (f" (measured x{verdict.measured_ratio:.3f})"
                 if verdict.measured_ratio is not None else ""))
    tariff_event = next(
        e for e in events.list_events() if e.source_record_id == "EVT-2025-TARIFF-SOYBEAN"
    )
    impact = events.impact(tariff_event.event_id, "indore")
    print(f"  what-happened view, tariff at indore: {len(impact.days)} observed "
          f"days against the no-event baseline; mean effect "
          f"x{impact.mean_price_ratio:.3f}, peak log effect "
          f"{impact.peak_log_effect:+.3f}")

    wired = ForecastService(
        store,
        build_model_port(settings),
        sentiment_provider=sentiment.forecast_input,
        sentiment_claim_verifier=sentiment.verify_claims,
        events_provider=events.forecast_adjustments,
    )
    clear = wired.run_forecast("soybean", "indore")
    clear_view = wired.events_view(clear.forecast_id)
    print(f"soybean/indore forecast {clear.forecast_id} before any live "
          f"declaration: events state '{clear_view['state']}' (the 2025 "
          "tariff's window and decay tail end months before this run)")
    declared = events.register_event(
        event_class="tariff_change",
        commodity="soybean",
        window_start=date(2026, 2, 1),
        window_end=date(2026, 2, 28),
        channel="import_flow",
        peak_log_price_effect=0.08,
        basis="announced_measure",
        basis_detail="Import duty on oilseeds raised by 10 percentage "
                     "points in a ministry notification; the peak is "
                     "the announced measure's import-parity effect as "
                     "stated by the desk",
        decay_days=20,
        description="Import tariff increase on oilseeds announced for "
                    "February; domestic prices expected to step up "
                    "through import parity",
        declared_by="a.sharma",
        declared_on=date(2026, 1, 2),
    )
    shocked = wired.run_forecast("soybean", "indore")
    shocked_view = wired.events_view(shocked.forecast_id)
    entry = shocked_view["events"][0]
    print(f"declared {declared.event_id} (tariff_change, +0.08 log, "
          f"Feb 2026) -> forecast {shocked.forecast_id} is "
          f"'{shocked_view['state']}': the event is its own line "
          f"(peak daily contribution "
          f"{max(entry['contribution_path_inr']):+.2f} INR, intervals "
          f"widened x{shocked_view['interval_widening']} on shocked days)")
    problems = wired.verify_stored(shocked.forecast_id)
    print(f"  re-performance of the shocked artefact (decomposition + "
          f"per-event lines): {len(problems)} problems")

    print("\n--- scenario studio (R6, Law 5): bounded levers, pinned forks, a human adoption gate ---")
    from fmcg_forecast.scenarios.service import (
        ScenarioParseError,
        ScenarioService,
    )

    scenarios = ScenarioService(
        store,
        build_model_port(settings),
        wired,
        events,
        sentiment_provider=sentiment.forecast_input,
    )
    what_if = "what if arrivals drop 10% and the tariff stays another month?"
    request = scenarios.parse_request(
        "soybean", "indore", what_if, base_forecast_id=shocked.forecast_id
    )
    print(f"typed what-if: {what_if!r}")
    print(f"  parsed request {request.request_id} under pack "
          f"{request.pack_version} (model profile {request.model_profile}):")
    for lever in request.levers:
        detail = (
            f"{lever.value:+g}" if lever.value is not None else
            f"event {lever.event_id} +{lever.extra_days} days"
        )
        print(f"    {lever.lever:<18} {detail}   <- clause {lever.clause!r}")
    run = scenarios.run_scenario(
        request.request_id, shocked.forecast_id, author="a.sharma",
        created_on=date(2026, 1, 3),
    )
    for shift in run.shifts:
        print(f"  lever became a driver-input shift: {shift.driver} "
              f"{shift.mode} {shift.value:+.4f} (from "
              f"{shift.basis_stats})")
    extended = run.scenario_events[0]
    print(f"  the tariff's prolongation is a scenario-local event "
          f"{extended.event_id}: window now ends {extended.window_end} "
          f"(the registry record is untouched)")
    diff = scenarios.diff(run.scenario_id)
    print(f"  fork {run.fork_forecast_id} vs base {shocked.forecast_id}: "
          f"P50 difference at 7/30/90 days "
          f"{diff.at_horizons['7']:+.2f} / {diff.at_horizons['30']:+.2f} / "
          f"{diff.at_horizons['90']:+.2f} INR; driver totals "
          + ", ".join(f"{k} {v:+.2f}" for k, v in diff.driver_totals.items())
          + f"; events {diff.events_total:+.2f}; whole-horizon "
          f"{diff.p50_total:+.2f} — the parts sum to the total exactly")
    print(f"  re-performance of the stored run: "
          f"{len(scenarios.verify_stored(run.scenario_id))} problems")
    print(f"  before any act, the desk's adopted view for soybean/indore: "
          f"{scenarios.adopted_view('soybean', 'indore')['state']} — the "
          f"scenario reads as '{scenarios.scenario_view(run.scenario_id)['view_kind']}'")
    adoption = scenarios.adopt(
        run.scenario_id, adopter="r.menon", role="Head of Trading Desk",
        decided_on=date(2026, 1, 4),
    )
    adopted = scenarios.adopted_view("soybean", "indore")
    print(f"  adoption act {adoption.adoption_id}: {adoption.adopter} "
          f"({adoption.role}) adopted it on {adoption.decided_on}; the "
          f"adopted view now reads '{adopted['scenario']['view_kind']}' "
          f"and the base forecast keeps its own status "
          f"({wired.get_forecast(shocked.forecast_id).status})")
    try:
        scenarios.parse_request(
            "soybean", "indore",
            "what if the monsoon fails completely?",
            base_forecast_id=shocked.forecast_id,
        )
    except ScenarioParseError as refusal:
        print(f"  an out-of-catalogue what-if is refused, not improvised: "
              f"clause {refusal.clause!r} — {refusal.reason}")

    print("\n--- prompt-to-dashboard (R7, Law 6): a stated spec, verified pages, a provenance appendix, the morning board ---")
    from fmcg_forecast.dashboards.service import DashboardService

    dashboards = DashboardService(
        store, build_model_port(settings), events, sentiment
    )
    prompt = (
        "wheat forecast at delhi and soybean sentiment and declared "
        "events for soybean and the coffee forecast and the adopted "
        "scenario for soybean at indore and show me the coffee stock position"
    )
    spec = dashboards.ask(prompt, asked_by="a.sharma", created_on=date(2026, 1, 5))
    print(f"prompt: {prompt!r}")
    print(f"  stated spec {spec.spec_id} under dashboard pack "
          f"{spec.pack_version} (model profile {spec.model_profile}):")
    for panel in spec.panels:
        if panel.gap_needed:
            print(f"    panel {panel.panel_no}: NAMED GAP — {panel.gap_needed}")
        else:
            print(f"    panel {panel.panel_no}: {panel.kind:<14} "
                  f"{panel.scope} bound at ask time to "
                  f"{panel.binding_artefact_ids}")
    view = dashboards.save_view(
        spec.spec_id, "morning desk", saved_by="a.sharma",
        saved_on=date(2026, 1, 5),
    )
    print(f"  saved as view {view.view_id} ({view.name!r}) — a name "
          f"pointing at the spec, re-runnable against fresh data")
    assembly = dashboards.assemble(spec.spec_id, assembled_on=date(2026, 1, 5))
    rendered = [p for p in assembly.panels if p.state == "rendered"]
    gaps = [p for p in assembly.panels if p.state == "gap"]
    figures = sum(len(p.figures) for p in rendered)
    print(f"  assembly {assembly.assembly_id}: {len(rendered)} panels "
          f"rendered ({figures} figures), {len(gaps)} named gap(s); "
          f"verified before it was stored — "
          f"{len(dashboards.verify_stored(assembly.assembly_id))} problems; "
          f"the page is {len(assembly.html)} bytes of static HTML")
    appendix = dashboards.appendix(assembly.assembly_id)
    walks = [
        (f["key"], f["lineage"])
        for p in appendix["panels"] for f in p["figures"]
    ]
    terminal = sum(
        1 for _, lineage in walks
        if any(fact["kind"] in ("observation_series", "sentiment_item",
                                "event_declaration", "manifest")
               for fact in lineage)
    )
    print(f"  provenance appendix: {len(walks)} figures, every one "
          f"walked to a stored fact ({terminal}/{len(walks)} terminate "
          f"at observations, items, declarations or the manifest) — "
          f"e.g. figure {walks[0][0]!r} traces through "
          f"{[fact['kind'] + ':' + fact['ref'] for fact in walks[0][1][:2]]} …")
    again = dashboards.assemble(spec.spec_id, assembled_on=date(2026, 1, 6))
    print(f"  re-assembling against unchanged data returns the same "
          f"artefact ({again.assembly_id == assembly.assembly_id}); a "
          f"re-run after new forecasts land computes the diff instead")
    board = dashboards.board(date(2026, 2, 15))
    print(f"  morning board {board.board_id} for {board.board_date} — "
          f"exceptions first, every row an artefact:")
    for row in board.rows:
        print(f"    [{row.kind:<15}] {row.headline}  ({row.artefact_id})")
    print("\n--- buy signals & coverage planning (R8, F20-PO2/PO3): a computed call per series, the desk's own plan priced ---")
    from fmcg_forecast.planning.models import PlanLine
    from fmcg_forecast.planning.service import PlanningService
    from fmcg_forecast.signals.service import SignalService

    signals = SignalService(store)
    planning = PlanningService(store, signals)
    for commodity, market in (
        ("soybean", "indore"),
        ("wheat", "delhi_khari_baoli"),
        ("chili", "guntur"),
    ):
        signal = signals.compute_for_series(commodity, market)
        print(f"  signal {signal.signal_id} — {commodity} at {market}: "
              f"{signal.value} (base {signal.base_value})")
        for line in signal.reasoning:
            print(f"      {line}")
    plan = planning.enter_plan(
        commodity="soybean", market="indore", entered_by="r.menon",
        entered_on=date(2026, 1, 5), opening_stock_tonnes=120.0,
        lines=[
            PlanLine(month=date(2026, 1, 1), required_tonnes=300.0),
            PlanLine(month=date(2026, 2, 1), required_tonnes=300.0),
            PlanLine(month=date(2026, 3, 1), required_tonnes=280.0),
        ],
        note="Q1 soybean requirement, entered by the desk",
    )
    print(f"  requirement plan {plan.plan_id} — desk-entered by "
          f"{plan.entered_by} (origin: {plan.origin}; the desk's own "
          f"statement, never market data)")
    assessment = planning.assess(plan.plan_id)
    print(f"  assessment {assessment.assessment_id} on the official "
          f"forecast {assessment.forecast_id}: coverage "
          f"{assessment.coverage_days} days, stockout "
          f"{assessment.stockout_month}, uncovered "
          f"{assessment.total_uncovered_tonnes} t, exposure "
          f"INR {assessment.total_exposure_inr:,.2f}")
    for option in assessment.options:
        print(f"    rank {option.rank}: {option.name:<13} expected "
              f"INR {option.cost_at_p50_inr:,.2f} / adverse "
              f"INR {option.cost_at_p90_inr:,.2f}")
    scenario_assessment = planning.assess(
        plan.plan_id, basis="adopted_scenario"
    )
    print(f"  the same plan on the adopted scenario "
          f"{scenario_assessment.scenario_id} (badged "
          f"scenario-based, never blended): exposure "
          f"INR {scenario_assessment.total_exposure_inr:,.2f}")
    board = dashboards.board(date(2026, 2, 15))
    signal_rows = [r for r in board.rows if r.kind == "signal"]
    print(f"  the morning board now carries a signals section — "
          f"{len(signal_rows)} actionable row(s):")
    for row in signal_rows:
        print(f"    [{row.kind:<15}] {row.headline}  ({row.artefact_id})")
    print(f"sealed truth rows stored: {truth_store.count()} (readable only via the truth store)")
    return 0


def sentiment_grading_check(sentiment, grading_store) -> int:
    """Demo-side grading: stored extractions vs the planted intent.

    Lives in the demo (a load-path surface) — the scoring code
    never sees the intent; only surfaces like this one, the tests
    and the eval gate may compare against it.
    """
    from fmcg_forecast.sentiment.corpus import expected_reading

    disagreements = 0
    for extraction in sentiment.list_extractions():
        intent = grading_store.get_intent(extraction.item_id)
        expected = expected_reading(intent)
        if extraction.status != expected["status"]:
            disagreements += 1
        elif expected["status"] == "classified" and (
            extraction.direction != expected["direction"]
            or extraction.strength != expected["strength"]
            or extraction.score != expected["score"]
            or extraction.aspects != expected["aspects"]
        ):
            disagreements += 1
    return disagreements


if __name__ == "__main__":
    raise SystemExit(main())
