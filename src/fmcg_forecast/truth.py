"""The grading-truth store — the sealed future path.

The generator emits the next 90 days of every series alongside the
history. Those rows are the truth the forecast engine will be graded
against (R3 backtesting), so they live behind this module alone:

- the dataset *load* path writes them here (it is the generator's
  own output, sealed at load time);
- graders and the eval gate read them here;
- **the forecast package must never import this module** — that
  isolation is enforced by a structural test and the eval gate.

Truth rows are insert-only, exactly like observations.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from fmcg_forecast.migrations import apply_migrations
from fmcg_forecast.models import Observation
from fmcg_forecast.store import _as_date


class TruthStore:
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

    def _q(self, sql: str) -> str:
        return sql.replace("?", self._ph) if self.dialect == "postgres" else sql

    def _date_param(self, value: date):
        return value if self.dialect == "postgres" else value.isoformat()

    def migrate(self) -> list[str]:
        return apply_migrations(self._conn, self.dialect, self._ph)

    def insert_truth(self, rows: list[Observation]) -> int:
        sql = self._q(
            "INSERT INTO truth_observations (commodity, market, obs_date, driver, value) "
            "VALUES (?, ?, ?, ?, ?)"
        )
        self._conn.cursor().executemany(
            sql,
            [
                (r.commodity, r.market, self._date_param(r.obs_date), r.driver, r.value)
                for r in rows
            ],
        )
        if self.dialect == "sqlite":
            self._conn.commit()
        return len(rows)

    def read_truth(
        self,
        commodity: str,
        market: str,
        driver: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Observation]:
        sql = (
            "SELECT commodity, market, obs_date, driver, value FROM truth_observations "
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

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM truth_observations")
        return int(cur.fetchone()[0])

    def close(self) -> None:
        self._conn.close()


def build_truth_store(
    sqlite_path: str | None = None, database_url: str | None = None
) -> TruthStore:
    store = TruthStore(sqlite_path=sqlite_path, database_url=database_url)
    store.migrate()
    return store
