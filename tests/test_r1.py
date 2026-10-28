"""Round 1 tests: generator, store, truth isolation, model port, API."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.api import create_app
from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.config import Settings
from fmcg_forecast.generator import _operating_days, generate_dataset
from fmcg_forecast.modelport import ModelNotConfiguredError, build_model_port
from fmcg_forecast.store import build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset


@pytest.fixture(scope="module")
def data():
    return generate_dataset()


@pytest.fixture()
def loaded(tmp_path):
    db = str(tmp_path / "test.db")
    store = build_store(db)
    truth = build_truth_store(db)
    state = load_dataset(store, truth, 20261027)
    return store, truth, state


# --- generator --------------------------------------------------------


def test_generator_is_deterministic(data):
    again = generate_dataset()
    assert again.manifest.history_digest == data.manifest.history_digest
    assert len(again.history) == len(data.history)
    assert len(again.future) == len(data.future)


def test_history_future_split(data):
    assert all(r.obs_date <= date(2025, 12, 31) for r in data.history)
    assert all(date(2026, 1, 1) <= r.obs_date <= date(2026, 3, 31) for r in data.future)
    assert data.manifest.history_rows == len(data.history)
    assert data.manifest.future_rows == len(data.future)
    # the future window is exactly 90 calendar days of truth
    future_days = {r.obs_date for r in data.future if r.commodity == "wheat"}
    assert len(future_days) == len(
        _operating_days(BY_NAME["wheat"], date(2026, 1, 1), date(2026, 3, 31))
    )


def test_manifest_states_the_planted_structure(data):
    m = data.manifest
    kinds = {e.kind for e in m.events}
    assert kinds == {"tariff_shock", "export_ban"}
    assert {b.commodity for b in m.trend_breaks} == {"soybean", "wheat"}
    assert m.coffee_disruption_reporting_days_lost == 6
    coffee = next(c for c in m.commodities if c.commodity == "coffee")
    assert coffee.missing_drivers == ["stock_level", "import_flow", "export_flow"]


def test_coffee_is_sparse_as_planted(data):
    m = data.manifest
    in_window = [
        r
        for r in data.history
        if r.commodity == "coffee"
        and m.coffee_disruption_start <= r.obs_date <= m.coffee_disruption_end
    ]
    assert in_window == []
    coffee_days = {r.obs_date for r in data.history if r.commodity == "coffee"}
    full = _operating_days(BY_NAME["coffee"], m.history_start, m.history_end)
    assert len(coffee_days) == len(full) - 6
    assert {r.driver for r in data.history if r.commodity == "coffee"} == {
        "modal_price",
        "arrivals",
        "weather_index",
    }


def test_no_sunday_observations(data):
    assert all(r.obs_date.weekday() != 6 for r in data.history)


# --- store --------------------------------------------------------------


def test_store_roundtrip(loaded):
    store, _, _ = loaded
    rows = store.series("wheat", "indore", "modal_price", date(2025, 1, 1), date(2025, 1, 31))
    assert len(rows) > 20
    assert all(r.commodity == "wheat" and r.driver == "modal_price" for r in rows)
    manifest = store.get_manifest()
    assert manifest is not None and manifest.seed == 20261027
    assert len(store.list_events()) == 2
    event = store.get_event("EVT-2025-TARIFF-SOYBEAN")
    assert event is not None and event.magnitude == 0.16


def test_observations_are_insert_only(loaded):
    store, _, _ = loaded
    row = store.series("wheat", "indore", "modal_price", date(2025, 1, 2), date(2025, 1, 2))[0]
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_observations([row])


def test_load_is_idempotent_at_workflow_level(loaded):
    store, truth, _ = loaded
    before = sum(store.row_counts().values())
    state = load_dataset(store, truth, 20261027)
    assert state["already_loaded"] is True
    assert state["history_rows_written"] == 0
    assert sum(store.row_counts().values()) == before


def test_migrations_are_idempotent(tmp_path):
    store = build_store(str(tmp_path / "m.db"))
    assert store.migrate() == []


def test_truth_store_holds_only_the_future(loaded, data):
    _, truth, _ = loaded
    assert truth.count() == data.manifest.future_rows
    rows = truth.read_truth("wheat", "indore", "modal_price")
    assert rows and all(r.obs_date >= date(2026, 1, 1) for r in rows)


# --- truth isolation ------------------------------------------------------


def test_forecast_package_never_imports_truth():
    import ast
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "src" / "fmcg_forecast" / "forecast"
    offenders = []
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(n == "fmcg_forecast.truth" or n.endswith(".truth") for n in names):
                offenders.append(str(path))
    assert offenders == []


# --- model port -----------------------------------------------------------


def test_offline_model_port_is_deterministic():
    port = build_model_port(Settings(model_profile="offline"))
    text = port.draft_commentary(subject="Wheat", figures={"price": "2450"})
    assert "Wheat" in text and "2450" in text


@pytest.mark.parametrize(
    "profile",
    ["anthropic", "bedrock", "nim"],
)
def test_hosted_profiles_refuse_until_configured(profile):
    with pytest.raises(ModelNotConfiguredError):
        build_model_port(Settings(model_profile=profile))


def test_unknown_profile_refuses():
    with pytest.raises(ModelNotConfiguredError):
        build_model_port(Settings(model_profile="carrier-pigeon"))


# --- API -------------------------------------------------------------------


@pytest.fixture()
def client(loaded):
    store, _, _ = loaded
    return TestClient(create_app(store))


def test_api_health_and_readiness(client):
    assert client.get("/health").json() == {"status": "ok"}
    body = client.get("/readiness").json()
    assert body["status"] == "ready" and body["history_rows"] > 0


def test_api_series_read(client):
    r = client.get(
        "/series",
        params={
            "commodity": "soybean",
            "market": "indore",
            "driver": "modal_price",
            "start": "2025-06-01",
            "end": "2025-06-30",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["unit"] == "INR/quintal" and len(body["points"]) > 20
    assert r.headers["x-request-id"]


def test_api_events_and_manifest(client):
    events = client.get("/events").json()["events"]
    assert {e["kind"] for e in events} == {"tariff_shock", "export_ban"}
    one = client.get("/events/EVT-2024-BAN-BASMATI")
    assert one.status_code == 200 and one.json()["magnitude"] == -0.11
    assert client.get("/events/NOPE").status_code == 404
    manifest = client.get("/manifest").json()
    assert manifest["seed"] == 20261027


def test_api_coverage_names_coffee_gaps(client):
    body = client.get("/coverage/coffee").json()
    assert body["missing_drivers"] == ["stock_level", "import_flow", "export_flow"]
    assert client.get("/coverage/unobtainium").status_code == 404


def test_api_series_unknown_returns_404(client):
    r = client.get(
        "/series",
        params={"commodity": "wheat", "market": "indore", "driver": "modal_price",
                "start": "1999-01-01", "end": "1999-01-31"},
    )
    assert r.status_code == 404
