"""The store port: price/driver observations, events, manifest.

One port, two dialects: SQLite is the local default, Postgres 16 is
the production profile (``DATABASE_URL``). Observation writes are
insert-only — the primary key rejects a duplicate (commodity,
market, date, driver), so a re-run load fails loudly instead of
silently overwriting history.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Protocol

from fmcg_forecast.forecast.models import (
    AccuracyRecord,
    BacktestResult,
    Commentary,
    Forecast,
    ForecastApproval,
)
from fmcg_forecast.migrations import apply_migrations
from fmcg_forecast.models import EventRecord, Manifest, Observation


class Store(Protocol):
    dialect: str

    def migrate(self) -> list[str]: ...
    def insert_observations(self, rows: list[Observation]) -> int: ...
    def insert_events(self, events: list[EventRecord]) -> int: ...
    def save_manifest(self, manifest: Manifest) -> None: ...
    def get_manifest(self) -> Manifest | None: ...
    def series(
        self,
        commodity: str,
        market: str,
        driver: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Observation]: ...
    def list_events(self, commodity: str | None = None) -> list[EventRecord]: ...
    def get_event(self, event_id: str) -> EventRecord | None: ...
    def row_counts(self) -> dict[str, int]: ...
    # -- forecast artefacts (R2) --------------------------------------
    def insert_forecast(self, forecast: Forecast) -> None: ...
    def get_forecast(self, forecast_id: str) -> Forecast | None: ...
    def list_forecasts(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[Forecast]: ...
    def set_forecast_status(self, forecast_id: str, status: str) -> None: ...
    def insert_approval(self, approval: ForecastApproval) -> None: ...
    def get_approval(self, forecast_id: str) -> ForecastApproval | None: ...
    def save_commentary(self, commentary: Commentary) -> None: ...
    def get_commentary(self, forecast_id: str) -> Commentary | None: ...
    # -- backtest results + accuracy ledger (R3) -----------------------
    def insert_backtest_result(self, result: BacktestResult) -> None: ...
    def get_backtest_result(self, result_id: str) -> BacktestResult | None: ...
    def list_backtest_results(
        self,
        commodity: str | None = None,
        market: str | None = None,
        horizon_days: int | None = None,
    ) -> list[BacktestResult]: ...
    def save_accuracy_record(self, record: AccuracyRecord) -> None: ...
    def get_accuracy_record(
        self, commodity: str, market: str, horizon_days: int
    ) -> AccuracyRecord | None: ...
    def list_accuracy_records(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[AccuracyRecord]: ...
    def close(self) -> None: ...


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


class SqlStore:
    """SQLite / Postgres implementation of the store port."""

    def __init__(self, sqlite_path: str | None = None, database_url: str | None = None):
        if database_url and database_url.startswith("postgres"):
            import psycopg

            self.dialect = "postgres"
            self._ph = "%s"
            self._conn = psycopg.connect(database_url, autocommit=True)
        else:
            self.dialect = "sqlite"
            self._ph = "?"
            path = Path(sqlite_path or "./data/fmcg.db")
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")

    # -- internals ---------------------------------------------------
    def _q(self, sql: str) -> str:
        return sql.replace("?", self._ph) if self.dialect == "postgres" else sql

    def _date_param(self, value: date):
        return value if self.dialect == "postgres" else value.isoformat()

    # -- schema --------------------------------------------------------
    def migrate(self) -> list[str]:
        return apply_migrations(self._conn, self.dialect, self._ph)

    # -- writes (insert-only) ------------------------------------------
    def insert_observations(self, rows: list[Observation]) -> int:
        sql = self._q(
            "INSERT INTO observations (commodity, market, obs_date, driver, value) "
            "VALUES (?, ?, ?, ?, ?)"
        )
        self._conn.executemany(
            sql,
            [
                (r.commodity, r.market, self._date_param(r.obs_date), r.driver, r.value)
                for r in rows
            ],
        )
        if self.dialect == "sqlite":
            self._conn.commit()
        return len(rows)

    def insert_events(self, events: list[EventRecord]) -> int:
        sql = self._q(
            "INSERT INTO events (event_id, kind, commodity, start_date, end_date, "
            "magnitude, decay_days, transmission, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        self._conn.executemany(
            sql,
            [
                (
                    e.event_id,
                    e.kind,
                    e.commodity,
                    self._date_param(e.start_date),
                    self._date_param(e.end_date),
                    e.magnitude,
                    e.decay_days,
                    e.transmission,
                    e.description,
                )
                for e in events
            ],
        )
        if self.dialect == "sqlite":
            self._conn.commit()
        return len(events)

    def save_manifest(self, manifest: Manifest) -> None:
        sql = self._q(
            "INSERT INTO generation_manifest (id, payload) VALUES (1, ?) "
            "ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload"
            if self.dialect == "postgres"
            else "INSERT OR REPLACE INTO generation_manifest (id, payload) VALUES (1, ?)"
        )
        self._conn.execute(sql, (manifest.model_dump_json(),))
        if self.dialect == "sqlite":
            self._conn.commit()

    # -- reads -----------------------------------------------------------
    def get_manifest(self) -> Manifest | None:
        cur = self._conn.execute("SELECT payload FROM generation_manifest WHERE id = 1")
        row = cur.fetchone()
        if row is None:
            return None
        return Manifest.model_validate(json.loads(row[0]))

    def series(
        self,
        commodity: str,
        market: str,
        driver: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Observation]:
        sql = (
            "SELECT commodity, market, obs_date, driver, value FROM observations "
            "WHERE commodity = ? AND market = ? AND driver = ?"
        )
        params: list = [commodity, market, driver]
        if start is not None:
            sql += " AND obs_date >= ?"
            params.append(self._date_param(start))
        if end is not None:
            sql += " AND obs_date <= ?"
            params.append(self._date_param(end))
        sql += " ORDER BY obs_date"
        cur = self._conn.execute(self._q(sql), params)
        return [
            Observation(
                commodity=r[0], market=r[1], obs_date=_as_date(r[2]),
                driver=r[3], value=float(r[4]),
            )
            for r in cur.fetchall()
        ]

    def list_events(self, commodity: str | None = None) -> list[EventRecord]:
        sql = (
            "SELECT event_id, kind, commodity, start_date, end_date, magnitude, "
            "decay_days, transmission, description FROM events"
        )
        params: list = []
        if commodity is not None:
            sql += " WHERE commodity = ?"
            params.append(commodity)
        sql += " ORDER BY start_date"
        cur = self._conn.execute(self._q(sql), params)
        return [
            EventRecord(
                event_id=r[0], kind=r[1], commodity=r[2],
                start_date=_as_date(r[3]), end_date=_as_date(r[4]),
                magnitude=float(r[5]), decay_days=int(r[6]),
                transmission=r[7], description=r[8],
            )
            for r in cur.fetchall()
        ]

    def get_event(self, event_id: str) -> EventRecord | None:
        events = [e for e in self.list_events() if e.event_id == event_id]
        return events[0] if events else None

    def row_counts(self) -> dict[str, int]:
        cur = self._conn.execute(
            "SELECT commodity, COUNT(*) FROM observations GROUP BY commodity ORDER BY commodity"
        )
        return {r[0]: int(r[1]) for r in cur.fetchall()}

    # -- forecast artefacts (R2) ---------------------------------------
    # Payloads are stored without their lifecycle status: the status
    # column is the state of record, flipped only by set_forecast_status
    # when an approval act lands. The payload itself is never rewritten,
    # so a stored decomposition cannot drift from what was approved.

    def insert_forecast(self, forecast: Forecast) -> None:
        sql = self._q(
            "INSERT INTO forecasts (forecast_id, commodity, market, as_of, "
            "status, engine_version, payload) VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                forecast.forecast_id,
                forecast.commodity,
                forecast.market,
                self._date_param(forecast.as_of),
                forecast.status,
                forecast.engine_version,
                forecast.model_dump_json(exclude={"status"}),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def _forecast_from_row(self, row) -> Forecast:
        payload = json.loads(row[6])
        payload["status"] = row[4]
        return Forecast.model_validate(payload)

    def get_forecast(self, forecast_id: str) -> Forecast | None:
        cur = self._conn.execute(
            self._q(
                "SELECT forecast_id, commodity, market, as_of, status, "
                "engine_version, payload FROM forecasts WHERE forecast_id = ?"
            ),
            (forecast_id,),
        )
        row = cur.fetchone()
        return self._forecast_from_row(row) if row else None

    def list_forecasts(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[Forecast]:
        sql = (
            "SELECT forecast_id, commodity, market, as_of, status, "
            "engine_version, payload FROM forecasts"
        )
        params: list = []
        clauses = []
        if commodity is not None:
            clauses.append("commodity = ?")
            params.append(commodity)
        if market is not None:
            clauses.append("market = ?")
            params.append(market)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY as_of, forecast_id"
        cur = self._conn.execute(self._q(sql), params)
        return [self._forecast_from_row(r) for r in cur.fetchall()]

    def set_forecast_status(self, forecast_id: str, status: str) -> None:
        self._conn.execute(
            self._q("UPDATE forecasts SET status = ? WHERE forecast_id = ?"),
            (status, forecast_id),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def insert_approval(self, approval: ForecastApproval) -> None:
        sql = self._q(
            "INSERT INTO forecast_approvals (approval_id, forecast_id, "
            "approver, role, decided_on, payload) VALUES (?, ?, ?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                approval.approval_id,
                approval.forecast_id,
                approval.approver,
                approval.role,
                self._date_param(approval.decided_on),
                approval.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_approval(self, forecast_id: str) -> ForecastApproval | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM forecast_approvals WHERE forecast_id = ?"),
            (forecast_id,),
        )
        row = cur.fetchone()
        return ForecastApproval.model_validate(json.loads(row[0])) if row else None

    def save_commentary(self, commentary: Commentary) -> None:
        if self.dialect == "postgres":
            sql = (
                "INSERT INTO commentaries (forecast_id, model_profile, payload) "
                "VALUES (%s, %s, %s) ON CONFLICT (forecast_id) DO UPDATE "
                "SET model_profile = EXCLUDED.model_profile, payload = EXCLUDED.payload"
            )
        else:
            sql = (
                "INSERT OR REPLACE INTO commentaries (forecast_id, model_profile, "
                "payload) VALUES (?, ?, ?)"
            )
        self._conn.execute(
            sql,
            (
                commentary.forecast_id,
                commentary.model_profile,
                commentary.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_commentary(self, forecast_id: str) -> Commentary | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM commentaries WHERE forecast_id = ?"),
            (forecast_id,),
        )
        row = cur.fetchone()
        return Commentary.model_validate(json.loads(row[0])) if row else None

    # -- backtest results + accuracy ledger (R3) -----------------------
    # Results are insert-only, like forecasts: the harness checks for
    # an existing content address before inserting, so a re-run is a
    # no-op rather than a duplicate-write error. The ledger holds one
    # CURRENT record per (series, horizon); saving replaces it,
    # because a rebuild is a re-performance over a possibly larger
    # result set — the record's content address is what changes.

    def insert_backtest_result(self, result: BacktestResult) -> None:
        sql = self._q(
            "INSERT INTO backtest_results (result_id, commodity, market, "
            "origin, horizon_days, forecast_id, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                result.result_id,
                result.commodity,
                result.market,
                self._date_param(result.origin),
                result.horizon_days,
                result.forecast_id,
                result.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_backtest_result(self, result_id: str) -> BacktestResult | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM backtest_results WHERE result_id = ?"),
            (result_id,),
        )
        row = cur.fetchone()
        return BacktestResult.model_validate(json.loads(row[0])) if row else None

    def list_backtest_results(
        self,
        commodity: str | None = None,
        market: str | None = None,
        horizon_days: int | None = None,
    ) -> list[BacktestResult]:
        sql = "SELECT payload FROM backtest_results"
        params: list = []
        clauses = []
        if commodity is not None:
            clauses.append("commodity = ?")
            params.append(commodity)
        if market is not None:
            clauses.append("market = ?")
            params.append(market)
        if horizon_days is not None:
            clauses.append("horizon_days = ?")
            params.append(horizon_days)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY commodity, market, horizon_days, origin"
        cur = self._conn.execute(self._q(sql), params)
        return [BacktestResult.model_validate(json.loads(r[0])) for r in cur.fetchall()]

    def save_accuracy_record(self, record: AccuracyRecord) -> None:
        if self.dialect == "postgres":
            sql = (
                "INSERT INTO accuracy_records (commodity, market, horizon_days, "
                "record_id, payload) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (commodity, market, horizon_days) DO UPDATE "
                "SET record_id = EXCLUDED.record_id, payload = EXCLUDED.payload"
            )
        else:
            sql = (
                "INSERT OR REPLACE INTO accuracy_records (commodity, market, "
                "horizon_days, record_id, payload) VALUES (?, ?, ?, ?, ?)"
            )
        self._conn.execute(
            sql,
            (
                record.commodity,
                record.market,
                record.horizon_days,
                record.record_id,
                record.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_accuracy_record(
        self, commodity: str, market: str, horizon_days: int
    ) -> AccuracyRecord | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM accuracy_records WHERE commodity = ? "
                "AND market = ? AND horizon_days = ?"
            ),
            (commodity, market, horizon_days),
        )
        row = cur.fetchone()
        return AccuracyRecord.model_validate(json.loads(row[0])) if row else None

    def list_accuracy_records(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[AccuracyRecord]:
        sql = "SELECT payload FROM accuracy_records"
        params: list = []
        clauses = []
        if commodity is not None:
            clauses.append("commodity = ?")
            params.append(commodity)
        if market is not None:
            clauses.append("market = ?")
            params.append(market)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY commodity, market, horizon_days"
        cur = self._conn.execute(self._q(sql), params)
        return [AccuracyRecord.model_validate(json.loads(r[0])) for r in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()


def build_store(sqlite_path: str | None = None, database_url: str | None = None) -> SqlStore:
    store = SqlStore(sqlite_path=sqlite_path, database_url=database_url)
    store.migrate()
    return store
