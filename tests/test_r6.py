"""Round 6 tests: scenario pack, the deterministic grammar
(fixtures exact, refusals named), lever bounds at and beyond the
bound, the engine's shift slot, lever-to-shift conversions,
pinned forks (identity, diff, base immutability), scenario
events (extension, registry add, hypothetical), the adoption
gate, tamper detection, API + CLI surfaces, truth isolation."""

from __future__ import annotations

import ast
import json
import math
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.api import create_app
from fmcg_forecast.events.pack import load_event_pack
from fmcg_forecast.events.paths import build_event_path
from fmcg_forecast.events.service import EventService
from fmcg_forecast.forecast.engine import (
    DriverShift,
    ForecastError,
    run_engine,
)
from fmcg_forecast.forecast.service import ForecastService
from fmcg_forecast.forecast.verify import verify_forecast
from fmcg_forecast.modelport import OfflineModel
from fmcg_forecast.scenarios import cli as scenario_cli
from fmcg_forecast.scenarios.diff import compute_diff
from fmcg_forecast.scenarios.models import LeverApplication
from fmcg_forecast.scenarios.pack import SCENARIO_PACK_V1, load_scenario_pack
from fmcg_forecast.scenarios.parse import ParseRefusal, parse_request_text
from fmcg_forecast.scenarios.service import (
    AdoptionStateError,
    AdoptionValidationError,
    ScenarioParseError,
    ScenarioService,
    ScenarioValidationError,
)
from fmcg_forecast.sentiment.grading import build_sentiment_grading_store
from fmcg_forecast.sentiment.load import load_sentiment_corpus
from fmcg_forecast.sentiment.service import SentimentService
from fmcg_forecast.store import build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset

SEED = 20261027
PACK = SCENARIO_PACK_V1
HISTORY_END = date(2025, 12, 31)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db = str(tmp_path_factory.mktemp("r6") / "test.db")
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
    tariff = events.register_event(
        event_class="tariff_change",
        commodity="soybean",
        window_start=date(2026, 2, 1),
        window_end=date(2026, 2, 28),
        channel="import_flow",
        peak_log_price_effect=0.08,
        basis="announced_measure",
        basis_detail="Import duty on oilseeds raised by 10 "
        "percentage points in a ministry notification",
        decay_days=20,
        description="Import tariff increase on oilseeds for February",
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
    scenarios = ScenarioService(
        store,
        model,
        forecasts,
        events,
        sentiment_provider=sentiment.forecast_input,
    )
    return {
        "db": db,
        "store": store,
        "events": events,
        "forecasts": forecasts,
        "scenarios": scenarios,
        "tariff": tariff,
        "soy_base": forecasts.run_forecast("soybean", "indore"),
        "wheat_base": forecasts.run_forecast("wheat", "delhi_khari_baoli"),
        "coffee_base": forecasts.run_forecast("coffee", "bengaluru"),
    }


def _parse(text, events=()):
    return parse_request_text(text, events=list(events), pack=PACK)


# --- the pack ---------------------------------------------------------------


def test_pack_loader_is_fail_closed():
    assert load_scenario_pack().version == "2026.10.1"
    with pytest.raises(ValueError):
        load_scenario_pack("1999.01.1")


def test_pack_catalogue_is_bounded_and_stated():
    assert set(PACK.levers) == {
        "arrivals_shift_pct",
        "stock_cover_days",
        "trade_flow_shift_pct",
        "weather_deviation",
        "sentiment_override",
        "event",
        "event_extension",
        "hypothetical_event",
    }
    assert PACK.levers["arrivals_shift_pct"].max_value == 40.0
    assert PACK.levers["stock_cover_days"].min_value == -30.0
    assert PACK.levers["trade_flow_shift_pct"].max_value == 60.0
    assert PACK.levers["weather_deviation"].max_value == 0.5
    assert PACK.levers["sentiment_override"].min_value == -1.0
    assert PACK.levers["event_extension"].max_value == 90.0
    assert PACK.days_per_month == 30


# --- the grammar: fixtures exact ----------------------------------------------


def test_parse_brief_sentence_exact(env):
    tariff = env["tariff"]
    levers = _parse(
        "what if arrivals drop 10% and the tariff stays another month?",
        events=[{"event_id": tariff.event_id, "event_class": "tariff_change"}],
    )
    assert len(levers) == 2
    first, second = levers
    assert first.lever == "arrivals_shift_pct" and first.value == -10.0
    assert first.clause == "arrivals drop 10%"
    assert second.lever == "event_extension"
    assert second.event_id == tariff.event_id
    assert second.extra_days == 30
    assert second.clause == "the tariff stays another month"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("arrivals rise by 7.5 percent", ("arrivals_shift_pct", 7.5)),
        ("arrivals down 3%", ("arrivals_shift_pct", -3.0)),
        ("stock cover falls by 12 days", ("stock_cover_days", -12.0)),
        ("stock cover up 5 days", ("stock_cover_days", 5.0)),
        ("imports rise 20%", ("trade_flow_shift_pct", 20.0)),
        ("trade flow down 15 percent", ("trade_flow_shift_pct", -15.0)),
        ("weather index deviation of -0.3", ("weather_deviation", -0.3)),
        ("weather deviation 0.25", ("weather_deviation", 0.25)),
        ("weather index falls by 0.2", ("weather_deviation", -0.2)),
        ("sentiment to -0.8", ("sentiment_override", -0.8)),
        ("sentiment index override to 0.4", ("sentiment_override", 0.4)),
    ],
)
def test_parse_single_clause_shapes(text, expected):
    levers = _parse(text)
    assert len(levers) == 1
    assert (levers[0].lever, levers[0].value) == expected
    assert levers[0].clause == text


def test_parse_hypothetical_and_registry_shapes():
    levers = _parse("a new tariff pushes prices up by 8% for 30 days")
    assert len(levers) == 1
    lever = levers[0]
    assert lever.lever == "hypothetical_event"
    assert lever.event_class == "tariff_change"
    assert lever.value == 8.0
    assert lever.duration_days == 30
    assert lever.start_offset_days == 0

    levers = _parse("a demand shock cuts prices by 5% for 10 days")
    assert levers[0].value == -5.0
    assert levers[0].event_class == "demand_shock"

    levers = _parse("add event evt-abc123def456")
    assert levers[0].lever == "event"
    assert levers[0].event_id == "EVT-abc123def456"


def test_parse_extension_wordings(env):
    tariff = env["tariff"]
    ctx = [{"event_id": tariff.event_id, "event_class": "tariff_change"}]
    levers = _parse("the tariff holds two more months", events=ctx)
    assert levers[0].extra_days == 60
    levers = _parse("the tariff stays for 45 more days", events=ctx)
    assert levers[0].extra_days == 45
    levers = _parse(
        f"extend event {tariff.event_id.lower()} by 15 days", events=ctx
    )
    assert levers[0].event_id == tariff.event_id
    assert levers[0].extra_days == 15


# --- the grammar: refusals -----------------------------------------------------


def test_parse_refusal_names_the_clause():
    with pytest.raises(ParseRefusal) as caught:
        _parse("what if the monsoon fails completely?")
    assert caught.value.clause == "the monsoon fails completely"
    with pytest.raises(ParseRefusal):
        _parse("")
    with pytest.raises(ParseRefusal) as caught:
        _parse("arrivals drop 10% and the market rallies hard")
    assert caught.value.clause == "the market rallies hard"


def test_parse_refusal_duplicate_driver():
    with pytest.raises(ParseRefusal) as caught:
        _parse("arrivals drop 10% and arrivals rise 5%")
    assert "arrivals" in caught.value.reason


def test_parse_refusal_event_resolution():
    tariff = {"event_id": "EVT-aaaaaaaaaaaa", "event_class": "tariff_change"}
    other = {"event_id": "EVT-bbbbbbbbbbbb", "event_class": "tariff_change"}
    with pytest.raises(ParseRefusal) as caught:
        _parse("the tariff stays another month", events=[])
    assert "no tariff_change event" in caught.value.reason
    with pytest.raises(ParseRefusal) as caught:
        _parse("the tariff stays another month", events=[tariff, other])
    assert "ambiguous" in caught.value.reason


@pytest.mark.parametrize(
    "text",
    [
        "arrivals drop 41%",
        "arrivals rise 41%",
        "stock cover rises by 31 days",
        "imports rise 61%",
        "weather index deviation of 0.6",
        "sentiment to 1.5",
        "a tariff pushes prices up by 36% for 30 days",
        "a tariff pushes prices up by 8% for 91 days",
    ],
)
def test_parse_beyond_bound_refused_with_bound_named(text):
    with pytest.raises(ParseRefusal) as caught:
        _parse(text)
    assert "bound" in caught.value.reason


@pytest.mark.parametrize(
    "text",
    [
        "arrivals drop 40%",
        "arrivals rise 40%",
        "stock cover falls by 30 days",
        "imports drop 60%",
        "weather index deviation of -0.5",
        "sentiment to -1",
        "a tariff pushes prices up by 35% for 90 days",
    ],
)
def test_parse_at_bound_passes(text):
    levers = _parse(text)
    assert len(levers) == 1


def test_parse_extension_beyond_bound_refused(env):
    tariff = env["tariff"]
    ctx = [{"event_id": tariff.event_id, "event_class": "tariff_change"}]
    with pytest.raises(ParseRefusal) as caught:
        _parse("the tariff stays four more months", events=ctx)
    assert "bound" in caught.value.reason
    levers = _parse("the tariff stays three more months", events=ctx)
    assert levers[0].extra_days == 90


# --- the engine's shift slot -----------------------------------------------------


def test_engine_shift_moves_input_path_exactly(env):
    store, manifest = env["store"], env["store"].get_manifest()
    base = run_engine(store, manifest, "wheat", "delhi_khari_baoli", HISTORY_END)
    shift = DriverShift(driver="arrivals", mode="add", value=-0.25)
    fork = run_engine(
        store, manifest, "wheat", "delhi_khari_baoli", HISTORY_END,
        driver_shifts=[shift],
    )
    base_line = next(l for l in base.lines if l.driver == "arrivals")
    fork_line = next(l for l in fork.lines if l.driver == "arrivals")
    for i in range(90):
        assert fork_line.input_path[i] == pytest.approx(
            base_line.input_path[i] - 0.25, abs=1.1e-4
        )
    assert fork_line.input_summary["scenario_shift"]["value"] == -0.25
    assert "scenario_shift" not in base_line.input_summary
    assert verify_forecast(fork) == []
    stock_line = next(l for l in fork.lines if l.driver == "stock_level")
    assert "scenario_shift" not in stock_line.input_summary


def test_engine_shift_refusals(env):
    store, manifest = env["store"], env["store"].get_manifest()
    with pytest.raises(ForecastError):
        run_engine(
            store, manifest, "coffee", "bengaluru", HISTORY_END,
            driver_shifts=[DriverShift(driver="stock_level", mode="add", value=0.1)],
        )
    with pytest.raises(ForecastError):
        run_engine(
            store, manifest, "wheat", "delhi_khari_baoli", HISTORY_END,
            driver_shifts=[
                DriverShift(driver="arrivals", mode="add", value=0.1),
                DriverShift(driver="arrivals", mode="add", value=0.2),
            ],
        )
    with pytest.raises(ForecastError):
        run_engine(
            store, manifest, "wheat", "delhi_khari_baoli", HISTORY_END,
            sentiment_start_override=-0.5,
        )


def test_engine_weather_shift_clips_to_the_index_range(env):
    store, manifest = env["store"], env["store"].get_manifest()
    fork = run_engine(
        store, manifest, "wheat", "delhi_khari_baoli", HISTORY_END,
        driver_shifts=[
            DriverShift(
                driver="weather_index", mode="add_clip", value=0.5,
                clip_min=-1.0, clip_max=1.0,
            )
        ],
    )
    line = next(l for l in fork.lines if l.driver == "weather_index")
    assert all(-1.0 <= v <= 1.0 for v in line.input_path)
    assert verify_forecast(fork) == []


# --- the fork: pinned, exact, base untouched --------------------------------------


def _raw_forecast_row(db: str, forecast_id: str):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT payload, status FROM forecasts WHERE forecast_id = ?",
            (forecast_id,),
        ).fetchone()
    finally:
        conn.close()


def test_run_from_typed_what_if(env):
    scenarios, base, tariff = env["scenarios"], env["soy_base"], env["tariff"]
    assert base.method.events_applied == [tariff.event_id]
    before = _raw_forecast_row(env["db"], base.forecast_id)
    request = scenarios.parse_request(
        "soybean",
        "indore",
        "what if arrivals drop 10% and the tariff stays another month?",
        base_forecast_id=base.forecast_id,
    )
    assert request.intake == "text"
    assert request.source_text is not None
    run = scenarios.run_scenario(
        request.request_id, base.forecast_id, "a.sharma", date(2026, 1, 3)
    )
    assert run.status == "draft"
    assert run.base_forecast_id == base.forecast_id
    assert run.fork.forecast_id != base.forecast_id
    # The shift re-performs from the store by the pack's conversion.
    rows = env["store"].series("soybean", "indore", "arrivals", None, base.as_of)
    logs = [math.log(r.value) for r in rows]
    mean = sum(logs) / len(logs)
    sd = math.sqrt(sum((v - mean) ** 2 for v in logs) / len(logs))
    shift = next(s for s in run.shifts if s.lever == "arrivals_shift_pct")
    assert shift.value == pytest.approx(math.log(0.9) / sd, abs=1e-9)
    assert shift.basis_stats["history_obs"] == len(rows)
    # The extension is scenario-local and the registry is untouched.
    assert len(run.scenario_events) == 1
    extended = run.scenario_events[0]
    assert extended.origin == "scenario"
    assert extended.source_record_id == tariff.event_id
    assert extended.window_end == tariff.window_end + timedelta(days=30)
    assert env["store"].get_market_event(extended.event_id) is None
    assert env["events"].get_event(tariff.event_id).window_end == tariff.window_end
    fork_events = next(l for l in run.fork.lines if l.driver == "events")
    assert extended.event_id in fork_events.input_summary["per_event"]
    # The fork is not a desk forecast; the base is byte-identical.
    assert env["store"].get_forecast(run.fork_forecast_id) is None
    assert _raw_forecast_row(env["db"], base.forecast_id) == before
    assert scenarios.verify_stored(run.scenario_id) == []
    # A re-run is the same artefact, not a duplicate.
    again = scenarios.run_scenario(
        request.request_id, base.forecast_id, "a.sharma", date(2026, 1, 3)
    )
    assert again.scenario_id == run.scenario_id


def test_diff_identity_and_shared_baseline(env):
    scenarios, base = env["scenarios"], env["wheat_base"]
    request = scenarios.create_request(
        "wheat",
        "delhi_khari_baoli",
        [
            LeverApplication(lever="arrivals_shift_pct", value=-20.0),
            LeverApplication(lever="weather_deviation", value=0.3),
        ],
    )
    run = scenarios.run_scenario(
        request.request_id, base.forecast_id, "t.iyer", date(2026, 1, 3)
    )
    diff, problems = compute_diff(run.scenario_id, base, run.fork)
    assert problems == []
    for base_day, fork_day in zip(base.days, run.fork.days):
        assert base_day.baseline == fork_day.baseline
    assert diff.p50_total == pytest.approx(
        sum(diff.driver_totals.values()) + diff.events_total, abs=1e-9
    )
    assert set(diff.at_horizons) == {"7", "30", "90"}
    assert diff.driver_totals["arrivals"] != 0.0
    assert scenarios.verify_stored(run.scenario_id) == []


def test_sentiment_override_fork(env):
    scenarios, base = env["scenarios"], env["wheat_base"]
    base_line = next(l for l in base.lines if l.driver == "sentiment")
    assert base_line.input_summary["state"] == "estimated"
    request = scenarios.create_request(
        "wheat",
        "delhi_khari_baoli",
        [LeverApplication(lever="sentiment_override", value=-0.8)],
    )
    run = scenarios.run_scenario(
        request.request_id, base.forecast_id, "t.iyer", date(2026, 1, 3)
    )
    fork_line = next(l for l in run.fork.lines if l.driver == "sentiment")
    assert fork_line.input_summary["last_input"] == -0.8
    assert fork_line.input_summary["scenario_shift"] == {
        "mode": "set_start",
        "value": -0.8,
    }
    persistence = fork_line.input_summary["persistence"]
    assert fork_line.input_path[0] == pytest.approx(-0.8 * persistence, abs=1.1e-4)
    assert fork_line.input_path[1] == pytest.approx(
        -0.8 * persistence**2, abs=1.1e-4
    )
    assert scenarios.verify_stored(run.scenario_id) == []


# --- applicability refusals --------------------------------------------------------


def test_run_refuses_levers_the_series_cannot_carry(env):
    scenarios, coffee = env["scenarios"], env["coffee_base"]
    stock = scenarios.create_request(
        "coffee",
        "bengaluru",
        [LeverApplication(lever="stock_cover_days", value=5.0)],
    )
    with pytest.raises(ScenarioValidationError) as caught:
        scenarios.run_scenario(
            stock.request_id, coffee.forecast_id, "t.iyer", date(2026, 1, 3)
        )
    assert "stock_level" in str(caught.value)
    sentiment = scenarios.create_request(
        "coffee",
        "bengaluru",
        [LeverApplication(lever="sentiment_override", value=0.5)],
    )
    with pytest.raises(ScenarioValidationError) as caught:
        scenarios.run_scenario(
            sentiment.request_id, coffee.forecast_id, "t.iyer", date(2026, 1, 3)
        )
    assert "sentiment" in str(caught.value)


def test_structured_intake_validation():
    scenarios = ScenarioService.__new__(ScenarioService)
    scenarios.pack = PACK
    scenarios.event_pack = load_event_pack()
    with pytest.raises(ScenarioValidationError):
        scenarios.validate_levers(
            [LeverApplication(lever="price_override", value=5.0)]
        )
    with pytest.raises(ScenarioValidationError) as caught:
        scenarios.validate_levers(
            [LeverApplication(lever="arrivals_shift_pct", value=55.0)]
        )
    assert "bound" in str(caught.value)
    with pytest.raises(ScenarioValidationError):
        scenarios.validate_levers(
            [
                LeverApplication(lever="arrivals_shift_pct", value=5.0),
                LeverApplication(lever="arrivals_shift_pct", value=6.0),
            ]
        )


def test_event_lever_refusals(env):
    scenarios, base, tariff = env["scenarios"], env["soy_base"], env["tariff"]
    add_applied = scenarios.create_request(
        "soybean",
        "indore",
        [LeverApplication(lever="event", event_id=tariff.event_id)],
    )
    with pytest.raises(ScenarioValidationError) as caught:
        scenarios.run_scenario(
            add_applied.request_id, base.forecast_id, "t.iyer", date(2026, 1, 3)
        )
    assert "already in the base forecast" in str(caught.value)
    extend_absent = scenarios.create_request(
        "wheat",
        "delhi_khari_baoli",
        [
            LeverApplication(
                lever="event_extension", event_id=tariff.event_id, extra_days=10
            )
        ],
    )
    with pytest.raises(ScenarioValidationError) as caught:
        scenarios.run_scenario(
            extend_absent.request_id,
            env["wheat_base"].forecast_id,
            "t.iyer",
            date(2026, 1, 3),
        )
    assert "not in the base forecast" in str(caught.value)


# --- scenario events: registry add + hypothetical -----------------------------------


def test_registry_add_and_hypothetical_events(env):
    scenarios, events = env["scenarios"], env["events"]
    declared = events.register_event(
        event_class="logistics_disruption",
        commodity="wheat",
        window_start=date(2026, 1, 20),
        window_end=date(2026, 2, 10),
        channel="arrivals",
        peak_log_price_effect=0.05,
        basis="desk_estimate",
        basis_detail="Desk estimate: corridor disruption thins "
        "arrivals for three weeks",
        decay_days=10,
        description="Transport corridor disruption thinning arrivals",
        declared_by="a.sharma",
        declared_on=date(2026, 1, 2),
    )
    base = env["wheat_base"]
    assert declared.event_id not in base.method.events_applied
    request = scenarios.create_request(
        "wheat",
        "delhi_khari_baoli",
        [
            LeverApplication(lever="event", event_id=declared.event_id),
            LeverApplication(
                lever="hypothetical_event",
                value=8.0,
                event_class="demand_shock",
                start_offset_days=10,
                duration_days=20,
                decay_days=5,
            ),
        ],
    )
    run = scenarios.run_scenario(
        request.request_id, base.forecast_id, "t.iyer", date(2026, 1, 3)
    )
    assert len(run.scenario_events) == 1
    assert run.fork.method.events_applied == [
        declared.event_id,
        run.scenario_events[0].event_id,
    ]
    hypo = run.scenario_events[0]
    assert hypo.origin == "scenario"
    assert hypo.event_class == "demand_shock"
    assert hypo.transmission.peak_log_price_effect == pytest.approx(
        round(math.log(1.08), 6)
    )
    assert hypo.window_start == base.as_of + timedelta(days=11)
    assert hypo.window_end == hypo.window_start + timedelta(days=19)
    expected_path = build_event_path(
        hypo, base.as_of + timedelta(days=1), 90, load_event_pack()
    )
    line = next(l for l in run.fork.lines if l.driver == "events")
    recorded = line.input_summary["per_event"][hypo.event_id]["input_path"]
    assert recorded == pytest.approx(expected_path, abs=1.1e-4)
    assert scenarios.verify_stored(run.scenario_id) == []


# --- the adoption gate ---------------------------------------------------------------


def _adopted_ready_run(env, text="arrivals drop 5%"):
    scenarios = env["scenarios"]
    request = scenarios.parse_request(
        "soybean", "indore", text, base_forecast_id=env["soy_base"].forecast_id
    )
    return scenarios.run_scenario(
        request.request_id, env["soy_base"].forecast_id, "a.sharma",
        date(2026, 1, 3),
    )


def test_adoption_gate_and_supersession(env):
    scenarios = env["scenarios"]
    assert scenarios.adopted_view("soybean", "indore")["state"] == "none"
    first = _adopted_ready_run(env)
    assert scenarios.scenario_view(first.scenario_id)["view_kind"] == "scenario_draft"
    with pytest.raises(AdoptionValidationError):
        scenarios.adopt(
            first.scenario_id, "unknown", "Head of Trading Desk", date(2026, 1, 4)
        )
    with pytest.raises(AdoptionValidationError):
        scenarios.adopt(first.scenario_id, "r.menon", "tbd", date(2026, 1, 4))
    act = scenarios.adopt(
        first.scenario_id, "r.menon", "Head of Trading Desk", date(2026, 1, 4)
    )
    assert act.supersedes_scenario_id is None
    assert scenarios.get_scenario(first.scenario_id).status == "adopted"
    view = scenarios.adopted_view("soybean", "indore")
    assert view["state"] == "adopted"
    assert view["scenario"]["view_kind"] == "adopted_scenario"
    with pytest.raises(AdoptionStateError):
        scenarios.adopt(
            first.scenario_id, "r.menon", "Head of Trading Desk", date(2026, 1, 5)
        )
    second = _adopted_ready_run(env, text="arrivals drop 15%")
    act2 = scenarios.adopt(
        second.scenario_id, "r.menon", "Head of Trading Desk", date(2026, 1, 6)
    )
    assert act2.supersedes_scenario_id == first.scenario_id
    assert scenarios.get_scenario(first.scenario_id).status == "superseded"
    assert scenarios.scenario_view(first.scenario_id)["view_kind"] == (
        "superseded_scenario"
    )
    assert scenarios.adopted_view("soybean", "indore")["scenario"][
        "scenario_id"
    ] == second.scenario_id
    with pytest.raises(AdoptionStateError):
        scenarios.adopt(
            first.scenario_id, "r.menon", "Head of Trading Desk", date(2026, 1, 7)
        )
    # The base forecast's own status is untouched by adoption.
    assert env["forecasts"].get_forecast(env["soy_base"].forecast_id).status == (
        "draft"
    )


# --- tamper detection ------------------------------------------------------------------


def test_tamper_detection(env):
    scenarios = env["scenarios"]
    run = _adopted_ready_run(env, text="stock cover rises by 3 days")
    assert scenarios.verify_stored(run.scenario_id) == []
    from fmcg_forecast.scenarios.verify import verify_scenario

    tampered_fork = run.fork.model_copy(deep=True)
    tampered_fork.days[10].p50 += 5.0
    tampered = run.model_copy(update={"fork": tampered_fork})
    problems = verify_scenario(
        env["store"],
        tampered,
        scenarios.get_request(run.request_id),
        env["forecasts"].get_forecast(run.base_forecast_id),
        PACK,
        load_event_pack(),
    )
    assert problems
    shifted = run.model_copy(deep=True)
    shifted.shifts[0].value += 0.5
    problems = verify_scenario(
        env["store"],
        shifted,
        scenarios.get_request(run.request_id),
        env["forecasts"].get_forecast(run.base_forecast_id),
        PACK,
        load_event_pack(),
    )
    assert any("shift" in p for p in problems)


# --- migration + API + CLI ---------------------------------------------------------------


def test_migration_0006_creates_the_scenario_tables(env):
    conn = sqlite3.connect(env["db"])
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        conn.close()
    assert {"scenario_requests", "scenarios", "scenario_adoptions"} <= tables
    root = Path(__file__).resolve().parents[1] / "migrations"
    assert (root / "sqlite" / "0006_scenarios.sql").exists()
    assert (root / "postgres" / "0006_scenarios.sql").exists()


def test_api_surface(env):
    client = TestClient(create_app(env["store"], OfflineModel()))
    base = env["wheat_base"]
    r = client.get("/scenarios/pack")
    assert r.status_code == 200
    assert r.json()["version"] == "2026.10.1"
    r = client.post(
        "/scenarios/requests",
        json={
            "commodity": "wheat",
            "market": "delhi_khari_baoli",
            "text": "what if arrivals drop 10%?",
            "base_forecast_id": base.forecast_id,
        },
    )
    assert r.status_code == 201
    request_id = r.json()["request_id"]
    r = client.post(
        "/scenarios/requests",
        json={
            "commodity": "wheat",
            "market": "delhi_khari_baoli",
            "text": "what if prices triple overnight?",
            "base_forecast_id": base.forecast_id,
        },
    )
    assert r.status_code == 422
    assert r.json()["detail"]["clause"] == "prices triple overnight"
    r = client.post(
        "/scenarios/requests/structured",
        json={
            "commodity": "wheat",
            "market": "delhi_khari_baoli",
            "levers": [{"lever": "arrivals_shift_pct", "value": 55.0}],
        },
    )
    assert r.status_code == 422
    r = client.post(
        "/scenarios",
        json={
            "request_id": request_id,
            "base_forecast_id": base.forecast_id,
            "author": "a.sharma",
            "created_on": "2026-01-03",
        },
    )
    assert r.status_code == 201
    assert r.json()["view_kind"] == "scenario_draft"
    scenario_id = r.json()["scenario_id"]
    r = client.get(f"/scenarios/{scenario_id}/diff")
    assert r.status_code == 200
    assert set(r.json()["at_horizons"]) == {"7", "30", "90"}
    r = client.get(f"/scenarios/{scenario_id}/verify")
    assert r.status_code == 200 and r.json()["problems"] == []
    r = client.get("/scenarios/adopted/wheat/delhi_khari_baoli")
    assert r.status_code == 200 and r.json()["state"] == "none"
    r = client.post(
        f"/scenarios/{scenario_id}/adopt",
        json={"adopter": "n/a", "role": "Head of Trading Desk"},
    )
    assert r.status_code == 422
    r = client.post(
        f"/scenarios/{scenario_id}/adopt",
        json={
            "adopter": "r.menon",
            "role": "Head of Trading Desk",
            "decided_on": "2026-01-04",
        },
    )
    assert r.status_code == 200
    r = client.get("/scenarios/adopted/wheat/delhi_khari_baoli")
    assert r.json()["state"] == "adopted"
    assert r.json()["scenario"]["view_kind"] == "adopted_scenario"
    r = client.get("/scenarios", params={"commodity": "wheat"})
    assert any(s["scenario_id"] == scenario_id for s in r.json()["scenarios"])


def test_cli_surface(env, capsys):
    rc = scenario_cli.main(
        [
            "--db", env["db"], "parse",
            "--commodity", "soybean", "--market", "indore",
            "--text", "arrivals drop 10%",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["request_id"].startswith("SCRQ-")
    rc = scenario_cli.main(
        [
            "--db", env["db"], "parse",
            "--commodity", "soybean", "--market", "indore",
            "--text", "the market rallies hard",
        ]
    )
    assert rc == 2
    capsys.readouterr()


def test_scenarios_package_is_truth_isolated():
    base = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "fmcg_forecast"
        / "scenarios"
    )
    for path in base.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "truth" not in alias.name
            elif isinstance(node, ast.ImportFrom):
                assert "truth" not in (node.module or "")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "truth_observations" not in node.value
