"""Round 12 tests: forecast-ops analytics (F20-AM1) + shock grading.

The ops report computed from the artefacts of record: accuracy
trends pooled by the ledger's own rule (hand-computed on a
fabricated result set), signal outcomes measured against the
price that actually followed (hand-computed on a fixture path),
transmission error per event class with small samples named,
shock-window grades split at the planted events' windows, and
the whole artefact re-performed by the verifier — tamper
included. API + CLI, and a Postgres parity test that runs when
FMCG_TEST_DATABASE_URL names a cluster.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.analytics import cli as analytics_cli
from fmcg_forecast.analytics.engine import _judge_outcome, _outcome_row
from fmcg_forecast.analytics.pack import load_analytics_pack
from fmcg_forecast.analytics.service import AnalyticsService
from fmcg_forecast.analytics.verify import verify_report
from fmcg_forecast.api import create_app
from fmcg_forecast.backtest import metrics
from fmcg_forecast.backtest.harness import run_all
from fmcg_forecast.events.service import EventService
from fmcg_forecast.forecast.engine import forecast_content_id
from fmcg_forecast.forecast.models import (
    ATTRIBUTION_ORDER as _ATTR,
)
from fmcg_forecast.forecast.models import (
    AccuracyAttachment,
    BacktestResult,
    BaselineMethod,
    Forecast,
    ForecastDay,
    ForecastMethod,
    HorizonAccuracy,
    HorizonSummary,
    ResidualMethod,
    SparsityMethod,
)
from fmcg_forecast.models import Observation
from fmcg_forecast.signals.models import BuySignal, signal_content_id
from fmcg_forecast.signals.pack import load_signal_pack
from fmcg_forecast.store import build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset

SEED = 20261027


@pytest.fixture(scope="module")
def graded(tmp_path_factory):
    """A loaded store: grid run, ledger built, events seeded."""
    db = str(tmp_path_factory.mktemp("r12") / "test.db")
    store = build_store(db)
    truth = build_truth_store(db)
    load_dataset(store, truth, SEED)
    run_all(store)
    EventService(store).seed_historical(store.get_manifest())
    return store, db


# --- the pack ---------------------------------------------------------------


def test_pack_is_versioned_and_fail_closed():
    pack = load_analytics_pack()
    assert pack.version == "2026.10.1"
    assert pack.trend_window_origins == 3
    assert pack.min_class_sample == 3
    for rule in (
        pack.trend_rule,
        pack.signal_outcome_rule,
        pack.transmission_rule,
        pack.shock_window_rule,
    ):
        assert len(rule) > 100
    with pytest.raises(ValueError):
        load_analytics_pack("1999.1.1")


# --- accuracy trends: hand-computed pooling -----------------------------------


def _result(commodity, market, origin, horizon, sum_abs_pct, covered, n_days=10):
    result = BacktestResult(
        result_id="BT-pending",
        commodity=commodity,
        market=market,
        origin=origin,
        horizon_days=horizon,
        forecast_id="FCST-fixture",
        engine_version="fixture",
        pack_version="2026.10.1",
        days=[],
        n_days=n_days,
        covered_days=covered,
        sum_err=0.0,
        sum_abs_err=sum_abs_pct * 20.0,
        sum_abs_pct=sum_abs_pct,
        mae=0.0,
        mape=0.0,
        bias=0.0,
        coverage=0.0,
    )
    return result.model_copy(
        update={"result_id": metrics.result_content_id(result)}
    )


def test_trend_windows_pool_by_the_ledger_rule(tmp_path):
    store = build_store(str(tmp_path / "trend.db"))
    # six origins: early three pool to MAPE 4.0 (0.4/10 per day),
    # late three to 6.0 — delta +2.0pp, beyond the 0.25 epsilon
    for i in range(6):
        store.insert_backtest_result(
            _result(
                "fixture_grain", "fixture_market",
                date(2025, 1, 1) + timedelta(days=31 * i), 30,
                sum_abs_pct=0.4 if i < 3 else 0.6,
                covered=8 if i < 3 else 9,
            )
        )
    from fmcg_forecast.analytics.engine import _trend_row

    row = _trend_row(
        store, "fixture_grain", "fixture_market", 30, load_analytics_pack()
    )
    assert row.n_results == 6
    assert row.early_mape == 4.0 and row.late_mape == 6.0
    assert row.early_coverage == 0.8 and row.late_coverage == 0.9
    assert row.delta_mape_pp == 2.0
    assert row.direction == "worsening"
    assert len(row.early_origins) == 3 and len(row.late_origins) == 3


def test_trend_names_insufficient_history(tmp_path):
    store = build_store(str(tmp_path / "trend2.db"))
    for i in range(5):
        store.insert_backtest_result(
            _result(
                "fixture_grain", "fixture_market",
                date(2025, 1, 1) + timedelta(days=31 * i), 30, 0.4, 8,
            )
        )
    from fmcg_forecast.analytics.engine import _trend_row

    row = _trend_row(
        store, "fixture_grain", "fixture_market", 30, load_analytics_pack()
    )
    assert row.direction == "insufficient_history"
    assert row.delta_mape_pp is None
    assert row.early_origins == [] and row.late_origins == []
    assert "insufficient" in row.reason


# --- signal outcomes: the stated rule, hand-judged ------------------------------


def test_outcome_rule_judges_each_call_by_its_own_claim():
    pack = load_signal_pack()
    # rise bar +2, fall bar -2 (the signal pack's own bars)
    assert _judge_outcome("buy_now", 2.5, pack) == ("rose", True)
    assert _judge_outcome("buy_now", 0.5, pack) == ("flat", False)
    assert _judge_outcome("buy_now", -3.0, pack) == ("fell", False)
    assert _judge_outcome("wait", -3.0, pack) == ("fell", True)
    assert _judge_outcome("wait", 0.5, pack) == ("flat", True)
    assert _judge_outcome("wait", 2.5, pack) == ("rose", False)
    assert _judge_outcome("phased", 2.5, pack) == ("rose", True)
    assert _judge_outcome("phased", 0.0, pack) == ("flat", True)
    assert _judge_outcome("phased", -2.5, pack) == ("fell", False)


def _signal(commodity, market, as_of, value, drift=10.0, spot=2000.0):
    signal = BuySignal(
        signal_id="SIG-pending",
        commodity=commodity,
        market=market,
        forecast_id="FCST-fixture",
        forecast_status="official",
        as_of=as_of,
        horizon_days=30,
        spot_inr=spot,
        spot_date=as_of,
        p10_horizon_inr=spot * 0.95,
        p50_horizon_inr=spot * (1 + drift / 100),
        p90_horizon_inr=spot * 1.15,
        drift_pct=drift,
        band_width_pct=10.0,
        accuracy_state="measured",
        accuracy_record_ids=[],
        degraded_horizons=[],
        base_value=value,
        value=value,
        caps_applied=[],
        active_events=[],
        missing_drivers=[],
        reasoning=["fixture"],
        pack_version="2026.10.1",
        scope_note="signal only",
    )
    return signal.model_copy(update={"signal_id": signal_content_id(signal)})


def test_outcome_row_measures_the_realised_price(tmp_path):
    store = build_store(str(tmp_path / "outcome.db"))
    store.insert_observations(
        [
            Observation(commodity="fixture_grain", market="fixture_market",
                        obs_date=date(2025, 11, 1), driver="modal_price",
                        value=2000.0),
            Observation(commodity="fixture_grain", market="fixture_market",
                        obs_date=date(2025, 11, 20), driver="modal_price",
                        value=2100.0),
            Observation(commodity="fixture_grain", market="fixture_market",
                        obs_date=date(2025, 12, 1), driver="modal_price",
                        value=2200.0),
        ]
    )
    pack = load_signal_pack()
    # buy_now struck 2025-11-01 predicting +10%: realised +10% on
    # the last observed day inside the horizon — rose, favourable
    row = _outcome_row(
        store, "desk",
        _signal("fixture_grain", "fixture_market", date(2025, 11, 1), "buy_now"),
        pack,
    )
    assert row.state == "graded"
    assert row.realised_date == date(2025, 12, 1)
    assert row.realised_drift_pct == 10.0
    assert row.drift_error_pct == 0.0
    assert row.move == "rose" and row.favourable is True
    # the same path graded against a wait call: waiting lost money
    row = _outcome_row(
        store, "desk",
        _signal("fixture_grain", "fixture_market", date(2025, 11, 1), "wait",
                drift=-5.0),
        pack,
    )
    assert row.move == "rose" and row.favourable is False


def test_outcome_row_names_an_unlanded_horizon_pending(tmp_path):
    store = build_store(str(tmp_path / "pending.db"))
    store.insert_observations(
        [
            Observation(commodity="fixture_grain", market="fixture_market",
                        obs_date=date(2025, 12, 31), driver="modal_price",
                        value=2000.0),
        ]
    )
    row = _outcome_row(
        store, "desk",
        _signal("fixture_grain", "fixture_market", date(2025, 12, 31), "buy_now"),
        load_signal_pack(),
    )
    assert row.state == "pending"
    assert row.favourable is None and row.move is None
    assert "2026-01-30" in row.reason and "pending" in row.reason


# --- the full report over the planted dataset -----------------------------------


def test_report_sections_over_the_graded_store(graded):
    store, _ = graded
    svc = AnalyticsService(store)
    report = svc.build_report()

    # trends: 14 series x 3 horizons; only coffee is insufficient
    assert len(report.trends) == 42
    insufficient = [r for r in report.trends if r.direction == "insufficient_history"]
    assert {r.commodity for r in insufficient} == {"coffee"}
    assert len(insufficient) == 3
    for row in report.trends:
        if row.direction != "insufficient_history":
            assert len(row.early_origins) == 3 and len(row.late_origins) == 3
            assert row.ledger_record_id is not None

    # grid outcomes: one per strikable origin, all landed by Dec
    grid = [r for r in report.signal_outcomes if r.population == "backtest_grid"]
    assert len(grid) == 135
    assert all(r.state == "graded" for r in grid)
    assert {r.value for r in grid} == {"buy_now", "phased", "wait"}
    assert len(report.origin_signal_skips) == 5
    assert {s.commodity for s in report.origin_signal_skips} == {"coffee"}

    # transmission: the three planted classes measure one event
    # each and are named small samples; empty classes named too
    by_class = {r.event_class: r for r in report.transmission}
    assert len(by_class) == 6
    for cls in ("tariff_change", "export_restriction", "weather_shock"):
        row = by_class[cls]
        assert row.n_events == 1 and row.n_measurable == 1
        assert row.verified_count == 1 and row.unverified_count == 0
        assert row.sample_state == "small_sample"
        assert "small sample" in row.note
    for cls in ("import_policy", "logistics_disruption", "demand_shock"):
        assert by_class[cls].sample_state == "no_measurable_events"
        assert by_class[cls].mean_signed_error is None
    assert set(report.small_sample_classes) == set(by_class)

    # shock windows: the 2024 ban was never inside a scored
    # window; the tariff and the drought grade against their rests
    ban_rows = [r for r in report.shock_windows if r.event_class == "export_restriction"]
    assert len(ban_rows) == 6
    assert all(r.state == "no_shock_window_days" for r in ban_rows)
    assert all(r.shock_mape is None for r in ban_rows)
    graded_shock = [r for r in report.shock_windows if r.state == "graded"]
    assert len(graded_shock) == 12
    assert all(r.shock_n_days > 0 and r.delta_mape_pp is not None for r in graded_shock)

    assert verify_report(store, report) == []
    assert svc.build_report().report_id == report.report_id


def test_report_names_a_stored_desk_signal_pending(graded, tmp_path):
    # a copy of the graded store, so the shared fixture's
    # artefact set (and its stored report) stays untouched
    import shutil

    _, db = graded
    copy_db = str(tmp_path / "copy.db")
    shutil.copy(db, copy_db)
    store = build_store(copy_db)
    # a desk signal struck at the last history day: its horizon
    # lands in the sealed future — pending, named, never graded
    signal = _signal("wheat", "delhi_khari_baoli", date(2025, 12, 31), "buy_now")
    store.insert_buy_signal(signal)
    report = AnalyticsService(store).build_report()
    desk = [r for r in report.signal_outcomes if r.population == "desk"]
    assert len(desk) == 1
    assert desk[0].state == "pending" and desk[0].favourable is None
    assert verify_report(store, report) == []


def test_tampered_report_is_flagged(graded):
    store, db = graded
    report = AnalyticsService(store).build_report()
    conn = sqlite3.connect(db)
    payload = json.loads(
        conn.execute(
            "SELECT payload FROM ops_reports WHERE report_id = ?",
            (report.report_id,),
        ).fetchone()[0]
    )
    payload["trends"][0]["late_mape"] = 99.0
    conn.execute(
        "UPDATE ops_reports SET payload = ? WHERE report_id = ?",
        (json.dumps(payload), report.report_id),
    )
    conn.commit()
    conn.close()
    problems = verify_report(store, store.get_ops_report(report.report_id))
    assert problems
    assert any("content id mismatch" in p for p in problems)
    assert any("re-performance mismatch" in p for p in problems)


# --- surfaces ---------------------------------------------------------------------


def test_api_analytics_surface(graded):
    store, _ = graded
    client = TestClient(create_app(store))
    pack = client.get("/analytics/pack")
    assert pack.status_code == 200
    assert pack.json()["version"] == "2026.10.1"

    built = client.post("/analytics/reports")
    assert built.status_code == 201
    body = built.json()
    assert body["problems"] == []
    report_id = body["report_id"]

    listed = client.get("/analytics/reports")
    assert [r["report_id"] for r in listed.json()["reports"]] == [report_id]

    fetched = client.get(f"/analytics/reports/{report_id}")
    assert fetched.status_code == 200
    assert fetched.json()["report_id"] == report_id

    verified = client.get(f"/analytics/reports/{report_id}/verify")
    assert verified.json() == {"report_id": report_id, "problems": []}

    missing = client.get("/analytics/reports/OPS-nope")
    assert missing.status_code == 404


def test_cli_pack_and_reports(graded, capsys):
    _, db = graded
    assert analytics_cli.main(["--db", db, "pack"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["version"] == "2026.10.1"
    # the report stored by the earlier builds on this fixture
    assert analytics_cli.main(["--db", db, "reports"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out) == 1 and out[0]["report_id"].startswith("OPS-")
    assert analytics_cli.main(["--db", db, "verify", "--all"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"scope": "all", "problems": []}


# --- Postgres parity -----------------------------------------------------------------

PG_URL = os.environ.get("FMCG_TEST_DATABASE_URL")


@pytest.mark.skipif(not PG_URL, reason="FMCG_TEST_DATABASE_URL not set")
def test_postgres_parity(tmp_path):
    lite = build_store(str(tmp_path / "lite.db"))
    lite_truth = build_truth_store(str(tmp_path / "lite.db"))
    load_dataset(lite, lite_truth, SEED)
    run_all(lite)
    EventService(lite).seed_historical(lite.get_manifest())
    lite_report = AnalyticsService(lite).build_report()

    pg_store = build_store(database_url=PG_URL)
    try:
        pg_truth = build_truth_store(database_url=PG_URL)
        load_dataset(pg_store, pg_truth, SEED)
        run_all(pg_store)
        EventService(pg_store).seed_historical(pg_store.get_manifest())
        pg_report = AnalyticsService(pg_store).build_report()
        assert pg_report.model_dump(mode="json") == lite_report.model_dump(mode="json")
        assert verify_report(pg_store, pg_report) == []
    finally:
        pg_store.close()
