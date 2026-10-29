"""Round 8 tests: the signal pack and its decision table
(hand-computed fixtures exact: rising / falling / degraded /
in-event-window / unmeasured), signal re-performance and tamper
detection, the coverage planner (hand-computed exposure and
option ranking exact, beyond-horizon months named never valued,
entry refusals), provenance separation (desk-entered figures
never in market provenance), scenario-basis assessments, the
board's signals section, API + CLI surfaces, truth isolation.
"""

from __future__ import annotations

import ast
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.api import create_app
from fmcg_forecast.backtest.harness import run_all as run_backtest_harness
from fmcg_forecast.backtest.pack import load_accuracy_pack
from fmcg_forecast.dashboards.board import build_board
from fmcg_forecast.dashboards.pack import load_dashboard_pack
from fmcg_forecast.dashboards.service import DashboardService
from fmcg_forecast.events.service import EventService
from fmcg_forecast.forecast.engine import forecast_content_id
from fmcg_forecast.forecast.models import (
    ATTRIBUTION_ORDER,
    AccuracyAttachment,
    BaselineMethod,
    Forecast,
    ForecastDay,
    ForecastMethod,
    HorizonAccuracy,
    HorizonSummary,
    ResidualMethod,
    SparsityMethod,
)
from fmcg_forecast.forecast.service import ForecastService
from fmcg_forecast.modelport import OfflineModel
from fmcg_forecast.models import Observation
from fmcg_forecast.planning import cli as planning_cli
from fmcg_forecast.planning.models import PlanLine
from fmcg_forecast.planning.pack import load_planning_pack
from fmcg_forecast.planning.service import (
    PlanningService,
    PlanningStateError,
    PlanningValidationError,
)
from fmcg_forecast.planning.verify import verify_assessment, verify_plan
from fmcg_forecast.scenarios.service import ScenarioService
from fmcg_forecast.sentiment.grading import build_sentiment_grading_store
from fmcg_forecast.sentiment.load import load_sentiment_corpus
from fmcg_forecast.sentiment.service import SentimentService
from fmcg_forecast.signals import cli as signals_cli
from fmcg_forecast.signals.pack import load_signal_pack
from fmcg_forecast.signals.service import SignalService
from fmcg_forecast.signals.verify import verify_signal
from fmcg_forecast.store import build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset

SEED = 20261027
HISTORY_END = date(2025, 12, 31)
BOARD_DATE = date(2026, 2, 15)


# --- hand-built forecast fixtures --------------------------------------


def _attachment(state: str) -> AccuracyAttachment:
    if state == "unmeasured":
        return AccuracyAttachment(
            state="unmeasured",
            pack_version=None,
            per_horizon=[
                HorizonAccuracy(
                    horizon_days=h, state="unmeasured", record_id=None,
                    n_origins=0, mae=None, mape=None, bias=None,
                    coverage=None,
                )
                for h in (7, 30, 90)
            ],
            note="no backtest coverage yet",
        )
    slices = []
    for h in (7, 30, 90):
        degraded = state == "degraded" and h == 30
        slices.append(
            HorizonAccuracy(
                horizon_days=h,
                state="degraded" if degraded else "measured",
                record_id=f"ACC-FIX-{h}",
                n_origins=6,
                mae=42.0,
                mape=7.5 if degraded else 2.0,
                bias=1.0,
                coverage=0.9,
            )
        )
    return AccuracyAttachment(
        state=state,  # type: ignore[arg-type]
        pack_version="2026.10.1",
        per_horizon=slices,
        note="fixture attachment",
    )


def _fixture_forecast(
    commodity: str,
    market: str,
    p50: float,
    p10: float,
    p90: float,
    accuracy: AccuracyAttachment | None,
) -> Forecast:
    days = [
        ForecastDay(
            forecast_date=HISTORY_END + timedelta(days=i + 1),
            baseline=p50,
            contributions={},
            events_adjustment=0.0,
            p10=p10,
            p50=p50,
            p90=p90,
        )
        for i in range(90)
    ]
    summaries = [
        HorizonSummary(
            horizon_days=h,
            forecast_date=days[h - 1].forecast_date,
            baseline=p50,
            contributions={},
            events_adjustment=0.0,
            p10=p10,
            p50=p50,
            p90=p90,
        )
        for h in (7, 30, 90)
    ]
    method = ForecastMethod(
        engine_version="fixture-1",
        baseline=BaselineMethod(
            intercept=0.0, trend_per_year=0.0, seasonal_sin=0.0,
            seasonal_cos=0.0, anchor_date=HISTORY_END, n_obs=300,
        ),
        drivers={},
        residuals=ResidualMethod(
            sigma=0.01, rho=0.0, q10=-0.01, q90=0.01, window_obs=300
        ),
        sparsity=SparsityMethod(
            observed_days=300, calendar_days=300, multiplier=1.0
        ),
        attribution_order=list(ATTRIBUTION_ORDER),
    )
    forecast = Forecast(
        forecast_id="FCST-pending",
        commodity=commodity,
        market=market,
        as_of=HISTORY_END,
        engine_version="fixture-1",
        method=method,
        days=days,
        lines=[],
        horizons_summary=summaries,
        missing_drivers=[],
        accuracy=accuracy,
    )
    return forecast.model_copy(
        update={"forecast_id": forecast_content_id(forecast)}
    )


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    """A bare store: hand-built forecasts, spots, one declared event."""
    db = str(tmp_path_factory.mktemp("r8fix") / "fixtures.db")
    store = build_store(db)

    def add(commodity, market, spot, p50, p10, p90, accuracy):
        store.insert_observations(
            [
                Observation(
                    commodity=commodity, market=market,
                    obs_date=HISTORY_END, driver="modal_price", value=spot,
                )
            ]
        )
        forecast = _fixture_forecast(commodity, market, p50, p10, p90, accuracy)
        store.insert_forecast(forecast)
        return forecast

    rising = add("wheat", "delhi_khari_baoli", 2000.0, 2100.0, 2010.0, 2190.0,
                 _attachment("measured"))
    falling = add("soybean", "indore", 2000.0, 1900.0, 1810.0, 1990.0,
                  _attachment("measured"))
    degraded = add("chili", "guntur", 2000.0, 2100.0, 2010.0, 2190.0,
                   _attachment("degraded"))
    in_event = add("cumin", "unjha", 2000.0, 2010.0, 1950.0, 2070.0,
                   _attachment("measured"))
    unmeasured = add("groundnut", "rajkot", 2000.0, 2100.0, 2010.0, 2190.0,
                     None)
    flat = add("basmati_rice", "karnal", 2000.0, 2000.0, 1800.0, 2200.0,
               _attachment("measured"))

    events = EventService(store)
    event = events.register_event(
        event_class="tariff_change",
        commodity="cumin",
        window_start=date(2026, 1, 10),
        window_end=date(2026, 1, 20),
        channel="import_flow",
        peak_log_price_effect=0.08,
        basis="announced_measure",
        basis_detail="Import duty change notified for January",
        decay_days=10,
        description="Tariff change overlapping the cumin horizon",
        declared_by="a.sharma",
        declared_on=date(2026, 1, 2),
    )
    return {
        "db": db,
        "store": store,
        "rising": rising,
        "falling": falling,
        "degraded": degraded,
        "in_event": in_event,
        "unmeasured": unmeasured,
        "flat": flat,
        "event": event,
        "signals": SignalService(store),
        "planning": PlanningService(store),
    }


# --- the packs ------------------------------------------------------------


def test_signal_pack_states_every_threshold():
    pack = load_signal_pack()
    assert pack.version == "2026.10.1"
    assert pack.horizon_days == 30
    assert pack.rise_threshold_pct == 2.0
    assert pack.fall_threshold_pct == -2.0
    assert pack.wide_band_threshold_pct == 25.0
    assert pack.degraded_cap == "phased"
    assert pack.unmeasured_cap == "phased"
    with pytest.raises(ValueError):
        load_signal_pack("1900.01.1")


def test_planning_pack_states_options_and_ranking():
    pack = load_planning_pack()
    assert pack.version == "2026.10.1"
    assert pack.quintals_per_tonne == 10
    assert [o.name for o in pack.options] == [
        "cover_now", "cover_staged", "cover_phased",
    ]
    assert "Expected cost" in pack.ranking_rule
    assert "never enters the ranking" in pack.signal_rule


# --- signal fixtures, hand-computed ---------------------------------------


def test_signal_fixture_rising_is_buy_now(fixtures):
    signal = fixtures["signals"].compute_for_forecast(fixtures["rising"])
    assert signal.drift_pct == 5.0
    assert signal.band_width_pct == 8.5714
    assert signal.base_value == "buy_now"
    assert signal.value == "buy_now"
    assert signal.caps_applied == []
    assert signal.accuracy_state == "measured"
    assert signal.scope_note.startswith("signal only")
    assert signal.reasoning[-1] == signal.scope_note
    assert verify_signal(fixtures["store"], signal) == []


def test_signal_fixture_falling_is_wait(fixtures):
    signal = fixtures["signals"].compute_for_forecast(fixtures["falling"])
    assert signal.drift_pct == -5.0
    assert signal.base_value == "wait"
    assert signal.value == "wait"
    assert verify_signal(fixtures["store"], signal) == []


def test_signal_fixture_degraded_is_capped(fixtures):
    signal = fixtures["signals"].compute_for_forecast(fixtures["degraded"])
    assert signal.base_value == "buy_now"
    assert signal.value == "phased"
    assert signal.caps_applied == ["degraded_accuracy"]
    assert signal.degraded_horizons == [30]
    assert any("degraded_accuracy" in line for line in signal.reasoning)
    assert verify_signal(fixtures["store"], signal) == []


def test_signal_fixture_in_event_window_is_phased_and_named(fixtures):
    signal = fixtures["signals"].compute_for_forecast(fixtures["in_event"])
    assert signal.drift_pct == 0.5
    assert signal.base_value == "phased"
    assert signal.value == "phased"
    assert [e.event_id for e in signal.active_events] == [
        fixtures["event"].event_id
    ]
    assert any(
        fixtures["event"].event_id in line for line in signal.reasoning
    )
    assert verify_signal(fixtures["store"], signal) == []


def test_signal_fixture_unmeasured_is_capped(fixtures):
    signal = fixtures["signals"].compute_for_forecast(fixtures["unmeasured"])
    assert signal.accuracy_state == "unmeasured"
    assert signal.base_value == "buy_now"
    assert signal.value == "phased"
    assert signal.caps_applied == ["unmeasured_accuracy"]
    assert verify_signal(fixtures["store"], signal) == []


def test_signal_tamper_is_detected(fixtures):
    store = fixtures["store"]
    signal = fixtures["signals"].compute_for_forecast(fixtures["degraded"])
    conn = sqlite3.connect(fixtures["db"])
    payload = json.loads(
        conn.execute(
            "SELECT payload FROM buy_signals WHERE signal_id = ?",
            (signal.signal_id,),
        ).fetchone()[0]
    )
    payload["value"] = "buy_now"  # dress the capped signal up as strong
    conn.execute(
        "UPDATE buy_signals SET payload = ? WHERE signal_id = ?",
        (json.dumps(payload), signal.signal_id),
    )
    conn.commit()
    conn.close()
    tampered = store.get_buy_signal(signal.signal_id)
    problems = verify_signal(store, tampered)
    assert any("content id mismatch" in p for p in problems)
    assert any("hard rule breached" in p for p in problems)


# --- planning fixtures, hand-computed --------------------------------------


def _rice_plan(fixtures, with_april: bool = False):
    lines = [
        PlanLine(month=date(2026, 1, 1), required_tonnes=300.0),
        PlanLine(month=date(2026, 2, 1), required_tonnes=300.0),
        PlanLine(month=date(2026, 3, 1), required_tonnes=300.0),
    ]
    if with_april:
        lines.append(PlanLine(month=date(2026, 4, 1), required_tonnes=100.0))
    return fixtures["planning"].enter_plan(
        commodity="basmati_rice",
        market="karnal",
        entered_by="r.menon",
        entered_on=date(2026, 1, 2),
        opening_stock_tonnes=100.0,
        lines=lines,
        note="Q1 requirement",
    )


def test_planning_fixture_arithmetic_is_exact(fixtures):
    planning = fixtures["planning"]
    plan = _rice_plan(fixtures)
    assert plan.origin == "desk_entered"
    assert verify_plan(plan) == []
    assessment = planning.assess(plan.plan_id)
    assert assessment.coverage_days == 10.0
    assert assessment.stockout_month == date(2026, 1, 1)
    assert [m.uncovered_tonnes for m in assessment.months] == [
        200.0, 300.0, 300.0,
    ]
    assert [m.exposure_inr for m in assessment.months] == [
        4_000_000.0, 6_000_000.0, 6_000_000.0,
    ]
    assert assessment.total_uncovered_tonnes == 800.0
    assert assessment.total_exposure_inr == 16_000_000.0
    assert assessment.unvalued_months == []
    assert assessment.signal_value == "wait"
    ranked = [(o.name, o.rank) for o in assessment.options]
    assert ranked == [
        ("cover_now", 1), ("cover_staged", 2), ("cover_phased", 3),
    ]
    by_name = {o.name: o for o in assessment.options}
    assert by_name["cover_now"].cost_at_p50_inr == 16_000_000.0
    assert by_name["cover_now"].cost_at_p90_inr == 16_000_000.0
    assert by_name["cover_staged"].cost_at_p50_inr == 16_000_000.0
    assert by_name["cover_staged"].cost_at_p90_inr == 17_200_000.0
    assert by_name["cover_phased"].cost_at_p50_inr == 16_000_000.0
    assert by_name["cover_phased"].cost_at_p90_inr == 17_600_000.0
    # the signal is wait: cover_now carries the caution, the ranking
    # still follows the pack's criteria alone
    assert any(
        "against the signal" in note
        for note in by_name["cover_now"].notes
    )
    assert verify_assessment(fixtures["store"], assessment) == []


def test_planning_beyond_horizon_month_is_named_never_valued(fixtures):
    planning = fixtures["planning"]
    plan = _rice_plan(fixtures, with_april=True)
    assessment = planning.assess(plan.plan_id)
    assert assessment.coverage_days == 12.0
    assert assessment.unvalued_months == [date(2026, 4, 1)]
    april = assessment.months[-1]
    assert april.price_state == "beyond_horizon"
    assert april.mean_p50_inr is None
    assert april.exposure_inr is None
    assert april.uncovered_tonnes == 100.0
    # the valued months are untouched by the extra line
    assert assessment.total_exposure_inr == 16_000_000.0
    assert verify_assessment(fixtures["store"], assessment) == []


def test_plan_entry_refusals(fixtures):
    planning = fixtures["planning"]
    good = [PlanLine(month=date(2026, 1, 1), required_tonnes=10.0)]
    with pytest.raises(PlanningValidationError):
        planning.enter_plan("basmati_rice", "karnal", "tbd",
                            date(2026, 1, 2), 0.0, good)
    with pytest.raises(PlanningValidationError):
        planning.enter_plan("basmati_rice", "nowhere", "r.menon",
                            date(2026, 1, 2), 0.0, good)
    with pytest.raises(PlanningValidationError):
        planning.enter_plan(
            "basmati_rice", "karnal", "r.menon", date(2026, 1, 2), 0.0,
            [PlanLine(month=date(2026, 1, 15), required_tonnes=10.0)],
        )
    with pytest.raises(PlanningValidationError):
        planning.enter_plan(
            "basmati_rice", "karnal", "r.menon", date(2026, 1, 2), 0.0,
            good + good,
        )
    with pytest.raises(PlanningValidationError):
        planning.enter_plan(
            "basmati_rice", "karnal", "r.menon", date(2026, 1, 2), 0.0,
            [PlanLine(month=date(2026, 1, 1), required_tonnes=0.0)],
        )
    with pytest.raises(PlanningValidationError):
        planning.enter_plan("basmati_rice", "karnal", "r.menon",
                            date(2026, 1, 2), -5.0, good)


def test_assessment_tamper_is_detected(fixtures):
    planning = fixtures["planning"]
    plan = _rice_plan(fixtures)
    assessment = planning.assess(plan.plan_id)
    conn = sqlite3.connect(fixtures["db"])
    payload = json.loads(
        conn.execute(
            "SELECT payload FROM coverage_assessments "
            "WHERE assessment_id = ?",
            (assessment.assessment_id,),
        ).fetchone()[0]
    )
    payload["total_exposure_inr"] += 1.0
    conn.execute(
        "UPDATE coverage_assessments SET payload = ? "
        "WHERE assessment_id = ?",
        (json.dumps(payload), assessment.assessment_id),
    )
    conn.commit()
    conn.close()
    tampered = fixtures["store"].get_coverage_assessment(
        assessment.assessment_id
    )
    problems = verify_assessment(fixtures["store"], tampered)
    assert any("content id mismatch" in p for p in problems)
    assert any("total_exposure_inr" in p for p in problems)


def test_provenance_separation_on_assessment_figures(fixtures):
    planning = fixtures["planning"]
    assessment = planning.assess(_rice_plan(fixtures).plan_id)
    for figure in assessment.figures:
        kinds = [fact.kind for fact in figure.lineage]
        if figure.basis == "desk":
            assert kinds == ["desk_entered"]
            assert figure.lineage[0].source == "desk-entered by r.menon"
        elif figure.basis == "market":
            assert "desk_entered" not in kinds
        else:
            assert kinds.count("desk_entered") == 1


# --- the full pipeline world -------------------------------------------------


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db = str(tmp_path_factory.mktemp("r8") / "test.db")
    store = build_store(db)
    truth = build_truth_store(db)
    load_dataset(store, truth, SEED)
    manifest = store.get_manifest()
    grading = build_sentiment_grading_store(db)
    load_sentiment_corpus(store, grading, SEED)
    model = OfflineModel()
    sentiment = SentimentService(store, model)
    sentiment.run_pipeline()
    events = EventService(store)
    events.seed_historical(manifest)
    events.register_event(
        event_class="tariff_change",
        commodity="soybean",
        window_start=date(2026, 2, 1),
        window_end=date(2026, 2, 28),
        channel="import_flow",
        peak_log_price_effect=0.08,
        basis="announced_measure",
        basis_detail="Import duty on oilseeds raised in a ministry "
        "notification",
        decay_days=20,
        description="Import tariff increase on oilseeds for February",
        declared_by="a.sharma",
        declared_on=date(2026, 1, 2),
    )
    events.register_event(
        event_class="tariff_change",
        commodity="wheat",
        window_start=date(2026, 1, 10),
        window_end=date(2026, 1, 31),
        channel="import_flow",
        peak_log_price_effect=0.06,
        basis="announced_measure",
        basis_detail="Wheat import duty change notified for January",
        decay_days=10,
        description="Tariff change overlapping the wheat horizon",
        declared_by="a.sharma",
        declared_on=date(2026, 1, 2),
    )
    forecasts = ForecastService(
        store,
        model,
        sentiment_provider=sentiment.forecast_input,
        sentiment_claim_verifier=sentiment.verify_claims,
        events_provider=events.forecast_adjustments,
    )
    run_backtest_harness(store, load_accuracy_pack())
    soy = forecasts.run_forecast("soybean", "indore")
    wheat = forecasts.run_forecast("wheat", "delhi_khari_baoli")
    coffee = forecasts.run_forecast("coffee", "bengaluru")
    chili = forecasts.run_forecast("chili", "guntur")
    scenarios = ScenarioService(
        store, model, forecasts, events,
        sentiment_provider=sentiment.forecast_input,
    )
    request = scenarios.parse_request(
        "soybean", "indore", "what if arrivals drop 10%?",
        base_forecast_id=soy.forecast_id,
    )
    scenario_run = scenarios.run_scenario(
        request.request_id, soy.forecast_id, author="a.sharma",
        created_on=date(2026, 1, 3),
    )
    return {
        "db": db,
        "store": store,
        "model": model,
        "events": events,
        "forecasts": forecasts,
        "scenarios": scenarios,
        "dashboards": DashboardService(store, model, events, sentiment),
        "signals": SignalService(store),
        "planning": PlanningService(store),
        "soy": soy,
        "wheat": wheat,
        "coffee": coffee,
        "chili": chili,
        "scenario_run": scenario_run,
    }


def test_pipeline_signals_reperform(env):
    signals = env["signals"]
    for series in (
        ("soybean", "indore"),
        ("wheat", "delhi_khari_baoli"),
        ("coffee", "bengaluru"),
        ("chili", "guntur"),
    ):
        signal = signals.compute_for_series(*series)
        assert signal.value in ("buy_now", "phased", "wait")
        assert signal.reasoning
        assert verify_signal(env["store"], signal) == []
    # idempotent: computing again lands on the same artefact
    again = signals.compute_for_series("soybean", "indore")
    assert again.signal_id == signals.current_signal(
        "soybean", "indore"
    ).signal_id


def test_pipeline_degraded_chili_never_strong(env):
    signal = env["signals"].compute_for_series("chili", "guntur")
    assert signal.accuracy_state == "degraded"
    assert signal.value != "buy_now"
    if signal.base_value == "buy_now":
        assert signal.caps_applied == ["degraded_accuracy"]


def test_pipeline_wheat_signal_names_its_event_window(env):
    signal = env["signals"].compute_for_series("wheat", "delhi_khari_baoli")
    assert signal.active_events
    assert any(
        e.event_class == "tariff_change" for e in signal.active_events
    )
    assert any("event window" in line for line in signal.reasoning)


def test_board_gains_a_signals_section(env):
    signals = env["signals"]
    computed = {}
    for series in (
        ("soybean", "indore"),
        ("wheat", "delhi_khari_baoli"),
        ("coffee", "bengaluru"),
        ("chili", "guntur"),
    ):
        computed[series] = signals.compute_for_series(*series)
    board = env["dashboards"].board(BOARD_DATE)
    signal_rows = [r for r in board.rows if r.kind == "signal"]
    expected = {
        s.signal_id for s in computed.values() if s.value != "wait"
    }
    assert {r.artefact_id for r in signal_rows} == expected
    for row in signal_rows:
        assert env["store"].get_buy_signal(row.artefact_id) is not None
    view = env["dashboards"].board_view(BOARD_DATE)
    assert [r["artefact_id"] for r in view["sections"]["signal"]] == [
        r.artefact_id for r in signal_rows
    ]
    assert "Buy-window signals" in view["html"]


def test_market_provenance_never_carries_desk_facts(env):
    # a plan + assessment exist in this world by now or are made here
    plan = env["planning"].enter_plan(
        commodity="soybean", market="indore", entered_by="r.menon",
        entered_on=date(2026, 1, 5), opening_stock_tonnes=50.0,
        lines=[PlanLine(month=date(2026, 2, 1), required_tonnes=120.0)],
    )
    env["planning"].assess(plan.plan_id)
    dash = env["dashboards"]
    spec = dash.ask(
        "soybean forecast at indore", "a.sharma", date(2026, 1, 6)
    )
    assembly = dash.assemble(spec.spec_id, date(2026, 1, 6))
    appendix = dash.appendix(assembly.assembly_id)
    kinds = {
        fact["kind"]
        for panel in appendix["panels"]
        for figure in panel["figures"]
        for fact in figure["lineage"]
    }
    assert "desk_entered" not in kinds


def test_scenario_basis_assessment_is_pinned_and_badged(env):
    planning = env["planning"]
    run = env["scenario_run"]
    env["scenarios"].adopt(
        run.scenario_id, adopter="a.sharma", role="desk head",
        decided_on=date(2026, 1, 4),
    )
    plan = planning.enter_plan(
        commodity="soybean", market="indore", entered_by="r.menon",
        entered_on=date(2026, 1, 5), opening_stock_tonnes=40.0,
        lines=[
            PlanLine(month=date(2026, 1, 1), required_tonnes=100.0),
            PlanLine(month=date(2026, 2, 1), required_tonnes=100.0),
        ],
    )
    official = planning.assess(plan.plan_id)
    assert official.basis_kind == "official_forecast"
    assert official.scenario_id is None
    assert verify_assessment(env["store"], official) == []
    scenario = planning.assess(plan.plan_id, basis="adopted_scenario")
    assert scenario.basis_kind == "adopted_scenario"
    assert scenario.scenario_id == run.scenario_id
    assert scenario.forecast_id == run.fork.forecast_id
    assert any("scenario-based" in note for note in scenario.notes)
    assert verify_assessment(env["store"], scenario) == []
    # a series with no adopted scenario refuses the basis outright
    wheat_plan = planning.enter_plan(
        commodity="wheat", market="delhi_khari_baoli",
        entered_by="r.menon", entered_on=date(2026, 1, 5),
        opening_stock_tonnes=10.0,
        lines=[PlanLine(month=date(2026, 1, 1), required_tonnes=50.0)],
    )
    with pytest.raises(PlanningStateError):
        planning.assess(wheat_plan.plan_id, basis="adopted_scenario")


def test_scenario_basis_lineage_walks_through_the_run(env):
    # Regression: the scenario-basis price walk once ran the fork
    # through forecast_lineage, naming the fork as a forecast
    # artefact — but the fork lives inside the run, never in the
    # desk's forecast record, so every priced figure failed its
    # own verifier ("lineage names forecast …, not on record").
    planning = env["planning"]
    run = env["scenario_run"]
    stored_run = env["store"].get_scenario(run.scenario_id)
    if stored_run.status != "adopted":
        env["scenarios"].adopt(
            run.scenario_id, adopter="a.sharma", role="desk head",
            decided_on=date(2026, 1, 4),
        )
    plan = planning.enter_plan(
        commodity="soybean", market="indore", entered_by="r.menon",
        entered_on=date(2026, 1, 5), opening_stock_tonnes=40.0,
        lines=[
            PlanLine(month=date(2026, 1, 1), required_tonnes=100.0),
            PlanLine(month=date(2026, 2, 1), required_tonnes=100.0),
        ],
    )
    scenario = planning.assess(plan.plan_id, basis="adopted_scenario")
    assert verify_assessment(env["store"], scenario) == []
    priced = [
        f for f in scenario.figures
        if f.key not in ("total_required_tonnes", "opening_stock_tonnes",
                         "signal")
    ]
    assert priced
    for figure in priced:
        # the run is the artefact of record for fork-priced
        # figures, as on a dashboard's scenario panel
        assert figure.artefact_id == run.scenario_id
        refs = {fact.ref for fact in figure.lineage}
        assert run.scenario_id in refs
        assert run.base_forecast_id in refs
        # the fork is never named as a forecast artefact
        assert run.fork.forecast_id not in refs
        assert not any(
            fact.kind == "forecast" and fact.ref == run.fork.forecast_id
            for fact in figure.lineage
        )
    # the official basis still walks the forecast artefact itself
    official = planning.assess(plan.plan_id)
    official_priced = [
        f for f in official.figures
        if f.key not in ("total_required_tonnes", "opening_stock_tonnes",
                         "signal")
    ]
    assert official_priced
    for figure in official_priced:
        assert figure.artefact_id == official.forecast_id


def test_board_names_a_series_outside_the_catalogue(tmp_path):
    # Regression: the board's pending-gate section resolved every
    # stored forecast through the catalogue with a bare next();
    # a draft forecast for a series the catalogue does not name
    # (the signal engine's fixture series is one — the store
    # takes any series key) crashed the whole board with
    # StopIteration. The row must appear, named as recorded.
    store = build_store(str(tmp_path / "board.db"))
    fixture = _fixture_forecast(
        "fixture_grain", "fixture_market", 2100.0, 2010.0, 2190.0,
        _attachment("measured"),
    )
    store.insert_forecast(fixture)
    board = build_board(
        store, EventService(store), load_dashboard_pack(), BOARD_DATE
    )
    rows = [
        r for r in board.rows
        if r.kind == "pending_gate" and r.artefact_id == fixture.forecast_id
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row.commodity == "fixture_grain"
    assert "fixture_grain" in row.headline
    assert "outside the desk catalogue" in row.headline
    assert row.figures["catalogue"] == "not_in_catalogue"


# --- surfaces -----------------------------------------------------------------


def test_api_surface(env):
    client = TestClient(create_app(env["store"]))
    pack = client.get("/signals/pack")
    assert pack.status_code == 200
    assert pack.json()["version"] == "2026.10.1"
    assert client.get("/planning/pack").json()["version"] == "2026.10.1"

    computed = client.post(
        "/signals/compute",
        json={"commodity": "soybean", "market": "indore"},
    )
    assert computed.status_code == 200
    signal = computed.json()
    assert signal["value"] in ("buy_now", "phased", "wait")
    assert signal["reasoning"]
    shown = client.get(f"/signals/{signal['signal_id']}")
    assert shown.status_code == 200
    assert shown.json()["problems"] == []
    verified = client.get(f"/signals/{signal['signal_id']}/verify")
    assert verified.json()["problems"] == []

    created = client.post(
        "/planning/plans",
        json={
            "commodity": "soybean",
            "market": "indore",
            "entered_by": "r.menon",
            "entered_on": "2026-01-05",
            "opening_stock_tonnes": 25.0,
            "lines": [
                {"month": "2026-01-01", "required_tonnes": 80.0},
                {"month": "2026-02-01", "required_tonnes": 80.0},
            ],
        },
    )
    assert created.status_code == 201
    plan = created.json()
    assert plan["origin"] == "desk_entered"
    assert "desk-entered" in plan["origin_label"]
    assessed = client.post(
        f"/planning/plans/{plan['plan_id']}/assess", json={}
    )
    assert assessed.status_code == 200
    assessment = assessed.json()
    checked = client.get(
        f"/planning/assessments/{assessment['assessment_id']}/verify"
    )
    assert checked.json()["problems"] == []
    board = client.get("/board", params={"board_date": "2026-02-15"})
    assert board.status_code == 200
    assert "signal" in board.json()["sections"]


def test_cli_surfaces(env, capsys):
    assert signals_cli.main(
        ["--db", env["db"], "compute", "soybean", "indore"]
    ) == 0
    out = json.loads(capsys.readouterr().out)
    signal_id = out["signal_id"]
    assert signals_cli.main(
        ["--db", env["db"], "verify", signal_id]
    ) == 0
    assert json.loads(capsys.readouterr().out)["problems"] == []

    assert planning_cli.main(
        [
            "--db", env["db"], "enter", "wheat", "delhi_khari_baoli",
            "--by", "r.menon", "--on", "2026-01-05", "--stock", "30",
            "--line", "2026-01:90", "--line", "2026-02:90",
        ]
    ) == 0
    plan_id = json.loads(capsys.readouterr().out)["plan_id"]
    assert planning_cli.main(
        ["--db", env["db"], "assess", plan_id]
    ) == 0
    assessment_id = json.loads(capsys.readouterr().out)["assessment_id"]
    assert planning_cli.main(
        ["--db", env["db"], "verify", assessment_id]
    ) == 0
    assert json.loads(capsys.readouterr().out)["problems"] == []


# --- truth isolation ------------------------------------------------------------


def test_r8_packages_are_truth_isolated():
    root = Path(__file__).resolve().parents[1] / "src" / "fmcg_forecast"
    for package in ("signals", "planning"):
        for path in (root / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert "truth" not in alias.name
                elif isinstance(node, ast.ImportFrom):
                    assert "truth" not in (node.module or "")
                elif isinstance(node, ast.Constant) and isinstance(
                    node.value, str
                ):
                    assert "truth_observations" not in node.value
