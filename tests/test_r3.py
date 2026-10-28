"""Round 3 tests: backtest metrics, the accuracy ledger, the flag.

The metric fixtures are worked by hand in the comments — the sums
are the primitive record, and every expected figure below is
derived from them by the stated formulas, not copied from a run.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.api import create_app
from fmcg_forecast.backtest import metrics
from fmcg_forecast.backtest.harness import (
    monthly_origins,
    run_all,
    score_sealed_boundary,
)
from fmcg_forecast.backtest.pack import ACCURACY_PACK_V1, load_accuracy_pack
from fmcg_forecast.backtest.verify import (
    verify_accuracy_record,
    verify_backtest_result,
)
from fmcg_forecast.forecast.models import BacktestResult
from fmcg_forecast.forecast.service import ForecastService
from fmcg_forecast.forecast.verify import verify_forecast
from fmcg_forecast.modelport import OfflineModel
from fmcg_forecast.store import build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset

SEED = 20261027


@pytest.fixture(scope="module")
def plain(tmp_path_factory):
    """A loaded store with NO backtests run against it."""
    db = str(tmp_path_factory.mktemp("r3plain") / "test.db")
    store = build_store(db)
    truth = build_truth_store(db)
    load_dataset(store, truth, SEED)
    return store, truth, db


@pytest.fixture(scope="module")
def graded(tmp_path_factory):
    """A loaded store with the harness run and the ledger built."""
    db = str(tmp_path_factory.mktemp("r3graded") / "test.db")
    store = build_store(db)
    truth = build_truth_store(db)
    load_dataset(store, truth, SEED)
    report, records = run_all(store)
    return store, truth, db, report, records


# --- the pack -------------------------------------------------------------


def test_pack_grid_is_the_stated_one():
    pack = load_accuracy_pack()
    assert pack.version == "2026.10.1"
    assert pack.horizons_days == [7, 30, 90]
    assert pack.ledger_window_origins == 6
    assert pack.degraded_mape_pct == 5.0
    origins = monthly_origins(pack)
    assert origins[0] == date(2025, 1, 1) and origins[-1] == date(2025, 10, 1)
    assert len(origins) == 10
    with pytest.raises(ValueError):
        load_accuracy_pack("1900.1")


# --- metrics, worked by hand ------------------------------------------------
#
# Four scored days, band (180, 200, 220) throughout:
#   210 -> err +10, |err| 10, pct 10/210 = 1/21, covered
#   190 -> err -10, |err| 10, pct 10/190 = 1/19, covered
#   200 -> err   0, covered
#   250 -> err +50, |err| 50, pct 50/250 = 1/5, NOT covered (250 > 220)
# A fifth forecast day has no realised observation and is excluded.
# By hand: n=4, covered=3, sum_err = 10 - 10 + 0 + 50 = 50,
# sum_abs_err=70, sum_abs_pct = 1/21 + 1/19 + 0 + 1/5 = 599/1995,
# mae = 70/4 = 17.5, bias = 50/4 = 12.5, coverage = 3/4 = 0.75,
# mape = 100 * (599/1995) / 4 (from the sum rounded to 6dp).


def test_score_days_hand_computed():
    days = [
        (date(2025, 1, 2), 180.0, 200.0, 220.0),
        (date(2025, 1, 3), 180.0, 200.0, 220.0),
        (date(2025, 1, 4), 180.0, 200.0, 220.0),
        (date(2025, 1, 5), 180.0, 200.0, 220.0),
        (date(2025, 1, 6), 180.0, 200.0, 220.0),  # no realised -> excluded
    ]
    realised = {
        date(2025, 1, 2): 210.0,
        date(2025, 1, 3): 190.0,
        date(2025, 1, 4): 200.0,
        date(2025, 1, 5): 250.0,
    }
    scored, sums = metrics.score_days(days, realised)
    assert len(scored) == 4
    exact_pct = Fraction(1, 21) + Fraction(1, 19) + Fraction(1, 5)
    assert exact_pct == Fraction(599, 1995)
    expected_sum_pct = round(float(exact_pct), 6)
    assert sums["n_days"] == 4 and sums["covered_days"] == 3
    assert sums["sum_err"] == 50.0 and sums["sum_abs_err"] == 70.0
    assert sums["sum_abs_pct"] == expected_sum_pct
    assert sums["mae"] == 17.5 and sums["bias"] == 12.5
    assert sums["coverage"] == 0.75
    assert sums["mape"] == round(100.0 * expected_sum_pct / 4, 4)


def _make_result(origin: date, rows, realised) -> BacktestResult:
    scored, sums = metrics.score_days(rows, realised)
    result = BacktestResult(
        result_id="BT-pending",
        commodity="toy",
        market="toy_market",
        origin=origin,
        horizon_days=30,
        forecast_id="FCST-toy",
        engine_version="1.0.0",
        pack_version=ACCURACY_PACK_V1.version,
        days=scored,
        n_days=sums["n_days"],
        covered_days=sums["covered_days"],
        sum_err=sums["sum_err"],
        sum_abs_err=sums["sum_abs_err"],
        sum_abs_pct=sums["sum_abs_pct"],
        mae=sums["mae"],
        mape=sums["mape"],
        bias=sums["bias"],
        coverage=sums["coverage"],
    )
    result.result_id = metrics.result_content_id(result)
    return result


def _band_rows(origin: date, p50: float, width: float = 100.0):
    day = origin + timedelta(days=1)
    return [(day, p50 - width, p50, p50 + width)], day


# Three origins, worked by hand (band half-width 100 around p50):
#   A 2025-01-01: realised 1100 vs p50 1000 -> err +100, pct 1/11, covered
#   B 2025-02-01: realised 950 (err -50, pct 1/19) and 1050 (err +50,
#      pct 1/21), both covered
#   C 2025-03-01: realised 2200 vs p50 2000 (band to 2100) -> err +200,
#      pct 1/11, NOT covered
# Window 2 pools B + C: n=3, sum_err=200, sum_abs_err=300,
# sum_abs_pct = 1/19 + 1/21 + 1/11 (each stored rounded to 6dp first),
# mae = 100.0, bias = 200/3, coverage = 2/3, mape ~ 6.37 -> degraded.
def test_aggregation_pools_the_recent_window_by_hand():
    rows_a, day_a = _band_rows(date(2025, 1, 1), 1000.0)
    a = _make_result(date(2025, 1, 1), rows_a, {day_a: 1100.0})
    rows_b1, day_b1 = _band_rows(date(2025, 2, 1), 1000.0)
    rows_b2 = [(date(2025, 2, 3), 900.0, 1000.0, 1100.0)]
    b = _make_result(
        date(2025, 2, 1), rows_b1 + rows_b2, {day_b1: 950.0, date(2025, 2, 3): 1050.0}
    )
    rows_c, day_c = _band_rows(date(2025, 3, 1), 2000.0)
    c = _make_result(date(2025, 3, 1), rows_c, {day_c: 2200.0})

    pack = ACCURACY_PACK_V1.model_copy(update={"ledger_window_origins": 2})
    record = metrics.aggregate_results([a, b, c], pack)
    assert record.origins == [date(2025, 2, 1), date(2025, 3, 1)]
    assert record.n_results == 2 and record.n_days == 3
    assert record.covered_days == 2
    assert record.mae == 100.0
    assert record.bias == round(200 / 3, 4)
    # the pooled percentage sum, from the per-result sums as stored
    # (each rounded to 6dp before pooling, per the stated rule)
    pooled_pct = round(b.sum_abs_pct + c.sum_abs_pct, 6)
    exact_pct = Fraction(1, 19) + Fraction(1, 21) + Fraction(1, 11)
    assert pooled_pct == pytest.approx(float(exact_pct), abs=1e-6)
    assert record.mape == round(100.0 * pooled_pct / 3, 4)
    assert record.coverage == round(2 / 3, 4)
    assert record.degraded is True  # mape ~6.37 > the pack's 5.0 bar
    assert verify_accuracy_record(record, [a, b, c], pack) == []

    rows_d, day_d = _band_rows(date(2025, 4, 1), 1000.0)
    d = _make_result(date(2025, 4, 1), rows_d, {day_d: 1010.0})
    calm_record = metrics.aggregate_results([d], ACCURACY_PACK_V1)
    assert calm_record.mape < 5.0 and calm_record.degraded is False


def test_result_and_record_tamper_is_detected():
    rows, day = _band_rows(date(2025, 1, 1), 1000.0)
    result = _make_result(date(2025, 1, 1), rows, {day: 1100.0})
    assert verify_backtest_result(result) == []
    tampered = result.model_copy(deep=True)
    tampered.mape += 1.0
    problems = verify_backtest_result(tampered)
    assert any("content id mismatch" in p for p in problems)
    assert any("mape does not re-perform" in p for p in problems)

    record = metrics.aggregate_results([result], ACCURACY_PACK_V1)
    assert verify_accuracy_record(record, [result], ACCURACY_PACK_V1) == []
    drifted = record.model_copy(deep=True)
    drifted.mae += 5.0
    problems = verify_accuracy_record(drifted, [result], ACCURACY_PACK_V1)
    assert any("mae drifts" in p for p in problems)


# --- the harness over the real dataset --------------------------------------


def test_harness_grid_and_skips(graded):
    _, _, _, report, records = graded
    assert report.engine_runs == 135
    assert report.results_stored == 405
    assert len(report.skipped) == 5
    assert {s["commodity"] for s in report.skipped} == {"coffee"}
    assert {s["origin"] for s in report.skipped} == {
        "2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01", "2025-05-01",
    }
    assert all("observed price days" in s["reason"] for s in report.skipped)
    assert len(records) == 42


def test_every_stored_result_verifies(graded):
    store, _, _, _, _ = graded
    results = store.list_backtest_results()
    assert len(results) == 405
    problems = sum((verify_backtest_result(r) for r in results), [])
    assert problems == []


def test_ledger_reperforms_from_results(graded):
    store, _, _, _, records = graded
    pack = load_accuracy_pack()
    for record in records:
        results = store.list_backtest_results(
            record.commodity, record.market, record.horizon_days
        )
        assert verify_accuracy_record(record, results, pack) == []


def test_degraded_is_exactly_the_planted_noisy_series(graded):
    store, _, _, _, records = graded
    degraded = {
        (r.commodity, r.market, r.horizon_days) for r in records if r.degraded
    }
    assert degraded == {("chili", "guntur", 30), ("chili", "guntur", 90)}
    for record in records:
        assert record.degraded == (record.mape > 5.0)
    chili30 = store.get_accuracy_record("chili", "guntur", 30)
    assert chili30.mape == pytest.approx(5.1601, abs=1e-4)
    coffee = store.get_accuracy_record("coffee", "bengaluru", 30)
    assert coffee.n_results == 5
    assert coffee.origins[0] == date(2025, 6, 1)


def test_stored_result_tamper_is_detected(graded):
    store, _, db, _, _ = graded
    result = store.list_backtest_results("wheat", "indore", 7)[0]
    assert verify_backtest_result(result) == []
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT payload FROM backtest_results WHERE result_id = ?",
        (result.result_id,),
    ).fetchone()
    payload = json.loads(row[0])
    payload["mape"] += 2.5
    conn.execute(
        "UPDATE backtest_results SET payload = ? WHERE result_id = ?",
        (json.dumps(payload), result.result_id),
    )
    conn.commit()
    conn.close()
    problems = verify_backtest_result(store.get_backtest_result(result.result_id))
    assert any("content id mismatch" in p for p in problems)
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE backtest_results SET payload = ? WHERE result_id = ?",
        (row[0], result.result_id),
    )
    conn.commit()
    conn.close()
    assert verify_backtest_result(store.get_backtest_result(result.result_id)) == []


# --- forecasts carry the accuracy -------------------------------------------


def test_unmeasured_is_named_before_any_backtest(plain):
    store, _, _ = plain
    service = ForecastService(store, OfflineModel())
    forecast = service.run_forecast("soybean", "nagpur")
    assert forecast.accuracy is not None
    assert forecast.accuracy.state == "unmeasured"
    assert all(s.state == "unmeasured" for s in forecast.accuracy.per_horizon)
    assert "unmeasured" in forecast.accuracy.note
    assert verify_forecast(forecast) == []
    commentary = service.draft_commentary(forecast.forecast_id)
    assert "Backtest accuracy state: unmeasured" in commentary.text


def test_forecast_pins_the_ledger_and_the_flag(graded):
    store, _, _, _, _ = graded
    service = ForecastService(store, OfflineModel())
    chili = service.run_forecast("chili", "guntur")
    assert chili.accuracy.state == "degraded"
    by_horizon = {s.horizon_days: s for s in chili.accuracy.per_horizon}
    assert by_horizon[30].state == "degraded" and by_horizon[90].state == "degraded"
    assert by_horizon[7].state == "measured"
    record = store.get_accuracy_record("chili", "guntur", 30)
    assert by_horizon[30].record_id == record.record_id
    assert by_horizon[30].mape == record.mape
    assert "degraded" in chili.accuracy.note
    assert verify_forecast(chili) == []

    wheat = service.run_forecast("wheat", "delhi_khari_baoli")
    assert wheat.accuracy.state == "measured"
    assert all(s.state == "measured" for s in wheat.accuracy.per_horizon)

    commentary = service.draft_commentary(chili.forecast_id)
    assert "Backtest accuracy state: degraded" in commentary.text
    assert f"{record.mape:.2f}" in commentary.text


def test_the_flag_cannot_be_suppressed(graded):
    store, _, _, _, _ = graded
    service = ForecastService(store, OfflineModel())
    chili = service.run_forecast("chili", "guntur")
    view = service.accuracy_view(chili.forecast_id)
    assert view["accuracy"]["state"] == "degraded"

    client = TestClient(create_app(store, OfflineModel()))
    for params in ({"view": "clean"}, {"accuracy": "off"}, {"flag": "none"}):
        r = client.get(f"/forecasts/{chili.forecast_id}", params=params)
        assert r.status_code == 200
        assert r.json()["accuracy"]["state"] == "degraded"
    r = client.get(f"/forecasts/{chili.forecast_id}/accuracy")
    assert r.json()["accuracy"]["state"] == "degraded"


# --- the sealed-boundary dry run ---------------------------------------------


def test_sealed_boundary_scores_against_truth(graded):
    store, truth, _, _, _ = graded
    service = ForecastService(store, OfflineModel())
    for commodity, market in (("wheat", "delhi_khari_baoli"), ("coffee", "bengaluru")):
        forecast = service.run_forecast(commodity, market)
        rows = truth.read_truth(commodity, market, "modal_price")
        scores = score_sealed_boundary(forecast, rows)
        assert set(scores) == {7, 30, 90}
        for horizon, sums in scores.items():
            assert sums["n_days"] > 0, (commodity, horizon)
            assert sums["mape"] < 10.0, (commodity, horizon, sums)
            assert sums["coverage"] >= 0.8, (commodity, horizon, sums)


# --- API ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def client(graded):
    store, _, _, _, _ = graded
    return TestClient(create_app(store, OfflineModel()))


def test_api_accuracy_reads(client):
    r = client.get("/accuracy")
    assert r.status_code == 200 and len(r.json()["records"]) == 42
    r = client.get("/accuracy/chili/guntur/30")
    assert r.status_code == 200 and r.json()["degraded"] is True
    r = client.get("/accuracy/chili/guntur/7")
    assert r.status_code == 200 and r.json()["degraded"] is False
    assert client.get("/accuracy/nope/x/30").status_code == 404

    r = client.get("/backtests", params={"commodity": "coffee"})
    assert r.status_code == 200 and len(r.json()["results"]) == 15
    result_id = r.json()["results"][0]["result_id"]
    r = client.get(f"/backtests/{result_id}")
    assert r.status_code == 200 and r.json()["result_id"] == result_id
    assert client.get("/backtests/BT-nope").status_code == 404


def test_api_backtest_run_is_idempotent(client):
    r = client.post("/backtests/run", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["results_stored"] == 0
    assert body["results_already_on_record"] == 405
    assert body["ledger_records"] == 42
    assert {(d["commodity"], d["market"], d["horizon_days"]) for d in body["degraded_records"]} == {
        ("chili", "guntur", 30), ("chili", "guntur", 90),
    }
    r = client.post("/backtests/run", json={"pack_version": "1900.1"})
    assert r.status_code == 400
