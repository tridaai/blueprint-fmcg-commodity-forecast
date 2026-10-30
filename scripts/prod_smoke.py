"""Production smoke: the Postgres profile, end to end.

Stands the application up against the production-shaped
store — Postgres 16 via ``DATABASE_URL`` (a UTF-8 database;
the store layer reads text back as text) — in a throwaway
schema, and checks the things a deployment must prove
before it serves:

- the full migration set applies cleanly on a fresh schema;
- the dataset generates and loads, counts matching the
  manifest, on this profile too;
- the backtest harness runs the pack's grid (405 results,
  42 ledger records) against the Postgres store;
- ``/health`` and ``/readiness`` answer on the real app;
- the R11 data plane works on this profile too: a connector
  batch lands its clean rows, quarantines its bad row with
  the reason named, verifies, and its replay lands nothing
  twice — and the same delivery on a SQLite store produces
  the identical batch artefact (dialect parity, gap 0);
- the R13 operator console works on this profile too: the
  migration chain includes the console tables, and a struck
  pre-flight and a rejection act on the Postgres store are
  byte-identical to the same artefacts struck on a full
  SQLite store over the same record (dialect parity, gap 0);
- the R14 geo layer works on this profile too: cost lines
  entered on the Postgres store price a landed comparison,
  and the basis reading, the landed comparison and the
  market map are byte-identical to the same artefacts
  struck on a full SQLite store over the same record
  (dialect parity, gap 0), with the layer re-performing
  clean on the Postgres profile.

Usage: DATABASE_URL=postgresql://... python scripts/prod_smoke.py
Exits 0 when every check passes, 1 otherwise.
"""

import os
import sys
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPO = Path(__file__).resolve().parents[1]

FIXTURE_CSV = "\n".join(
    [
        "commodity,market,obs_date,driver,value,unit",
        "coffee,bengaluru,2025-12-29,modal_price,34100,INR/quintal",
        "coffee,bengaluru,2025-12-29,arrivals,-50,quintal/day",
    ]
)


def _fixture_batch(store):
    from fmcg_forecast.ingest.service import IngestService

    service = IngestService(store)
    batch = service.load_file_drop(
        "agmarknet_file_drop",
        FIXTURE_CSV,
        as_of=date(2026, 1, 5),
        received_by="smoke.desk",
        received_at=datetime(2026, 1, 5, 9, 0),
    )
    return service, batch


def main() -> int:
    base_url = os.environ.get("DATABASE_URL")
    if not base_url:
        print("SMOKE FAIL: DATABASE_URL is not set — the smoke "
              "runs against the Postgres profile only")
        return 1
    import psycopg

    schema = f"smoke_{uuid.uuid4().hex[:12]}"
    admin = psycopg.connect(base_url, autocommit=True)
    admin.execute("SET lock_timeout = '30s'")
    admin.execute(f'CREATE SCHEMA "{schema}"')
    sep = "&" if "?" in base_url else "?"
    url = f"{base_url}{sep}options=-c%20search_path%3D{schema}"
    problems: list[str] = []
    try:
        from fastapi.testclient import TestClient

        from fmcg_forecast.api import create_app
        from fmcg_forecast.backtest.harness import run_all
        from fmcg_forecast.ingest.service import IngestService
        from fmcg_forecast.generator import generate_dataset
        from fmcg_forecast.migrations import migration_files
        from fmcg_forecast.store import build_store
        from fmcg_forecast.truth import build_truth_store
        from fmcg_forecast.workflow import load_dataset

        store = build_store(database_url=url)
        truth_store = build_truth_store(database_url=url)
        applied = [
            r[0].decode() if isinstance(r[0], bytes) else r[0]
            for r in store._conn.execute(
                "SELECT name FROM schema_migrations ORDER BY name"
            ).fetchall()
        ]
        expected = [p.name for p in migration_files("postgres")]
        if applied != expected:
            problems.append(
                f"migrations applied: {applied}, expected {expected}"
            )
        else:
            print(f"migrations: {len(applied)} applied cleanly "
                  f"({applied[0]}..{applied[-1]})")

        data = generate_dataset()
        load_dataset(store, truth_store, data.manifest.seed)
        counts = store.row_counts()
        if sum(counts.values()) != data.manifest.history_rows:
            problems.append(
                f"history rows {sum(counts.values())} != manifest "
                f"{data.manifest.history_rows}"
            )
        print(f"dataset: {sum(counts.values())} history rows, "
              "manifest counts match")

        report, records = run_all(store)
        n_results = len(store.list_backtest_results())
        if n_results != 405 or len(records) != 42:
            problems.append(
                f"backtest grid on Postgres: {n_results} results, "
                f"{len(records)} records (expected 405 / 42)"
            )
        print(f"backtests: {n_results} results, {len(records)} "
              "ledger records on the Postgres profile")

        app = create_app(store)
        with TestClient(app) as client:
            health = client.get("/health")
            readiness = client.get("/readiness")
            if health.status_code != 200 or health.json() != {"status": "ok"}:
                problems.append(f"/health answered {health.status_code}")
            if readiness.status_code != 200:
                problems.append(f"/readiness answered {readiness.status_code}")
            sources = client.get("/ingest/sources")
            if sources.status_code != 200 or len(sources.json()["sources"]) != 6:
                problems.append("the source registry does not answer")
        print("/health and /readiness: ok on the Postgres profile")

        service, batch = _fixture_batch(store)
        if (batch.rows_loaded, batch.rows_quarantined) != (1, 1):
            problems.append(
                f"fixture batch landed {batch.rows_loaded} / "
                f"quarantined {batch.rows_quarantined} (expected 1 / 1)"
            )
        reasons = [
            r.reasons for r in service.list_quarantine(batch_id=batch.batch_id)
        ]
        if reasons != [["value_out_of_range"]]:
            problems.append(f"fixture quarantine reasons: {reasons}")
        _, replay = _fixture_batch(store)
        if replay.batch_id != batch.batch_id:
            problems.append("connector replay minted a second batch artefact")
        if service.verify_all():
            problems.append(f"data plane does not verify: {service.verify_all()}")
        print("data plane: batch landed, quarantined, verified, "
              "replay idempotent")

        with tempfile.TemporaryDirectory() as tmp:
            sqlite_store = build_store(str(Path(tmp) / "parity.db"))
            _, sqlite_batch = _fixture_batch(sqlite_store)
            if sqlite_batch.model_dump(mode="json") != batch.model_dump(mode="json"):
                problems.append(
                    "dialect parity: the SQLite batch artefact "
                    "differs from the Postgres one"
                )
            sqlite_reasons = [
                r.reasons
                for r in IngestService(sqlite_store).list_quarantine(
                    batch_id=sqlite_batch.batch_id
                )
            ]
            if sqlite_reasons != reasons:
                problems.append("dialect parity: quarantine reasons differ")
        print("dialect parity: batch artefact and quarantine "
              "identical across profiles (gap 0)")

        # --- R13: the operator console on this profile ----------------
        from fmcg_forecast.console.service import ConsoleService
        from fmcg_forecast.events.service import EventService
        from fmcg_forecast.forecast.service import ForecastService
        from fmcg_forecast.modelport import OfflineModel
        from fmcg_forecast.sentiment.grading import (
            build_sentiment_grading_store,
        )
        from fmcg_forecast.sentiment.load import load_sentiment_corpus
        from fmcg_forecast.sentiment.service import SentimentService

        EventService(store).seed_historical(store.get_manifest())
        grading = build_sentiment_grading_store(database_url=url)
        load_sentiment_corpus(store, grading, data.manifest.seed)
        SentimentService(store, OfflineModel()).run_pipeline()
        pg_console = ConsoleService(store, EventService(store))

        with tempfile.TemporaryDirectory() as tmp:
            lite_db = str(Path(tmp) / "console-parity.db")
            lite = build_store(lite_db)
            lite_truth = build_truth_store(lite_db)
            load_dataset(lite, lite_truth, data.manifest.seed)
            run_all(lite)
            EventService(lite).seed_historical(lite.get_manifest())
            lite_grading = build_sentiment_grading_store(lite_db)
            load_sentiment_corpus(lite, lite_grading, data.manifest.seed)
            SentimentService(lite, OfflineModel()).run_pipeline()
            lite_console = ConsoleService(lite, EventService(lite))
            for series in (("coffee", "bengaluru"),
                           ("wheat", "delhi_khari_baoli")):
                pg_report = pg_console.strike_preflight(*series)
                lite_report = lite_console.strike_preflight(*series)
                if pg_report.model_dump(mode="json") != (
                    lite_report.model_dump(mode="json")
                ):
                    problems.append(
                        f"console parity: the {series[0]} pre-flight "
                        "differs across profiles"
                    )
            pg_draft = ForecastService(
                store, OfflineModel()
            ).run_forecast("soybean", "nagpur", as_of=date(2025, 10, 31))
            lite_draft = ForecastService(
                lite, OfflineModel()
            ).run_forecast("soybean", "nagpur", as_of=date(2025, 10, 31))
            if pg_draft.forecast_id != lite_draft.forecast_id:
                problems.append(
                    "console parity: the parity draft's id differs "
                    "across profiles"
                )
            else:
                pg_act = pg_console.reject_forecast(
                    pg_draft.forecast_id, "d.kaur", "desk_head",
                    date(2026, 1, 3), "stale_inputs",
                )
                lite_act = lite_console.reject_forecast(
                    lite_draft.forecast_id, "d.kaur", "desk_head",
                    date(2026, 1, 3), "stale_inputs",
                )
                if pg_act.model_dump(mode="json") != (
                    lite_act.model_dump(mode="json")
                ):
                    problems.append(
                        "console parity: the rejection act differs "
                        "across profiles"
                    )
        print("console parity: pre-flights and the rejection act "
              "identical across profiles (gap 0)")

        # --- R14: the geo layer on this profile -------------------
        from fmcg_forecast.geo.service import GeoService
        from fmcg_forecast.geo.verify import verify_geo
        from fmcg_forecast.sentiment.service import SentimentService

        pg_geo = GeoService(store)
        for market in ("delhi_khari_baoli", "indore", "kanpur"):
            pg_geo.enter_cost_line(
                "wheat", market, "freight", 30000, "a.rao",
                date(2025, 12, 30),
            )
            pg_geo.enter_cost_line(
                "wheat", market, "handling", 8000, "a.rao",
                date(2025, 12, 30),
            )
        pg_basis = pg_geo.strike_basis_reading("wheat", date(2025, 12, 31))
        pg_landed = pg_geo.strike_landed_comparison(
            "wheat", date(2025, 12, 31), "verdanta_plant"
        )
        pg_map = pg_geo.strike_map("soybean", date(2025, 6, 20))
        if verify_geo(store):
            problems.append(
                f"geo layer does not verify on Postgres: {verify_geo(store)}"
            )
        with tempfile.TemporaryDirectory() as tmp:
            lite = build_store(str(Path(tmp) / "geo.db"))
            lite_truth = build_truth_store(str(Path(tmp) / "geo_truth.db"))
            load_dataset(lite, lite_truth, data.manifest.seed)
            run_all(lite)
            lite_grading = build_sentiment_grading_store(
                str(Path(tmp) / "geo_grading.db")
            )
            load_sentiment_corpus(lite, lite_grading, data.manifest.seed)
            SentimentService(lite, OfflineModel()).run_pipeline()
            EventService(lite).seed_historical(lite.get_manifest())
            lite_geo = GeoService(lite)
            for market in ("delhi_khari_baoli", "indore", "kanpur"):
                lite_geo.enter_cost_line(
                    "wheat", market, "freight", 30000, "a.rao",
                    date(2025, 12, 30),
                )
                lite_geo.enter_cost_line(
                    "wheat", market, "handling", 8000, "a.rao",
                    date(2025, 12, 30),
                )
            lite_basis = lite_geo.strike_basis_reading(
                "wheat", date(2025, 12, 31)
            )
            lite_landed = lite_geo.strike_landed_comparison(
                "wheat", date(2025, 12, 31), "verdanta_plant"
            )
            lite_map = lite_geo.strike_map("soybean", date(2025, 6, 20))
            for name, pg_art, lite_art in (
                ("basis reading", pg_basis, lite_basis),
                ("landed comparison", pg_landed, lite_landed),
                ("market map", pg_map, lite_map),
            ):
                if pg_art.model_dump(mode="json") != (
                    lite_art.model_dump(mode="json")
                ):
                    problems.append(
                        f"geo parity: the {name} differs across profiles"
                    )
        print("geo parity: basis, landed and map artefacts "
              "identical across profiles (gap 0)")
    finally:
        # The app under test holds its own store connection;
        # its open read transaction would block the DROP, so
        # clear other backends on this database first.
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() "
            "AND pid <> pg_backend_pid()")
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.close()

    if problems:
        for problem in problems:
            print(f"SMOKE FAIL: {problem}")
        return 1
    print("SMOKE PASS — the Postgres profile serves end to end")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
