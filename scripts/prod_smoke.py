"""Production smoke: the Postgres profile, end to end.

Stands the application up against the production-shaped
store — Postgres 16 via ``DATABASE_URL`` — in a throwaway
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
  the identical batch artefact (dialect parity, gap 0).

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
