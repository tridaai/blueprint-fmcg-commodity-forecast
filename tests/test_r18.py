"""Round 18 tests: cost, usage and service monitoring
(F20-AM2).

The acceptance gates, as probed before the build:

- COST: every completed model-port call strikes exactly
  one run record, and a board's cost total is the exact
  sum of the rated records it folds — reconciliation is
  arithmetic, not assertion. An unrated profile's calls
  carry cost None (never zero), are counted as unrated,
  and never enter a cost total.
- PRIVACY: the ledger stores hashes and counts only —
  a headline that passed through the port appears
  nowhere in any stored run payload.
- FRESHNESS: a daily source whose last loaded batch is
  older than the pack's window at the board's as-of is
  named a breach; a source that has never loaded is
  named on the board, never absent; a one-off source
  owes no window. A refused batch is job history, not
  freshness — the verdict reads from the last LOADED
  batch.
- AS-OF: a board folds only records and batches at or
  before its struck instant.
- TAMPER: a rewritten cost, a purpose outside the
  closed vocabulary, a token figure the estimator does
  not give, a forged content address and a board whose
  breach list was quietly dropped are each named by
  the verifier.

Postgres parity runs when FMCG_TEST_DATABASE_URL
names a cluster.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.api import create_app
from fmcg_forecast.ingest.models import IngestBatch, batch_content_id
from fmcg_forecast.modelport import ModelNotConfiguredError, OfflineModel
from fmcg_forecast.monitoring import cli as monitoring_cli
from fmcg_forecast.monitoring.engine import estimate_tokens, price_call
from fmcg_forecast.monitoring.models import (
    RunRecord,
    board_content_id,
    canonical_payload,
    payload_hash,
    run_content_id,
)
from fmcg_forecast.monitoring.pack import (
    PURPOSES,
    load_monitoring_pack,
)
from fmcg_forecast.monitoring.port import RecordingModelPort
from fmcg_forecast.monitoring.service import MonitoringService
from fmcg_forecast.monitoring.verify import verify_monitoring
from fmcg_forecast.sentiment.models import SentimentItem
from fmcg_forecast.sentiment.service import SentimentService
from fmcg_forecast.store import build_store

UTC = timezone.utc
AS_OF = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)


class AnthropicNamedModel(OfflineModel):
    """The offline readings under a rated profile's name."""

    profile_name = "anthropic"


class RefusingModel(OfflineModel):
    profile_name = "anthropic"

    def extract_sentiment(self, *, headline: str) -> dict:
        raise ModelNotConfiguredError("refusing, as a hosted port does")


def _clock(times):
    it = iter(times)
    return lambda: next(it)


def _batch(source_id: str, received_at: datetime, *, status="loaded",
           rows_received=10, rows_loaded=9, rows_quarantined=1) -> IngestBatch:
    digest = payload_hash({"source": source_id, "at": received_at.isoformat()})
    return IngestBatch(
        batch_id=batch_content_id(
            source_id, "file_drop", date(2026, 1, 9), digest, "2026.10.1"
        ),
        source_id=source_id,
        connector_kind="file_drop",
        received_by="a.sharma",
        received_at=received_at,
        as_of=date(2026, 1, 9) if status == "loaded" else None,
        pack_version="2026.10.1",
        status=status,
        refusal_reason="" if status == "loaded" else "unit_mismatch",
        rows_received=rows_received if status == "loaded" else 0,
        rows_loaded=rows_loaded if status == "loaded" else 0,
        rows_quarantined=rows_quarantined if status == "loaded" else 0,
        rows_duplicate=0,
        content_digest=digest,
    )


# --- the pack -----------------------------------------------------------------


def test_pack_loader_is_fail_closed():
    pack = load_monitoring_pack()
    assert pack.version == "2026.10.1"
    assert tuple(pack.purposes) == PURPOSES
    with pytest.raises(ValueError):
        load_monitoring_pack("1999.01.1")


def test_estimator_and_rate_card_arithmetic():
    pack = load_monitoring_pack()
    assert estimate_tokens(0, pack) == 0
    assert estimate_tokens(8, pack) == 2
    assert estimate_tokens(9, pack) == 3
    # a million tokens each way at the anthropic reference
    # rate: 3e9 + 15e9 nano-USD, exactly
    cost, basis = price_call("anthropic", 1_000_000, 1_000_000, pack)
    assert (cost, basis) == (18_000_000_000, "reference_rate")
    # the offline profile is unrated: None, never zero
    cost, basis = price_call("offline", 1_000_000, 1_000_000, pack)
    assert cost is None and basis == "unrated_profile"
    # a profile the pack does not state prices the same way
    cost, basis = price_call("some_future_profile", 10, 10, pack)
    assert cost is None and basis == "unrated_profile"


# --- the recording port ---------------------------------------------------------


def test_every_completed_call_strikes_one_record(tmp_path):
    store = build_store(str(tmp_path / "t.db"))
    pack = load_monitoring_pack()
    times = [AS_OF + timedelta(seconds=i) for i in range(4)]
    port = RecordingModelPort(OfflineModel(), store, pack, clock=_clock(times))
    bare = OfflineModel()
    assert port.profile_name == "offline"
    assert port.extract_sentiment(headline="Arrivals surge at mandis.") == \
        bare.extract_sentiment(headline="Arrivals surge at mandis.")
    assert port.draft_commentary(subject="Wheat", figures={"p50": "2450"}) == \
        bare.draft_commentary(subject="Wheat", figures={"p50": "2450"})
    assert port.parse_scenario(text="what if", events=[]) == \
        bare.parse_scenario(text="what if", events=[])
    assert port.parse_dashboard(text="show wheat", context={}) == \
        bare.parse_dashboard(text="show wheat", context={})
    records = store.list_model_runs()
    assert len(records) == 4
    assert [r.purpose for r in sorted(records, key=lambda r: r.called_at)] == [
        "sentiment_extraction",
        "commentary_drafting",
        "scenario_parsing",
        "dashboard_parsing",
    ]
    (first,) = [r for r in records if r.purpose == "sentiment_extraction"]
    assert first.cost_nano_usd is None
    assert first.cost_basis == "unrated_profile"
    # the hashes re-derive from the payloads the caller sent
    assert first.request_hash == payload_hash(
        {"headline": "Arrivals surge at mandis."}
    )
    assert first.request_chars == len(
        canonical_payload({"headline": "Arrivals surge at mandis."})
    )
    assert run_content_id(first) == first.run_id
    assert verify_monitoring(store) == []


def test_the_ledger_stores_hashes_never_text(tmp_path):
    store = build_store(str(tmp_path / "t.db"))
    port = RecordingModelPort(
        OfflineModel(), store, load_monitoring_pack(),
        clock=_clock([AS_OF]),
    )
    secret = "Phoned-in quote from the Kanpur contact, do not publish"
    port.extract_sentiment(headline=secret)
    (record,) = store.list_model_runs()
    assert secret not in record.model_dump_json()
    assert "Kanpur" not in record.model_dump_json()


def test_a_rated_profile_is_priced_exactly(tmp_path):
    store = build_store(str(tmp_path / "t.db"))
    pack = load_monitoring_pack()
    port = RecordingModelPort(
        AnthropicNamedModel(), store, pack, clock=_clock([AS_OF])
    )
    port.extract_sentiment(headline="Arrivals surge at mandis.")
    (record,) = store.list_model_runs()
    expected = int(round(
        (record.request_tokens * 3_000_000_000
         + record.response_tokens * 15_000_000_000) / 1_000_000
    ))
    assert record.cost_basis == "reference_rate"
    assert record.cost_nano_usd == expected
    assert record.cost_nano_usd > 0


def test_a_refused_call_strikes_no_record(tmp_path):
    store = build_store(str(tmp_path / "t.db"))
    port = RecordingModelPort(
        RefusingModel(), store, load_monitoring_pack(), clock=_clock([AS_OF])
    )
    with pytest.raises(ModelNotConfiguredError):
        port.extract_sentiment(headline="anything")
    assert store.list_model_runs() == []


def test_a_repeated_identical_call_is_one_record(tmp_path):
    """The pipeline re-drafts commentary for standing indices on
    every run, so identical calls are the common case: a repeat
    under the same content address holds ONE record and the
    second strike does not raise."""
    store = build_store(str(tmp_path / "t.db"))
    port = RecordingModelPort(
        OfflineModel(), store, load_monitoring_pack(),
        clock=_clock([AS_OF, AS_OF]),
    )
    port.draft_commentary(subject="Wheat", figures={"p50": "2450"})
    port.draft_commentary(subject="Wheat", figures={"p50": "2450"})
    records = store.list_model_runs()
    assert len(records) == 1
    assert records[0].purpose == "commentary_drafting"
    assert verify_monitoring(store) == []


def test_pipeline_calls_are_ledgered_exactly_once(tmp_path):
    store = build_store(str(tmp_path / "t.db"))
    store.insert_sentiment_items(
        [
            SentimentItem(
                item_id=f"NEWS-2026-{n}",
                commodity="wheat",
                item_date=date(2026, 1, 5),
                source="trade wire",
                headline=headline,
            )
            for n, headline in enumerate(
                ["Arrivals surge at mandis.", "Export demand strong.",
                 "Stocks ample at ports."],
                start=1,
            )
        ]
    )
    port = RecordingModelPort(
        OfflineModel(), store, load_monitoring_pack(),
        clock=_clock([AS_OF + timedelta(seconds=i) for i in range(9)]),
    )
    summary = SentimentService(store, port).run_pipeline()
    assert summary["extractions_new"] == 3
    records = store.list_model_runs()
    assert len(records) == 3
    assert {r.purpose for r in records} == {"sentiment_extraction"}
    assert verify_monitoring(store) == []


# --- boards: usage reconciliation -----------------------------------------------


def _mixed_store(tmp_path):
    store = build_store(str(tmp_path / "t.db"))
    pack = load_monitoring_pack()
    offline = RecordingModelPort(
        OfflineModel(), store, pack,
        clock=_clock([AS_OF - timedelta(hours=2), AS_OF - timedelta(hours=1)]),
    )
    offline.extract_sentiment(headline="Arrivals surge at mandis.")
    offline.draft_commentary(subject="Wheat", figures={"p50": "2450"})
    rated = RecordingModelPort(
        AnthropicNamedModel(), store, pack,
        clock=_clock([AS_OF - timedelta(minutes=30)]),
    )
    rated.extract_sentiment(headline="Export demand strong.")
    return store


def test_board_cost_totals_reconcile_to_the_record(tmp_path):
    store = _mixed_store(tmp_path)
    board = MonitoringService(store).strike_board(as_of=AS_OF)
    records = store.list_model_runs()
    rated = [r for r in records if r.cost_basis == "reference_rate"]
    assert board.total_calls == 3
    assert board.rated_calls == 1
    assert board.unrated_calls == 2
    assert board.total_cost_nano_usd == sum(r.cost_nano_usd for r in rated)
    assert board.total_request_tokens == sum(r.request_tokens for r in records)
    assert board.total_response_tokens == sum(r.response_tokens for r in records)
    rows = {(r.profile, r.purpose): r for r in board.usage}
    assert rows[("offline", "sentiment_extraction")].cost_nano_usd is None
    assert rows[("anthropic", "sentiment_extraction")].cost_nano_usd == \
        rated[0].cost_nano_usd
    assert board_content_id(board) == board.board_id
    assert verify_monitoring(store) == []


def test_striking_is_idempotent(tmp_path):
    store = _mixed_store(tmp_path)
    service = MonitoringService(store)
    first = service.strike_board(as_of=AS_OF)
    second = service.strike_board(as_of=AS_OF)
    assert first.board_id == second.board_id
    assert len(store.list_monitoring_boards()) == 1


def test_a_board_folds_only_what_had_landed_by_its_as_of(tmp_path):
    store = build_store(str(tmp_path / "t.db"))
    pack = load_monitoring_pack()
    port = RecordingModelPort(
        OfflineModel(), store, pack,
        clock=_clock([AS_OF - timedelta(hours=1), AS_OF + timedelta(hours=1)]),
    )
    port.extract_sentiment(headline="Arrivals surge at mandis.")
    port.extract_sentiment(headline="Export demand strong.")
    store.insert_ingest_batch(
        _batch("agmarknet_file_drop", AS_OF - timedelta(hours=12))
    )
    store.insert_ingest_batch(
        _batch("exchange_bhavcopy_drop", AS_OF + timedelta(hours=2))
    )
    board = MonitoringService(store).strike_board(as_of=AS_OF)
    assert board.total_calls == 1
    rows = {r.source_id: r for r in board.freshness}
    assert rows["agmarknet_file_drop"].n_batches == 1
    assert rows["exchange_bhavcopy_drop"].n_batches == 0
    assert rows["exchange_bhavcopy_drop"].state == "never_loaded"
    assert verify_monitoring(store) == []


# --- boards: freshness ------------------------------------------------------------


def test_freshness_verdicts_and_named_gaps(tmp_path):
    store = build_store(str(tmp_path / "t.db"))
    # daily source, last loaded 48h before the as-of: a breach
    store.insert_ingest_batch(
        _batch("agmarknet_file_drop", AS_OF - timedelta(hours=48))
    )
    # hourly source, loaded an hour ago: fresh
    store.insert_ingest_batch(
        _batch("mandi_api_push", AS_OF - timedelta(hours=1))
    )
    # weekly source whose only batch was REFUSED: never loaded,
    # and the refusal is on its face as job history
    store.insert_ingest_batch(
        _batch("trade_flow_file_drop", AS_OF - timedelta(hours=2),
               status="refused")
    )
    board = MonitoringService(store).strike_board(as_of=AS_OF)
    rows = {r.source_id: r for r in board.freshness}
    assert rows["agmarknet_file_drop"].state == "late"
    assert rows["agmarknet_file_drop"].age_hours == 48.0
    assert board.breaches == ["agmarknet_file_drop"]
    assert rows["mandi_api_push"].state == "fresh"
    trade = rows["trade_flow_file_drop"]
    assert trade.state == "never_loaded"
    assert trade.n_batches == 1 and trade.n_refused == 1
    assert "trade_flow_file_drop" in board.never_loaded
    # the one-off bootstrap owes no window and breaches nothing
    assert rows["verdanta_generated_history"].state == "one_off"
    assert "verdanta_generated_history" not in board.breaches
    assert "verdanta_generated_history" not in board.never_loaded
    # every registered source has a row — nothing is absent
    assert len(board.freshness) == 6
    assert verify_monitoring(store) == []


def test_a_refusal_does_not_refresh_freshness(tmp_path):
    store = build_store(str(tmp_path / "t.db"))
    store.insert_ingest_batch(
        _batch("weather_service_pull", AS_OF - timedelta(hours=72))
    )
    store.insert_ingest_batch(
        _batch("weather_service_pull", AS_OF - timedelta(hours=1),
               status="refused")
    )
    board = MonitoringService(store).strike_board(as_of=AS_OF)
    (row,) = [r for r in board.freshness
              if r.source_id == "weather_service_pull"]
    assert row.state == "late"
    assert row.age_hours == 72.0
    assert row.n_batches == 2 and row.n_refused == 1
    assert row.rows_loaded == 9


# --- the verifier's tamper probes ---------------------------------------------------


def _tamper_store(tmp_path):
    store = _mixed_store(tmp_path)
    MonitoringService(store).strike_board(as_of=AS_OF)
    assert verify_monitoring(store) == []
    return store


def test_verifier_names_a_rewritten_cost(tmp_path):
    store = _tamper_store(tmp_path)
    (rated,) = [r for r in store.list_model_runs()
                if r.cost_basis == "reference_rate"]
    forged = rated.model_copy(
        update={"cost_nano_usd": rated.cost_nano_usd + 1}
    )
    forged = forged.model_copy(update={"run_id": run_content_id(forged)})
    # insert-only discipline is the service's; the verifier's
    # job is to name a row that does not re-perform, so the
    # probe writes through a scratch store of its own
    scratch = build_store(str(tmp_path / "scratch.db"))
    scratch.insert_model_run(forged)
    problems = verify_monitoring(scratch)
    assert any("states cost" in p for p in problems)


def test_verifier_names_a_forged_address_and_a_foreign_purpose(tmp_path):
    store = build_store(str(tmp_path / "t.db"))
    port = RecordingModelPort(
        OfflineModel(), store, load_monitoring_pack(), clock=_clock([AS_OF])
    )
    port.extract_sentiment(headline="Arrivals surge at mandis.")
    (record,) = store.list_model_runs()
    scratch = build_store(str(tmp_path / "scratch.db"))
    forged = record.model_copy(update={"request_chars": 9999})
    scratch.insert_model_run(forged)  # id no longer re-derives
    problems = verify_monitoring(scratch)
    assert any("content id mismatch" in p for p in problems)
    assert any("estimator gives" in p for p in problems)
    foreign = record.model_copy(update={"purpose": "free_styling"})
    foreign = foreign.model_copy(update={"run_id": run_content_id(foreign)})
    scratch2 = build_store(str(tmp_path / "scratch2.db"))
    scratch2.insert_model_run(foreign)
    problems = verify_monitoring(scratch2)
    assert any("closed" in p and "vocabulary" in p for p in problems)


def test_verifier_names_a_board_with_a_dropped_breach(tmp_path):
    store = _tamper_store(tmp_path)
    store.insert_ingest_batch(
        _batch("agmarknet_file_drop", AS_OF - timedelta(hours=48))
    )
    board = MonitoringService(store).strike_board(as_of=AS_OF)
    assert board.breaches == ["agmarknet_file_drop"]
    doctored = board.model_copy(update={"breaches": []})
    doctored = doctored.model_copy(
        update={"board_id": board_content_id(doctored)}
    )
    scratch = build_store(str(tmp_path / "scratch.db"))
    for record in store.list_model_runs():
        scratch.insert_model_run(record)
    scratch.insert_ingest_batch(
        _batch("agmarknet_file_drop", AS_OF - timedelta(hours=48))
    )
    scratch.insert_monitoring_board(doctored)
    problems = verify_monitoring(scratch)
    assert any("does not re-perform" in p for p in problems)


# --- surfaces ---------------------------------------------------------------------


def test_api_ledgers_its_own_calls_and_serves_the_board(tmp_path):
    store = build_store(str(tmp_path / "t.db"))
    store.insert_sentiment_items(
        [
            SentimentItem(
                item_id="NEWS-2026-1", commodity="wheat",
                item_date=date(2026, 1, 5), source="trade wire",
                headline="Arrivals surge at mandis.",
            ),
            SentimentItem(
                item_id="NEWS-2026-2", commodity="wheat",
                item_date=date(2026, 1, 5), source="trade wire",
                headline="Export demand strong.",
            ),
        ]
    )
    client = TestClient(create_app(store))
    r = client.get("/monitoring/pack")
    assert r.status_code == 200 and r.json()["version"] == "2026.10.1"
    r = client.post("/sentiment/run")
    assert r.status_code == 200
    r = client.get("/monitoring/runs")
    assert r.status_code == 200 and len(r.json()["runs"]) == 2
    r = client.get("/monitoring/runs", params={"purpose": "scenario_parsing"})
    assert r.json()["runs"] == []
    r = client.post("/monitoring/boards")
    assert r.status_code == 200
    board = r.json()
    assert board["total_calls"] == 2
    assert board["unrated_calls"] == 2
    assert "agmarknet_file_drop" in board["never_loaded"]
    r = client.get(f"/monitoring/boards/{board['board_id']}")
    assert r.status_code == 200 and r.json()["board_id"] == board["board_id"]
    r = client.get("/monitoring/boards/MON-nope")
    assert r.status_code == 404
    r = client.get("/monitoring/verify")
    assert r.status_code == 200 and r.json()["problems"] == []


def test_cli_round_trip(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    store = build_store(db)
    port = RecordingModelPort(
        OfflineModel(), store, load_monitoring_pack(), clock=_clock([AS_OF])
    )
    port.extract_sentiment(headline="Arrivals surge at mandis.")
    store.close()
    assert monitoring_cli.main(["--db", db, "runs"]) == 0
    assert "sentiment_extraction" in capsys.readouterr().out
    assert monitoring_cli.main(["--db", db, "board"]) == 0
    assert "MON-" in capsys.readouterr().out
    assert monitoring_cli.main(["--db", db, "verify"]) == 0
    assert monitoring_cli.main(["--db", db, "board", "MON-nope"]) == 2


# --- Postgres parity ---------------------------------------------------------

PG_DSN = os.environ.get("FMCG_TEST_DATABASE_URL")


def _monitoring_walk(store) -> dict:
    pack = load_monitoring_pack()
    times = [AS_OF - timedelta(hours=3) + timedelta(minutes=7 * i)
             for i in range(6)]
    port = RecordingModelPort(
        OfflineModel(), store, pack, clock=_clock(times[:3])
    )
    port.extract_sentiment(headline="Arrivals surge at mandis.")
    port.draft_commentary(subject="Wheat", figures={"p50": "2450"})
    port.parse_dashboard(text="show wheat", context={})
    rated = RecordingModelPort(
        AnthropicNamedModel(), store, pack, clock=_clock(times[3:])
    )
    rated.extract_sentiment(headline="Export demand strong.")
    store.insert_ingest_batch(
        _batch("agmarknet_file_drop", AS_OF - timedelta(hours=48))
    )
    store.insert_ingest_batch(
        _batch("mandi_api_push", AS_OF - timedelta(hours=1))
    )
    board = MonitoringService(store, pack).strike_board(as_of=AS_OF)
    return {
        "runs": [r.model_dump(mode="json") for r in store.list_model_runs()],
        "board": board.model_dump(mode="json"),
        "problems": verify_monitoring(store, pack),
    }


def _pg_store():
    """A Postgres store in its own fresh schema (the R17 pattern)."""
    import psycopg

    schema = "r18_" + uuid.uuid4().hex[:12]
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.commit()
    sep = "&" if "?" in PG_DSN else "?"
    return build_store(
        database_url=(
            f"{PG_DSN}{sep}options=-c%20search_path%3D{schema}"
        )
    )


@pytest.mark.skipif(not PG_DSN, reason="FMCG_TEST_DATABASE_URL not set")
def test_postgres_parity(tmp_path):
    lite = build_store(str(tmp_path / "lite.db"))
    pg = _pg_store()
    lite_walk = _monitoring_walk(lite)
    pg_walk = _monitoring_walk(pg)
    assert lite_walk == pg_walk
    assert pg_walk["problems"] == []
    assert pg_walk["board"]["breaches"] == ["agmarknet_file_drop"]
