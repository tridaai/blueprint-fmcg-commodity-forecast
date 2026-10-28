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

    def close(self) -> None:
        self._conn.close()


def build_store(sqlite_path: str | None = None, database_url: str | None = None) -> SqlStore:
    store = SqlStore(sqlite_path=sqlite_path, database_url=database_url)
    store.migrate()
    return store
