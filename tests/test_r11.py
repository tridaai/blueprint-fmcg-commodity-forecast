"""Round 11 tests: the production data plane (F20-DI1/DI2/DI4).

The source registry as an artefact; connector loads through
one validation path — clean rows land with provenance, bad
rows quarantine with exactly their planted reasons, unit
mismatches and unknown sources refuse the batch whole;
replay idempotence; corrections as insert-only overlays whose
fold is the effective fact while history keeps its landed
value; and backfill replay earning a series its accuracy
ledger through the harness's own seams. API + CLI, and a
Postgres parity class that runs when FMCG_TEST_DATABASE_URL
names a cluster.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.api import create_app
from fmcg_forecast.ingest import cli as ingest_cli
from fmcg_forecast.ingest.service import (
    IngestNotFoundError,
    IngestService,
    IngestValidationError,
)
from fmcg_forecast.ingest.verify import verify_replay
from fmcg_forecast.models import CommodityCoverage, Manifest
from fmcg_forecast.store import build_store
from fmcg_forecast.thin.engine import operating_days
from fmcg_forecast.catalogue import BY_NAME

AS_OF = date(2026, 1, 5)
T0 = datetime(2026, 1, 5, 9, 0, 0)
HEADER = "commodity,market,obs_date,driver,value,unit"


def _csv(*rows: str) -> str:
    return "\n".join([HEADER, *rows])


@pytest.fixture()
def fx(tmp_path):
    store = build_store(str(tmp_path / "r11.db"))
    return store, IngestService(store), str(tmp_path / "r11.db")


# --- registry ---------------------------------------------------------------


def test_registry_lists_the_pack_builtins_with_canonical_units(fx):
    _, svc, _ = fx
    sources = {s.source_id: s for s in svc.list_sources()}
    assert len(sources) == 6
    assert sources["agmarknet_file_drop"].units["modal_price"] == "INR/quintal"
    assert sources["mandi_api_push"].drivers == ["modal_price", "arrivals"]
    assert sources["verdanta_generated_history"].registered_by == "ingest_pack"
    assert svc.verify_all() == []


def test_register_source_is_a_named_act(fx):
    _, svc, _ = fx
    registration = svc.register_source(
        "coop_mandi_drop", "file_drop", "Cooperative mandi file drop",
        "market data desk", "daily", ["modal_price", "arrivals"],
        "Cooperative society data share", "d.rao", "desk_head", T0,
    )
    assert registration.units == {
        "modal_price": "INR/quintal",
        "arrivals": "quintal/day",
    }
    # the same act re-entered is the same artefact
    again = svc.register_source(
        "coop_mandi_drop", "file_drop", "Cooperative mandi file drop",
        "market data desk", "daily", ["modal_price", "arrivals"],
        "Cooperative society data share", "d.rao", "desk_head", T0,
    )
    assert again.source_id == registration.source_id
    # a different contract under the same id is refused
    with pytest.raises(IngestValidationError):
        svc.register_source(
            "coop_mandi_drop", "file_drop", "A different drop",
            "market data desk", "weekly", ["modal_price"],
            "Other terms", "d.rao", "desk_head", T0,
        )
    # a built-in's id is taken
    with pytest.raises(IngestValidationError):
        svc.register_source(
            "agmarknet_file_drop", "file_drop", "Impostor",
            "market data desk", "daily", ["modal_price"],
            "No terms", "d.rao", "desk_head", T0,
        )
    # unnamed actors and unknown drivers are refused
    with pytest.raises(IngestValidationError):
        svc.register_source(
            "x_drop", "file_drop", "X", "market data desk", "daily",
            ["modal_price"], "Terms", "someone", "desk_head", T0,
        )
    with pytest.raises(IngestValidationError):
        svc.register_source(
            "x_drop", "file_drop", "X", "market data desk", "daily",
            ["humidity"], "Terms", "d.rao", "desk_head", T0,
        )
    assert svc.verify_all() == []


# --- loading, quarantine, replay ---------------------------------------------


def test_file_load_lands_clean_rows_with_provenance(fx):
    store, svc, _ = fx
    batch = svc.load_file_drop(
        "agmarknet_file_drop",
        _csv(
            "coffee,bengaluru,2025-12-29,modal_price,34100,INR/quintal",
            "coffee,bengaluru,2025-12-29,arrivals,2600,quintal/day",
        ),
        as_of=AS_OF, received_by="d.rao", received_at=T0,
    )
    assert batch.status == "loaded"
    assert (batch.rows_received, batch.rows_loaded) == (2, 2)
    assert (batch.rows_quarantined, batch.rows_duplicate) == (0, 0)
    provenance = store.list_provenance(batch_id=batch.batch_id)
    assert len(provenance) == 2
    assert {p.source_id for p in provenance} == {"agmarknet_file_drop"}
    assert svc.verify_all() == []


def test_replay_lands_nothing_twice(fx):
    store, svc, _ = fx
    text = _csv("coffee,bengaluru,2025-12-29,modal_price,34100,INR/quintal")
    first = svc.load_file_drop(
        "agmarknet_file_drop", text, as_of=AS_OF,
        received_by="d.rao", received_at=T0,
    )
    replay = svc.load_file_drop(
        "agmarknet_file_drop", text, as_of=AS_OF,
        received_by="other.desk", received_at=T0 + timedelta(days=1),
    )
    assert replay.batch_id == first.batch_id
    assert len(store.series("coffee", "bengaluru", "modal_price")) == 1
    # the same fact delivered again under a new batch is a duplicate
    again = svc.load_file_drop(
        "exchange_bhavcopy_drop", text, as_of=AS_OF,
        received_by="d.rao", received_at=T0,
    )
    assert (again.rows_loaded, again.rows_duplicate) == (0, 1)
    assert len(store.series("coffee", "bengaluru", "modal_price")) == 1
    assert svc.verify_all() == []


def test_quarantine_reasons_are_exact(fx):
    store, svc, _ = fx
    # a landed fact for the conflict row to strike against
    svc.load_file_drop(
        "agmarknet_file_drop",
        _csv("coffee,bengaluru,2025-12-30,modal_price,34000,INR/quintal"),
        as_of=AS_OF, received_by="d.rao", received_at=T0,
    )
    batch = svc.load_file_drop(
        "agmarknet_file_drop",
        _csv(
            "coffee,bengaluru,not-a-date,modal_price,34100,INR/quintal",
            "tea,bengaluru,2025-12-29,modal_price,100,INR/quintal",
            "coffee,chennai,2025-12-29,modal_price,34100,INR/quintal",
            "coffee,bengaluru,2025-12-29,stock_level,80,index (0-160)",
            "coffee,bengaluru,2026-03-02,modal_price,35000,INR/quintal",
            "coffee,bengaluru,2025-12-24,arrivals,-50,quintal/day",
            "coffee,bengaluru,2025-12-30,modal_price,99999,INR/quintal",
            "coffee,bengaluru,2025-12-24,modal_price,33900,INR/quintal",
            "coffee,bengaluru,2025-12-24,modal_price,34050,INR/quintal",
        ),
        as_of=AS_OF, received_by="d.rao", received_at=T0,
    )
    assert batch.rows_loaded == 0
    assert batch.rows_quarantined == 9
    reasons = {
        r.row_index: r.reasons for r in svc.list_quarantine(batch.batch_id)
    }
    assert reasons == {
        0: ["malformed_row"],
        1: ["unknown_commodity"],
        2: ["unknown_market"],
        3: ["driver_not_reported"],
        4: ["future_date"],
        5: ["value_out_of_range"],
        6: ["conflicts_with_landed"],
        7: ["duplicate_conflicting"],
        8: ["duplicate_conflicting"],
    }
    # zero quarantined rows reached the observations table
    assert store.series("coffee", "bengaluru", "modal_price",
                        date(2025, 12, 24), date(2025, 12, 24)) == []
    assert svc.verify_all() == []


def test_api_push_provenance_and_driver_coverage(fx):
    store, svc, _ = fx
    batch = svc.load_api_push(
        "mandi_api_push",
        [
            {"commodity": "coffee", "market": "bengaluru",
             "obs_date": "2025-12-26", "driver": "modal_price",
             "value": 34300, "unit": "INR/quintal",
             "source": "mandi_api_push", "as_of": "2026-01-05"},
            {"commodity": "coffee", "market": "bengaluru",
             "obs_date": "2025-12-31", "driver": "arrivals",
             "value": 2500, "unit": "quintal/day", "as_of": "2026-01-05"},
            {"commodity": "coffee", "market": "bengaluru",
             "obs_date": "2025-12-26", "driver": "weather_index",
             "value": 0.1, "unit": "deviation (-1..1)",
             "source": "mandi_api_push", "as_of": "2026-01-05"},
        ],
        as_of=AS_OF, received_by="feed.bot", received_at=T0,
    )
    assert (batch.rows_loaded, batch.rows_quarantined) == (1, 2)
    reasons = {
        r.row_index: r.reasons for r in svc.list_quarantine(batch.batch_id)
    }
    assert reasons == {1: ["missing_provenance"], 2: ["driver_not_covered"]}
    assert svc.verify_all() == []


def test_batch_refusals_are_recorded_artefacts(fx):
    store, svc, _ = fx
    good = "coffee,bengaluru,2025-12-29,modal_price,34100,INR/quintal"
    unknown = svc.load_file_drop(
        "no_such_source", _csv(good), as_of=AS_OF,
        received_by="d.rao", received_at=T0,
    )
    assert (unknown.status, unknown.refusal_reason) == ("refused", "unknown_source")
    mismatch = svc.load_file_drop(
        "agmarknet_file_drop", _csv(good.replace("INR/quintal", "INR/kg")),
        as_of=AS_OF, received_by="d.rao", received_at=T0,
    )
    assert (mismatch.status, mismatch.refusal_reason) == ("refused", "unit_mismatch")
    no_asof = svc.load_file_drop(
        "agmarknet_file_drop", _csv(good), as_of=None,
        received_by="d.rao", received_at=T0,
    )
    assert no_asof.refusal_reason == "batch_missing_provenance"
    empty = svc.load_file_drop(
        "agmarknet_file_drop", HEADER, as_of=AS_OF,
        received_by="d.rao", received_at=T0,
    )
    assert empty.refusal_reason == "empty_batch"
    # a refused batch touches nothing
    assert store.series("coffee", "bengaluru", "modal_price") == []
    assert store.list_provenance() == []
    assert svc.verify_all() == []


def test_quarantine_tamper_is_caught(fx, tmp_path):
    store, svc, db = fx
    batch = svc.load_file_drop(
        "agmarknet_file_drop",
        _csv("coffee,bengaluru,2025-12-24,arrivals,-50,quintal/day"),
        as_of=AS_OF, received_by="d.rao", received_at=T0,
    )
    (record,) = svc.list_quarantine(batch.batch_id)
    conn = sqlite3.connect(db)
    payload = json.loads(
        conn.execute(
            "SELECT payload FROM ingest_quarantine WHERE quarantine_id = ?",
            (record.quarantine_id,),
        ).fetchone()[0]
    )
    payload["reasons"] = ["future_date"]
    conn.execute(
        "UPDATE ingest_quarantine SET payload = ? WHERE quarantine_id = ?",
        (json.dumps(payload), record.quarantine_id),
    )
    conn.commit()
    conn.close()
    problems = svc.verify_batch(batch.batch_id)
    assert any("content id mismatch" in p for p in problems)
    assert any("do not re-perform" in p for p in problems)


# --- corrections ---------------------------------------------------------------


def _land_price(svc):
    return svc.load_file_drop(
        "agmarknet_file_drop",
        _csv("coffee,bengaluru,2025-12-29,modal_price,34100,INR/quintal"),
        as_of=AS_OF, received_by="d.rao", received_at=T0,
    )


def test_correction_chain_folds_and_history_stands(fx):
    store, svc, _ = fx
    _land_price(svc)
    first = svc.correct(
        "coffee", "bengaluru", date(2025, 12, 29), "modal_price", 34250.0,
        reason="transcription slip in the phoned figure",
        corrected_by="r.menon", corrected_by_role="desk_head",
        corrected_at=T0 + timedelta(hours=1),
    )
    assert first.supersedes_correction_id is None
    second = svc.correct(
        "coffee", "bengaluru", date(2025, 12, 29), "modal_price", 34300.0,
        reason="the market contact corrected the correction",
        corrected_by="r.menon", corrected_by_role="desk_head",
        corrected_at=T0 + timedelta(hours=2),
    )
    assert second.supersedes_correction_id == first.correction_id
    # the stored observation keeps the value it landed with
    rows = store.series("coffee", "bengaluru", "modal_price",
                        date(2025, 12, 29), date(2025, 12, 29))
    assert [r.value for r in rows] == [34100.0]
    effective = svc.effective_fact(
        "coffee", "bengaluru", date(2025, 12, 29), "modal_price"
    )
    assert effective["state"] == "corrected"
    assert effective["landed_value"] == 34100.0
    assert effective["effective_value"] == 34300.0
    assert effective["provenance"]["source_id"] == "agmarknet_file_drop"
    assert [c["correction_id"] for c in effective["corrections"]] == [
        first.correction_id, second.correction_id,
    ]
    assert svc.verify_all() == []


def test_correction_answers_quarantine_without_landing(fx):
    store, svc, _ = fx
    batch = svc.load_file_drop(
        "agmarknet_file_drop",
        _csv("coffee,bengaluru,2025-12-24,arrivals,-50,quintal/day"),
        as_of=AS_OF, received_by="d.rao", received_at=T0,
    )
    (record,) = svc.list_quarantine(batch.batch_id)
    svc.correct(
        "coffee", "bengaluru", date(2025, 12, 24), "arrivals", 2450.0,
        reason="the minus was a stray keystroke on the phoned figure",
        corrected_by="r.menon", corrected_by_role="desk_head",
        corrected_at=T0 + timedelta(hours=1),
        corrects_quarantine_id=record.quarantine_id,
    )
    effective = svc.effective_fact(
        "coffee", "bengaluru", date(2025, 12, 24), "arrivals"
    )
    assert effective["state"] == "quarantine_corrected"
    assert effective["effective_value"] == 2450.0
    # the correction is an overlay: no observation appears
    assert store.series("coffee", "bengaluru", "arrivals",
                        date(2025, 12, 24), date(2025, 12, 24)) == []
    assert svc.verify_all() == []


def test_correction_refusals(fx):
    _, svc, _ = fx
    # nothing stands at the key and no quarantine record is named
    with pytest.raises(IngestValidationError):
        svc.correct(
            "coffee", "bengaluru", date(2025, 12, 29), "modal_price", 1.0,
            reason="why", corrected_by="r.menon",
            corrected_by_role="desk_head", corrected_at=T0,
        )
    _land_price(svc)
    # an out-of-range correction is a new error, refused
    with pytest.raises(IngestValidationError):
        svc.correct(
            "coffee", "bengaluru", date(2025, 12, 29), "modal_price", -5.0,
            reason="why", corrected_by="r.menon",
            corrected_by_role="desk_head", corrected_at=T0,
        )
    # an unexplained correction is refused
    with pytest.raises(IngestValidationError):
        svc.correct(
            "coffee", "bengaluru", date(2025, 12, 29), "modal_price", 34250.0,
            reason="  ", corrected_by="r.menon",
            corrected_by_role="desk_head", corrected_at=T0,
        )
    # a quarantine link about a different fact is refused
    with pytest.raises(IngestNotFoundError):
        svc.correct(
            "coffee", "bengaluru", date(2025, 12, 29), "modal_price", 34250.0,
            reason="why", corrected_by="r.menon",
            corrected_by_role="desk_head", corrected_at=T0,
            corrects_quarantine_id="QRN-doesnotexist",
        )


# --- backfill & replay ---------------------------------------------------------


def _wiggle(base: float, i: int) -> float:
    return round(base * (1 + 0.012 * math.sin(i * 0.7)), 2)


def _backfill_cumin_jodhpur(svc) -> int:
    """Three and a half years of one series, through the connector."""
    spec = BY_NAME["cumin"]
    days = operating_days(spec, date(2022, 6, 1), date(2025, 12, 31))
    lines = []
    for i, day in enumerate(days):
        lines.append(
            f"cumin,jodhpur,{day.isoformat()},modal_price,"
            f"{_wiggle(26500.0, i)},INR/quintal"
        )
        lines.append(
            f"cumin,jodhpur,{day.isoformat()},arrivals,"
            f"{_wiggle(4700.0, i)},quintal/day"
        )
        lines.append(
            f"cumin,jodhpur,{day.isoformat()},stock_level,"
            f"{_wiggle(100.0, i)},index (0-160)"
        )
        lines.append(
            f"cumin,jodhpur,{day.isoformat()},import_flow,"
            f"{_wiggle(120.0, i)},quintal/day"
        )
        lines.append(
            f"cumin,jodhpur,{day.isoformat()},export_flow,"
            f"{_wiggle(2600.0, i)},quintal/day"
        )
        lines.append(
            f"cumin,jodhpur,{day.isoformat()},weather_index,"
            f"{round(0.3 * math.sin(i * 0.11), 4)},deviation (-1..1)"
        )
    batch = svc.load_file_drop(
        "verdanta_generated_history", _csv(*lines), as_of=AS_OF,
        received_by="d.rao", received_at=T0,
    )
    assert batch.status == "loaded" and batch.rows_quarantined == 0
    return batch.rows_loaded


def _save_manifest(store, rows: int) -> None:
    spec = BY_NAME["cumin"]
    store.save_manifest(
        Manifest(
            generator_version="r11-fixture",
            seed=1,
            history_start=date(2022, 6, 1),
            history_end=date(2025, 12, 31),
            future_start=date(2026, 1, 5),
            future_end=date(2026, 4, 4),
            commodities=[
                CommodityCoverage(
                    commodity="cumin",
                    markets=["unjha", "jodhpur"],
                    drivers=list(spec.drivers),
                    reporting_pattern="mon_sat",
                    history_days_per_market=1100,
                    history_rows=rows,
                )
            ],
            events=[],
            trend_breaks=[],
            weather_anomalies=[],
            coffee_disruption_start=date(2025, 1, 1),
            coffee_disruption_end=date(2025, 1, 2),
            coffee_disruption_reporting_days_lost=0,
            history_digest="r11-fixture",
            history_rows=rows,
            future_rows=0,
        )
    )


def test_backfill_replay_earns_the_ledger(fx):
    store, svc, _ = fx
    loaded = _backfill_cumin_jodhpur(svc)
    _save_manifest(store, loaded)
    origins = [date(2025, 7, 1), date(2025, 8, 1),
               date(2025, 9, 1), date(2025, 10, 1)]
    replay = svc.replay_backtests(
        "cumin", "jodhpur", origins,
        replayed_by="d.rao", replayed_at=T0,
    )
    assert replay.results_stored == 12
    assert replay.skipped == []
    assert len(replay.result_ids) == 12
    # the series earned a ledger: one record per horizon, pooled
    # over exactly the replayed origins
    for horizon in (7, 30, 90):
        record = store.get_accuracy_record("cumin", "jodhpur", horizon)
        assert record is not None
        assert record.origins == origins
    assert sorted(replay.ledger_record_ids) == sorted(
        store.get_accuracy_record("cumin", "jodhpur", h).record_id
        for h in (7, 30, 90)
    )
    # a second replay stores nothing twice
    again = svc.replay_backtests(
        "cumin", "jodhpur", origins,
        replayed_by="d.rao", replayed_at=T0 + timedelta(days=1),
    )
    assert again.results_stored == 0
    assert again.results_already_on_record == 12
    assert len(store.list_backtest_results("cumin", "jodhpur")) == 12
    # an origin the data cannot support is skipped, with the
    # engine's refusal named — never silently dropped
    early = svc.replay_backtests(
        "cumin", "jodhpur", [date(2022, 7, 1)],
        replayed_by="d.rao", replayed_at=T0,
    )
    assert early.results_stored == 0
    assert len(early.skipped) == 1
    assert "observed price days" in early.skipped[0]["reason"]
    assert verify_replay(store, replay) == []
    assert svc.verify_all() == []


# --- API + CLI -------------------------------------------------------------------


def test_api_surface(fx):
    store, _, _ = fx
    with TestClient(create_app(store)) as client:
        assert client.get("/ingest/pack").json()["version"] == "2026.10.1"
        sources = client.get("/ingest/sources").json()["sources"]
        assert len(sources) == 6
        loaded = client.post(
            "/ingest/batches/file",
            json={
                "source_id": "agmarknet_file_drop",
                "csv_text": _csv(
                    "coffee,bengaluru,2025-12-29,modal_price,34100,INR/quintal",
                    "coffee,bengaluru,2025-12-24,arrivals,-50,quintal/day",
                ),
                "as_of": "2026-01-05",
                "received_by": "d.rao",
                "at": "2026-01-05T09:00:00",
            },
        )
        assert loaded.status_code == 201
        body = loaded.json()
        assert (body["rows_loaded"], body["rows_quarantined"]) == (1, 1)
        assert body["problems"] == []
        quarantine = client.get("/ingest/quarantine").json()["quarantine"]
        assert quarantine[0]["reasons"] == ["value_out_of_range"]
        effective = client.get(
            "/ingest/effective",
            params={"commodity": "coffee", "market": "bengaluru",
                    "obs_date": "2025-12-29", "driver": "modal_price"},
        ).json()
        assert effective["state"] == "landed"
        assert effective["provenance"]["source_id"] == "agmarknet_file_drop"
        assert client.get("/ingest/verify").json() == {"problems": []}
        refused = client.post(
            "/ingest/batches/file",
            json={
                "source_id": "no_such_source",
                "csv_text": _csv(
                    "coffee,bengaluru,2025-12-29,modal_price,34100,INR/quintal"
                ),
                "as_of": "2026-01-05",
                "received_by": "d.rao",
                "at": "2026-01-05T09:00:00",
            },
        )
        assert refused.json()["status"] == "refused"
        assert refused.json()["refusal_reason"] == "unknown_source"


def test_cli_surface(fx, tmp_path):
    _, _, db = fx
    assert ingest_cli.main(["--db", db, "sources"]) == 0
    csv_path = tmp_path / "drop.csv"
    csv_path.write_text(
        _csv("coffee,bengaluru,2025-12-29,modal_price,34100,INR/quintal"),
        encoding="utf-8",
    )
    assert ingest_cli.main([
        "--db", db, "load-file", "--source", "agmarknet_file_drop",
        "--file", str(csv_path), "--as-of", "2026-01-05",
        "--received-by", "d.rao", "--at", "2026-01-05T09:00:00",
    ]) == 0
    assert ingest_cli.main([
        "--db", db, "effective", "--commodity", "coffee",
        "--market", "bengaluru", "--date", "2025-12-29",
        "--driver", "modal_price",
    ]) == 0
    assert ingest_cli.main(["--db", db, "verify"]) == 0
    assert ingest_cli.main([
        "--db", db, "correct", "--commodity", "coffee",
        "--market", "bengaluru", "--date", "2025-12-29",
        "--driver", "modal_price", "--value", "34250",
        "--reason", "transcription slip", "--corrected-by", "r.menon",
        "--corrected-by-role", "desk_head", "--at", "2026-01-05T10:00:00",
    ]) == 0


# --- Postgres parity -------------------------------------------------------------

PG_URL = os.environ.get("FMCG_TEST_DATABASE_URL")


@pytest.mark.skipif(not PG_URL, reason="FMCG_TEST_DATABASE_URL not set")
def test_postgres_parity(tmp_path):
    """The same delivery on both dialects: identical artefacts."""
    import psycopg

    schema = f"r11_{os.getpid()}"
    admin = psycopg.connect(PG_URL, autocommit=True)
    admin.execute(f'CREATE SCHEMA "{schema}"')
    sep = "&" if "?" in PG_URL else "?"
    url = f"{PG_URL}{sep}options=-c%20search_path%3D{schema}"
    try:
        pg_store = build_store(database_url=url)
        pg = IngestService(pg_store)
        lite_store = build_store(str(tmp_path / "parity.db"))
        lite = IngestService(lite_store)
        text = _csv(
            "coffee,bengaluru,2025-12-29,modal_price,34100,INR/quintal",
            "coffee,bengaluru,2025-12-24,arrivals,-50,quintal/day",
            "coffee,bengaluru,2026-03-02,modal_price,35000,INR/quintal",
        )
        pg_batch = pg.load_file_drop(
            "agmarknet_file_drop", text, as_of=AS_OF,
            received_by="d.rao", received_at=T0,
        )
        lite_batch = lite.load_file_drop(
            "agmarknet_file_drop", text, as_of=AS_OF,
            received_by="d.rao", received_at=T0,
        )
        assert pg_batch.model_dump(mode="json") == lite_batch.model_dump(mode="json")
        assert [
            r.reasons for r in pg.list_quarantine(pg_batch.batch_id)
        ] == [r.reasons for r in lite.list_quarantine(lite_batch.batch_id)]
        assert pg.verify_all() == [] == lite.verify_all()
        correction = pg.correct(
            "coffee", "bengaluru", date(2025, 12, 29), "modal_price", 34250.0,
            reason="transcription slip", corrected_by="r.menon",
            corrected_by_role="desk_head", corrected_at=T0,
        )
        lite_correction = lite.correct(
            "coffee", "bengaluru", date(2025, 12, 29), "modal_price", 34250.0,
            reason="transcription slip", corrected_by="r.menon",
            corrected_by_role="desk_head", corrected_at=T0,
        )
        assert correction.correction_id == lite_correction.correction_id
        assert pg.effective_fact(
            "coffee", "bengaluru", date(2025, 12, 29), "modal_price"
        ) == lite.effective_fact(
            "coffee", "bengaluru", date(2025, 12, 29), "modal_price"
        )
    finally:
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid()"
        )
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.close()
