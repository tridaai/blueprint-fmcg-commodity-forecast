"""The sentiment intent store — grading side only.

The corpus plants every headline from known lexicon phrases, so
what each item was *meant* to read as is known exactly. Those
intents are the grading truth for extraction — and like the
sealed future price path behind ``fmcg_forecast.truth``, they
live behind this module alone:

- the corpus *load* path writes them here (they are the
  generator's own planting record, sealed at load time);
- graders and the eval gate read them here;
- **the scoring path must never import this module** — extraction
  is graded against headlines alone. The isolation is enforced by
  a structural test and the eval gate, mirroring the truth store.

Intent rows are insert-only, exactly like observations.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fmcg_forecast.migrations import apply_migrations
from fmcg_forecast.sentiment.corpus import PlantedIntent


class SentimentGradingStore:
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

    def migrate(self) -> list[str]:
        return apply_migrations(self._conn, self.dialect, self._ph)

    def insert_intents(self, intents: list[PlantedIntent]) -> int:
        sql = self._q(
            "INSERT INTO sentiment_intent (item_id, payload) VALUES (?, ?)"
        )
        self._conn.executemany(
            sql, [(i.item_id, i.model_dump_json()) for i in intents]
        )
        if self.dialect == "sqlite":
            self._conn.commit()
        return len(intents)

    def get_intent(self, item_id: str) -> PlantedIntent | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM sentiment_intent WHERE item_id = ?"),
            (item_id,),
        )
        row = cur.fetchone()
        return PlantedIntent.model_validate(json.loads(row[0])) if row else None

    def list_intents(self) -> list[PlantedIntent]:
        cur = self._conn.execute(
            "SELECT payload FROM sentiment_intent ORDER BY item_id"
        )
        return [
            PlantedIntent.model_validate(json.loads(r[0])) for r in cur.fetchall()
        ]

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM sentiment_intent")
        return int(cur.fetchone()[0])

    def close(self) -> None:
        self._conn.close()


def build_sentiment_grading_store(
    sqlite_path: str | None = None, database_url: str | None = None
) -> SentimentGradingStore:
    store = SentimentGradingStore(sqlite_path=sqlite_path, database_url=database_url)
    store.migrate()
    return store
