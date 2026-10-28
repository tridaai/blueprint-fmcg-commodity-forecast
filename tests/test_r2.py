"""Round 2 tests: forecast engine, decomposition, gate, commentary."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.api import create_app
from fmcg_forecast.forecast.engine import (
    EventAdjustment,
    InsufficientHistoryError,
    SealedWindowRefusal,
    run_engine,
)
from fmcg_forecast.forecast.service import (
    ApprovalStateError,
    ApprovalValidationError,
    CommentaryVerificationError,
    ForecastService,
)
from fmcg_forecast.forecast.verify import verify_forecast
from fmcg_forecast.modelport import OfflineModel
from fmcg_forecast.store import build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset

AS_OF = date(2025, 12, 31)


@pytest.fixture(scope="module")
def loaded(tmp_path_factory):
    db = str(tmp_path_factory.mktemp("r2") / "test.db")
    store = build_store(db)
    truth = build_truth_store(db)
    load_dataset(store, truth, 20261027)
    return store, db


@pytest.fixture()
def service(loaded):
    store, _ = loaded
    return ForecastService(store, OfflineModel())


@pytest.fixture(scope="module")
def wheat(loaded):
    store, _ = loaded
    return ForecastService(store, OfflineModel()).run_forecast(
        "wheat", "delhi_khari_baoli"
    )


# --- the engine ---------------------------------------------------------


def test_forecast_shape(wheat):
    assert wheat.status == "draft"
    assert len(wheat.days) == 90
    assert wheat.days[0].forecast_date == date(2026, 1, 1)
    assert wheat.days[-1].forecast_date == date(2026, 3, 31)
    assert [s.horizon_days for s in wheat.horizons_summary] == [7, 30, 90]
    assert [line.driver for line in wheat.lines] == [
        "arrivals",
        "stock_level",
        "trade_flow",
        "weather_index",
        "events",
    ]


def test_decomposition_sums_exactly(wheat):
    for day in wheat.days:
        parts = day.baseline + sum(day.contributions.values()) + day.events_adjustment
        assert abs(parts - day.p50) <= 0.011
    assert verify_forecast(wheat) == []


def test_intervals_bracket_the_point_forecast(loaded):
    store, _ = loaded
    manifest = store.get_manifest()
    for commodity, market in (("soybean", "indore"), ("chili", "guntur")):
        forecast = run_engine(store, manifest, commodity, market, AS_OF)
        assert all(d.p10 <= d.p50 <= d.p90 for d in forecast.days)
        assert verify_forecast(forecast) == []


def test_arrivals_pressure_signs_in_the_harvest_window(loaded):
    store, _ = loaded
    manifest = store.get_manifest()
    forecast = run_engine(store, manifest, "wheat", "delhi_khari_baoli", date(2025, 4, 15))
    arrivals = next(line for line in forecast.lines if line.driver == "arrivals")
    # planted: arrivals surge at harvest presses prices down
    assert arrivals.coefficient < 0
    assert arrivals.input_summary["last_input"] > 0  # surge in progress at as_of
    assert arrivals.at_horizon["7"] < 0


def test_sealed_window_refused_without_backtest_path(loaded):
    store, _ = loaded
    manifest = store.get_manifest()
    with pytest.raises(SealedWindowRefusal):
        run_engine(store, manifest, "wheat", "indore", date(2026, 2, 1))
    via = run_engine(store, manifest, "wheat", "indore", date(2026, 2, 1), via_backtest=True)
    assert len(via.days) == 90


def test_insufficient_history_refused(loaded):
    store, _ = loaded
    manifest = store.get_manifest()
    with pytest.raises(InsufficientHistoryError):
        run_engine(store, manifest, "wheat", "indore", date(2023, 6, 1))


def test_events_slot_is_empty_by_default_and_applies_when_filled(loaded):
    store, _ = loaded
    manifest = store.get_manifest()
    plain = run_engine(store, manifest, "cumin", "unjha", AS_OF)
    assert all(d.events_adjustment == 0.0 for d in plain.days)
    assert plain.method.events_applied == []

    shocked = run_engine(
        store,
        manifest,
        "cumin",
        "unjha",
        AS_OF,
        event_adjustments=[EventAdjustment(event_id="EVT-TEST", path=[0.10] * 90)],
    )
    assert shocked.days[0].events_adjustment > 0
    assert shocked.method.events_applied == ["EVT-TEST"]
    assert verify_forecast(shocked) == []


# --- coffee: thin data, honestly -----------------------------------------


def test_coffee_names_gaps_and_widens(loaded, wheat):
    store, _ = loaded
    manifest = store.get_manifest()
    coffee = run_engine(store, manifest, "coffee", "bengaluru", AS_OF)
    assert coffee.missing_drivers == ["stock_level", "import_flow", "export_flow"]
    assert [line.driver for line in coffee.lines] == ["arrivals", "weather_index", "events"]
    # the stated sparsity rule separates the two series decisively
    assert coffee.method.sparsity.multiplier >= 1.5 * wheat.method.sparsity.multiplier
    c30 = next(s for s in coffee.horizons_summary if s.horizon_days == 30)
    w30 = next(s for s in wheat.horizons_summary if s.horizon_days == 30)
    assert (c30.p90 - c30.p10) / c30.p50 > (w30.p90 - w30.p10) / w30.p50
    assert verify_forecast(coffee) == []


# --- service: idempotency, tamper, gate, commentary -----------------------


def test_run_is_idempotent(service):
    first = service.run_forecast("groundnut", "gondal")
    second = service.run_forecast("groundnut", "gondal")
    assert first.forecast_id == second.forecast_id
    assert len(service.list_forecasts("groundnut", "gondal")) == 1


def test_tampered_stored_forecast_fails_verification(loaded):
    store, db = loaded
    service = ForecastService(store, OfflineModel())
    forecast = service.run_forecast("groundnut", "rajkot")
    assert service.verify_stored(forecast.forecast_id) == []

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT payload FROM forecasts WHERE forecast_id = ?", (forecast.forecast_id,)
    ).fetchone()
    payload = json.loads(row[0])
    payload["days"][5]["p50"] += 250.0
    conn.execute(
        "UPDATE forecasts SET payload = ? WHERE forecast_id = ?",
        (json.dumps(payload), forecast.forecast_id),
    )
    conn.commit()
    conn.close()

    problems = service.verify_stored(forecast.forecast_id)
    assert any("does not sum" in p for p in problems)
    assert any("content id mismatch" in p for p in problems)


def test_approval_gate(service):
    forecast = service.run_forecast("soybean", "indore")
    assert forecast.status == "draft"
    with pytest.raises(ApprovalValidationError):
        service.approve(forecast.forecast_id, "unknown", "Head of Desk", date(2026, 1, 2))
    with pytest.raises(ApprovalValidationError):
        service.approve(forecast.forecast_id, "r.menon", " ", date(2026, 1, 2))
    approval = service.approve(
        forecast.forecast_id, "r.menon", "Head of Trading Desk", date(2026, 1, 2)
    )
    assert approval.forecast_id == forecast.forecast_id
    assert service.get_forecast(forecast.forecast_id).status == "official"
    assert service.get_approval(forecast.forecast_id).approver == "r.menon"
    with pytest.raises(ApprovalStateError):
        service.approve(forecast.forecast_id, "s.khan", "Desk Head", date(2026, 1, 3))


class _LyingModel:
    profile_name = "lying"

    def draft_commentary(self, *, subject, figures):
        return f"{subject}. P50 at 30 days (INR/quintal): 9999.99."


def test_commentary_figures_verify_and_lying_drafts_are_refused(loaded, wheat):
    store, _ = loaded
    service = ForecastService(store, OfflineModel())
    commentary = service.draft_commentary(wheat.forecast_id)
    assert commentary.model_profile == "offline"
    assert f"{wheat.horizons_summary[1].p50:.2f}" in commentary.text

    lying = ForecastService(store, _LyingModel())
    target = lying.run_forecast("basmati_rice", "karnal")
    with pytest.raises(CommentaryVerificationError):
        lying.draft_commentary(target.forecast_id)
    assert store.get_commentary(target.forecast_id) is None


# --- API -------------------------------------------------------------------


@pytest.fixture(scope="module")
def client(loaded):
    store, _ = loaded
    return TestClient(create_app(store, OfflineModel()))


def test_api_forecast_flow(client):
    r = client.post("/forecasts/run", json={"commodity": "wheat", "market": "indore"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "draft" and len(body["days"]) == 90
    fid = body["forecast_id"]

    r = client.get(f"/forecasts/{fid}/contributions")
    assert r.status_code == 200 and len(r.json()["lines"]) == 5
    r = client.get(f"/forecasts/{fid}/verify")
    assert r.status_code == 200 and r.json()["problems"] == []
    r = client.post(f"/forecasts/{fid}/commentary")
    assert r.status_code == 200 and r.json()["forecast_id"] == fid
    r = client.get("/forecasts", params={"commodity": "wheat"})
    assert any(f["forecast_id"] == fid for f in r.json()["forecasts"])
    assert client.get("/forecasts/FCST-nope").status_code == 404


def test_api_approval_and_refusals(client):
    r = client.post("/forecasts/run", json={"commodity": "chili", "market": "guntur"})
    fid = r.json()["forecast_id"]
    r = client.post(
        f"/forecasts/{fid}/approve",
        json={"approver": "tbd", "role": "Head of Trading Desk", "decided_on": "2026-01-02"},
    )
    assert r.status_code == 422
    r = client.post(
        f"/forecasts/{fid}/approve",
        json={"approver": "r.menon", "role": "Head of Trading Desk", "decided_on": "2026-01-02"},
    )
    assert r.status_code == 200 and r.json()["approver"] == "r.menon"
    r = client.post(
        f"/forecasts/{fid}/approve",
        json={"approver": "s.khan", "role": "Desk Head", "decided_on": "2026-01-03"},
    )
    assert r.status_code == 409
    r = client.get(f"/forecasts/{fid}/approval")
    assert r.status_code == 200 and r.json()["decided_on"] == "2026-01-02"


def test_api_sealed_window_is_403(client):
    r = client.post(
        "/forecasts/run",
        json={"commodity": "wheat", "market": "indore", "as_of": "2026-02-01"},
    )
    assert r.status_code == 403
    r = client.post(
        "/forecasts/run",
        json={"commodity": "wheat", "market": "indore", "as_of": "2023-06-01"},
    )
    assert r.status_code == 422
