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

from fmcg_forecast.dashboards.models import (
    DashboardAssembly,
    DashboardSpec,
    DashboardView,
    DeskBoard,
)
from fmcg_forecast.alerts.models import (
    AlertAct,
    AlertDigest,
    AlertInstance,
    AlertSubscription,
    PriceCrossing,
)
from fmcg_forecast.events.models import MarketEvent
from fmcg_forecast.forecast.models import (
    AccuracyRecord,
    BacktestResult,
    Commentary,
    Forecast,
    ForecastApproval,
)
from fmcg_forecast.migrations import apply_migrations
from fmcg_forecast.models import EventRecord, Manifest, Observation
from fmcg_forecast.planning.models import CoverageAssessment, RequirementPlan
from fmcg_forecast.scenarios.models import (
    ScenarioAdoption,
    ScenarioRequest,
    ScenarioRun,
)
from fmcg_forecast.intake.models import IntakeCheckAct, IntakeEntry
from fmcg_forecast.signals.models import BuySignal
from fmcg_forecast.thin.models import ThinAssessment
from fmcg_forecast.sentiment.models import (
    SentimentCorpusManifest,
    SentimentExtraction,
    SentimentIndex,
    SentimentItem,
)


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
    # -- sentiment corpus + artefacts (R4) ------------------------------
    def insert_sentiment_items(self, items: list[SentimentItem]) -> int: ...
    def list_sentiment_items(
        self, commodity: str | None = None
    ) -> list[SentimentItem]: ...
    def get_sentiment_item(self, item_id: str) -> SentimentItem | None: ...
    def save_sentiment_manifest(self, manifest: SentimentCorpusManifest) -> None: ...
    def get_sentiment_manifest(self) -> SentimentCorpusManifest | None: ...
    def insert_extraction(self, extraction: SentimentExtraction) -> None: ...
    def get_extraction(self, item_id: str) -> SentimentExtraction | None: ...
    def list_extractions(
        self, commodity: str | None = None
    ) -> list[SentimentExtraction]: ...
    def insert_index(self, index: SentimentIndex) -> None: ...
    def list_indices(self, commodity: str) -> list[SentimentIndex]: ...
    def get_index(
        self, commodity: str, week_start: date
    ) -> SentimentIndex | None: ...
    # -- governed event registry (R5) ----------------------------------
    def insert_market_event(self, event: MarketEvent) -> None: ...
    def get_market_event(self, event_id: str) -> MarketEvent | None: ...
    def list_market_events(
        self, commodity: str | None = None
    ) -> list[MarketEvent]: ...
    # -- scenario studio (R6) ------------------------------------------
    def insert_scenario_request(self, request: ScenarioRequest) -> None: ...
    def get_scenario_request(self, request_id: str) -> ScenarioRequest | None: ...
    def list_scenario_requests(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[ScenarioRequest]: ...
    def insert_scenario(self, run: ScenarioRun) -> None: ...
    def get_scenario(self, scenario_id: str) -> ScenarioRun | None: ...
    def list_scenarios(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[ScenarioRun]: ...
    def set_scenario_status(self, scenario_id: str, status: str) -> None: ...
    def insert_scenario_adoption(self, adoption: ScenarioAdoption) -> None: ...
    def get_scenario_adoption(
        self, scenario_id: str
    ) -> ScenarioAdoption | None: ...
    # -- dashboards + desk board (R7) --------------------------------
    def insert_dashboard_spec(self, spec: DashboardSpec) -> None: ...
    def get_dashboard_spec(self, spec_id: str) -> DashboardSpec | None: ...
    def list_dashboard_specs(self) -> list[DashboardSpec]: ...
    def insert_dashboard_assembly(self, assembly: DashboardAssembly) -> None: ...
    def get_dashboard_assembly(
        self, assembly_id: str
    ) -> DashboardAssembly | None: ...
    def list_dashboard_assemblies(
        self, spec_id: str | None = None
    ) -> list[DashboardAssembly]: ...
    def insert_dashboard_view(self, view: DashboardView) -> None: ...
    def get_dashboard_view(self, view_id: str) -> DashboardView | None: ...
    def list_dashboard_views(
        self, name: str | None = None
    ) -> list[DashboardView]: ...
    def insert_desk_board(self, board: DeskBoard) -> None: ...
    def get_desk_board(self, board_id: str) -> DeskBoard | None: ...
    def list_desk_boards(self) -> list[DeskBoard]: ...
    # -- buy signals + coverage planning (R8) -------------------------
    def insert_buy_signal(self, signal: BuySignal) -> None: ...
    def get_buy_signal(self, signal_id: str) -> BuySignal | None: ...
    def list_buy_signals(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[BuySignal]: ...
    def insert_requirement_plan(self, plan: RequirementPlan) -> None: ...
    def get_requirement_plan(self, plan_id: str) -> RequirementPlan | None: ...
    def list_requirement_plans(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[RequirementPlan]: ...
    def insert_coverage_assessment(self, assessment: CoverageAssessment) -> None: ...
    def get_coverage_assessment(
        self, assessment_id: str
    ) -> CoverageAssessment | None: ...
    def list_coverage_assessments(
        self, plan_id: str | None = None
    ) -> list[CoverageAssessment]: ...
    # -- alerting, subscriptions and escalation (R9) -------------------
    def insert_alert_subscription(self, subscription: AlertSubscription) -> None: ...
    def get_alert_subscription(
        self, subscription_id: str
    ) -> AlertSubscription | None: ...
    def list_alert_subscriptions(
        self, subscriber: str | None = None
    ) -> list[AlertSubscription]: ...
    def insert_price_crossing(self, crossing: PriceCrossing) -> None: ...
    def get_price_crossing(self, crossing_id: str) -> PriceCrossing | None: ...
    def list_price_crossings(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[PriceCrossing]: ...
    def insert_alert(self, alert: AlertInstance) -> None: ...
    def get_alert(self, alert_id: str) -> AlertInstance | None: ...
    def list_alerts(
        self,
        commodity: str | None = None,
        market: str | None = None,
        subscription_id: str | None = None,
    ) -> list[AlertInstance]: ...
    def insert_alert_act(self, act: AlertAct) -> None: ...
    def get_alert_act(self, act_id: str) -> AlertAct | None: ...
    def list_alert_acts(
        self, alert_id: str | None = None
    ) -> list[AlertAct]: ...
    def insert_alert_digest(self, digest: AlertDigest) -> None: ...
    def get_alert_digest(self, digest_id: str) -> AlertDigest | None: ...
    def list_alert_digests(
        self, subscription_id: str | None = None
    ) -> list[AlertDigest]: ...
    # -- thin-data assessments + assisted intake (R10) -----------------
    def insert_thin_assessment(self, assessment: ThinAssessment) -> None: ...
    def get_thin_assessment(
        self, assessment_id: str
    ) -> ThinAssessment | None: ...
    def list_thin_assessments(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[ThinAssessment]: ...
    def insert_intake_entry(self, entry: IntakeEntry) -> None: ...
    def get_intake_entry(self, entry_id: str) -> IntakeEntry | None: ...
    def list_intake_entries(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[IntakeEntry]: ...
    def insert_intake_check_act(self, act: IntakeCheckAct) -> None: ...
    def get_intake_check_act(self, act_id: str) -> IntakeCheckAct | None: ...
    def list_intake_check_acts(
        self, entry_id: str | None = None
    ) -> list[IntakeCheckAct]: ...
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

    # -- sentiment corpus + artefacts (R4) ------------------------------
    # Items are insert-only, like observations: a duplicate item id
    # fails loudly instead of overwriting a headline of record.
    # Extractions and indices are content-addressed artefacts keyed
    # by their id, with one CURRENT row per item / (commodity,
    # week): the service checks the content address before
    # inserting, so a re-run under the same pack is a no-op. The
    # corpus manifest is product data only — it never carries the
    # planted intent (that is grading-side, behind the grading
    # store).

    def insert_sentiment_items(self, items: list[SentimentItem]) -> int:
        sql = self._q(
            "INSERT INTO sentiment_items (item_id, commodity, item_date, "
            "source, headline) VALUES (?, ?, ?, ?, ?)"
        )
        self._conn.executemany(
            sql,
            [
                (
                    i.item_id,
                    i.commodity,
                    self._date_param(i.item_date),
                    i.source,
                    i.headline,
                )
                for i in items
            ],
        )
        if self.dialect == "sqlite":
            self._conn.commit()
        return len(items)

    def list_sentiment_items(
        self, commodity: str | None = None
    ) -> list[SentimentItem]:
        sql = (
            "SELECT item_id, commodity, item_date, source, headline "
            "FROM sentiment_items"
        )
        params: list = []
        if commodity is not None:
            sql += " WHERE commodity = ?"
            params.append(commodity)
        sql += " ORDER BY item_date, item_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            SentimentItem(
                item_id=r[0], commodity=r[1], item_date=_as_date(r[2]),
                source=r[3], headline=r[4],
            )
            for r in cur.fetchall()
        ]

    def get_sentiment_item(self, item_id: str) -> SentimentItem | None:
        cur = self._conn.execute(
            self._q(
                "SELECT item_id, commodity, item_date, source, headline "
                "FROM sentiment_items WHERE item_id = ?"
            ),
            (item_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return SentimentItem(
            item_id=row[0], commodity=row[1], item_date=_as_date(row[2]),
            source=row[3], headline=row[4],
        )

    def save_sentiment_manifest(self, manifest: SentimentCorpusManifest) -> None:
        sql = self._q(
            "INSERT INTO sentiment_corpus_manifest (id, payload) VALUES (1, ?) "
            "ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload"
            if self.dialect == "postgres"
            else "INSERT OR REPLACE INTO sentiment_corpus_manifest (id, payload) VALUES (1, ?)"
        )
        self._conn.execute(sql, (manifest.model_dump_json(),))
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_sentiment_manifest(self) -> SentimentCorpusManifest | None:
        cur = self._conn.execute(
            "SELECT payload FROM sentiment_corpus_manifest WHERE id = 1"
        )
        row = cur.fetchone()
        if row is None:
            return None
        return SentimentCorpusManifest.model_validate(json.loads(row[0]))

    def insert_extraction(self, extraction: SentimentExtraction) -> None:
        sql = self._q(
            "INSERT INTO sentiment_extractions (extraction_id, item_id, "
            "commodity, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                extraction.extraction_id,
                extraction.item_id,
                extraction.commodity,
                extraction.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_extraction(self, item_id: str) -> SentimentExtraction | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM sentiment_extractions WHERE item_id = ?"
            ),
            (item_id,),
        )
        row = cur.fetchone()
        return (
            SentimentExtraction.model_validate(json.loads(row[0])) if row else None
        )

    def list_extractions(
        self, commodity: str | None = None
    ) -> list[SentimentExtraction]:
        sql = "SELECT payload FROM sentiment_extractions"
        params: list = []
        if commodity is not None:
            sql += " WHERE commodity = ?"
            params.append(commodity)
        # Item ids are assigned in date order at planting, so id
        # order is date order.
        sql += " ORDER BY item_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            SentimentExtraction.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_index(self, index: SentimentIndex) -> None:
        sql = self._q(
            "INSERT INTO sentiment_indices (index_id, commodity, week_start, "
            "payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                index.index_id,
                index.commodity,
                self._date_param(index.week_start),
                index.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def list_indices(self, commodity: str) -> list[SentimentIndex]:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM sentiment_indices WHERE commodity = ? "
                "ORDER BY week_start"
            ),
            (commodity,),
        )
        return [
            SentimentIndex.model_validate(json.loads(r[0])) for r in cur.fetchall()
        ]

    def get_index(
        self, commodity: str, week_start: date
    ) -> SentimentIndex | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM sentiment_indices WHERE commodity = ? "
                "AND week_start = ?"
            ),
            (commodity, self._date_param(week_start)),
        )
        row = cur.fetchone()
        return SentimentIndex.model_validate(json.loads(row[0])) if row else None

    # -- governed event registry (R5) ----------------------------------
    # Declarations are insert-only, like forecasts: the service
    # checks the content address before inserting, so re-declaring
    # or re-seeding the same event is a no-op rather than a
    # duplicate-write error, and a stored declaration is never
    # rewritten.

    def insert_market_event(self, event: MarketEvent) -> None:
        sql = self._q(
            "INSERT INTO market_events (event_id, commodity, event_class, "
            "window_start, payload) VALUES (?, ?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                event.event_id,
                event.commodity,
                event.event_class,
                self._date_param(event.window_start),
                event.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_market_event(self, event_id: str) -> MarketEvent | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM market_events WHERE event_id = ?"),
            (event_id,),
        )
        row = cur.fetchone()
        return MarketEvent.model_validate(json.loads(row[0])) if row else None

    def list_market_events(
        self, commodity: str | None = None
    ) -> list[MarketEvent]:
        sql = "SELECT payload FROM market_events"
        params: list = []
        if commodity is not None:
            sql += " WHERE commodity = ?"
            params.append(commodity)
        sql += " ORDER BY window_start, event_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            MarketEvent.model_validate(json.loads(r[0])) for r in cur.fetchall()
        ]

    # -- scenario studio (R6) ------------------------------------------
    # Requests and runs are insert-only, like forecasts: the
    # service checks the content address before inserting, so a
    # re-parse or re-run is a no-op rather than a duplicate-write
    # error. A run's payload is stored without its lifecycle
    # status (the status column is the state of record, flipped
    # only by set_scenario_status when an adoption act lands).

    def insert_scenario_request(self, request: ScenarioRequest) -> None:
        sql = self._q(
            "INSERT INTO scenario_requests (request_id, commodity, "
            "market, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                request.request_id,
                request.commodity,
                request.market,
                request.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_scenario_request(self, request_id: str) -> ScenarioRequest | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM scenario_requests WHERE request_id = ?"
            ),
            (request_id,),
        )
        row = cur.fetchone()
        return ScenarioRequest.model_validate(json.loads(row[0])) if row else None

    def list_scenario_requests(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[ScenarioRequest]:
        sql = "SELECT payload FROM scenario_requests"
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
        sql += " ORDER BY request_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            ScenarioRequest.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_scenario(self, run: ScenarioRun) -> None:
        sql = self._q(
            "INSERT INTO scenarios (scenario_id, base_forecast_id, "
            "commodity, market, status, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                run.scenario_id,
                run.base_forecast_id,
                run.commodity,
                run.market,
                run.status,
                run.model_dump_json(exclude={"status"}),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def _scenario_from_row(self, row) -> ScenarioRun:
        payload = json.loads(row[0])
        payload["status"] = row[1]
        return ScenarioRun.model_validate(payload)

    def get_scenario(self, scenario_id: str) -> ScenarioRun | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload, status FROM scenarios WHERE scenario_id = ?"
            ),
            (scenario_id,),
        )
        row = cur.fetchone()
        return self._scenario_from_row(row) if row else None

    def list_scenarios(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[ScenarioRun]:
        sql = "SELECT payload, status FROM scenarios"
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
        sql += " ORDER BY scenario_id"
        cur = self._conn.execute(self._q(sql), params)
        return [self._scenario_from_row(r) for r in cur.fetchall()]

    def set_scenario_status(self, scenario_id: str, status: str) -> None:
        self._conn.execute(
            self._q("UPDATE scenarios SET status = ? WHERE scenario_id = ?"),
            (status, scenario_id),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def insert_scenario_adoption(self, adoption: ScenarioAdoption) -> None:
        sql = self._q(
            "INSERT INTO scenario_adoptions (adoption_id, scenario_id, "
            "payload) VALUES (?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (adoption.adoption_id, adoption.scenario_id, adoption.model_dump_json()),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_scenario_adoption(
        self, scenario_id: str
    ) -> ScenarioAdoption | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM scenario_adoptions WHERE scenario_id = ?"
            ),
            (scenario_id,),
        )
        row = cur.fetchone()
        return ScenarioAdoption.model_validate(json.loads(row[0])) if row else None

    # -- dashboards + desk board (R7) ----------------------------------
    # Specs, assemblies, views and boards are insert-only, like
    # every other artefact: the service checks the content address
    # before inserting, so a re-ask / re-assembly / rebuild is a
    # no-op rather than a duplicate-write error. An assembly's
    # payload is stored whole (HTML included): the page is a pure
    # function of the resolved panels, and the verifier re-renders
    # it byte-for-byte from the stored spec + panels.

    def insert_dashboard_spec(self, spec: DashboardSpec) -> None:
        sql = self._q(
            "INSERT INTO dashboard_specs (spec_id, prompt, asked_by, "
            "payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (spec.spec_id, spec.prompt, spec.asked_by, spec.model_dump_json()),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_dashboard_spec(self, spec_id: str) -> DashboardSpec | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM dashboard_specs WHERE spec_id = ?"),
            (spec_id,),
        )
        row = cur.fetchone()
        return DashboardSpec.model_validate(json.loads(row[0])) if row else None

    def list_dashboard_specs(self) -> list[DashboardSpec]:
        cur = self._conn.execute(
            "SELECT payload FROM dashboard_specs ORDER BY spec_id"
        )
        return [
            DashboardSpec.model_validate(json.loads(r[0])) for r in cur.fetchall()
        ]

    def insert_dashboard_assembly(self, assembly: DashboardAssembly) -> None:
        sql = self._q(
            "INSERT INTO dashboard_assemblies (assembly_id, spec_id, "
            "seq, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                assembly.assembly_id,
                assembly.spec_id,
                assembly.seq,
                assembly.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_dashboard_assembly(
        self, assembly_id: str
    ) -> DashboardAssembly | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM dashboard_assemblies "
                "WHERE assembly_id = ?"
            ),
            (assembly_id,),
        )
        row = cur.fetchone()
        return (
            DashboardAssembly.model_validate(json.loads(row[0])) if row else None
        )

    def list_dashboard_assemblies(
        self, spec_id: str | None = None
    ) -> list[DashboardAssembly]:
        sql = "SELECT payload FROM dashboard_assemblies"
        params: list = []
        if spec_id is not None:
            sql += " WHERE spec_id = ?"
            params.append(spec_id)
        sql += " ORDER BY spec_id, seq"
        cur = self._conn.execute(self._q(sql), params)
        return [
            DashboardAssembly.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_dashboard_view(self, view: DashboardView) -> None:
        sql = self._q(
            "INSERT INTO dashboard_views (view_id, spec_id, name, "
            "payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (view.view_id, view.spec_id, view.name, view.model_dump_json()),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_dashboard_view(self, view_id: str) -> DashboardView | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM dashboard_views WHERE view_id = ?"),
            (view_id,),
        )
        row = cur.fetchone()
        return DashboardView.model_validate(json.loads(row[0])) if row else None

    def list_dashboard_views(
        self, name: str | None = None
    ) -> list[DashboardView]:
        sql = "SELECT payload FROM dashboard_views"
        params: list = []
        if name is not None:
            sql += " WHERE name = ?"
            params.append(name)
        sql += " ORDER BY name, view_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            DashboardView.model_validate(json.loads(r[0])) for r in cur.fetchall()
        ]

    def insert_desk_board(self, board: DeskBoard) -> None:
        sql = self._q(
            "INSERT INTO desk_boards (board_id, board_date, payload) "
            "VALUES (?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                board.board_id,
                self._date_param(board.board_date),
                board.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_desk_board(self, board_id: str) -> DeskBoard | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM desk_boards WHERE board_id = ?"),
            (board_id,),
        )
        row = cur.fetchone()
        return DeskBoard.model_validate(json.loads(row[0])) if row else None

    def list_desk_boards(self) -> list[DeskBoard]:
        cur = self._conn.execute(
            "SELECT payload FROM desk_boards ORDER BY board_date, board_id"
        )
        return [DeskBoard.model_validate(json.loads(r[0])) for r in cur.fetchall()]

    # -- buy signals + coverage planning (R8) --------------------------
    # Signals, plans and assessments are insert-only, like every
    # other artefact: the services check the content address before
    # inserting, so a re-computation or re-entry that lands on the
    # same content is a no-op rather than a duplicate-write error.

    def insert_buy_signal(self, signal: BuySignal) -> None:
        sql = self._q(
            "INSERT INTO buy_signals (signal_id, commodity, market, "
            "forecast_id, payload) VALUES (?, ?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                signal.signal_id,
                signal.commodity,
                signal.market,
                signal.forecast_id,
                signal.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_buy_signal(self, signal_id: str) -> BuySignal | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM buy_signals WHERE signal_id = ?"),
            (signal_id,),
        )
        row = cur.fetchone()
        return BuySignal.model_validate(json.loads(row[0])) if row else None

    def list_buy_signals(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[BuySignal]:
        sql = "SELECT payload FROM buy_signals"
        clauses, params = [], []
        if commodity is not None:
            clauses.append("commodity = ?")
            params.append(commodity)
        if market is not None:
            clauses.append("market = ?")
            params.append(market)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY commodity, market, signal_id"
        cur = self._conn.execute(self._q(sql), params)
        return [BuySignal.model_validate(json.loads(r[0])) for r in cur.fetchall()]

    def insert_requirement_plan(self, plan: RequirementPlan) -> None:
        sql = self._q(
            "INSERT INTO requirement_plans (plan_id, commodity, market, "
            "entered_by, payload) VALUES (?, ?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                plan.plan_id,
                plan.commodity,
                plan.market,
                plan.entered_by,
                plan.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_requirement_plan(self, plan_id: str) -> RequirementPlan | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM requirement_plans WHERE plan_id = ?"),
            (plan_id,),
        )
        row = cur.fetchone()
        return RequirementPlan.model_validate(json.loads(row[0])) if row else None

    def list_requirement_plans(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[RequirementPlan]:
        sql = "SELECT payload FROM requirement_plans"
        clauses, params = [], []
        if commodity is not None:
            clauses.append("commodity = ?")
            params.append(commodity)
        if market is not None:
            clauses.append("market = ?")
            params.append(market)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY commodity, market, plan_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            RequirementPlan.model_validate(json.loads(r[0])) for r in cur.fetchall()
        ]

    def insert_coverage_assessment(self, assessment: CoverageAssessment) -> None:
        sql = self._q(
            "INSERT INTO coverage_assessments (assessment_id, plan_id, "
            "forecast_id, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                assessment.assessment_id,
                assessment.plan_id,
                assessment.forecast_id,
                assessment.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_coverage_assessment(
        self, assessment_id: str
    ) -> CoverageAssessment | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM coverage_assessments "
                "WHERE assessment_id = ?"
            ),
            (assessment_id,),
        )
        row = cur.fetchone()
        return (
            CoverageAssessment.model_validate(json.loads(row[0])) if row else None
        )

    def list_coverage_assessments(
        self, plan_id: str | None = None
    ) -> list[CoverageAssessment]:
        sql = "SELECT payload FROM coverage_assessments"
        params: list = []
        if plan_id is not None:
            sql += " WHERE plan_id = ?"
            params.append(plan_id)
        sql += " ORDER BY plan_id, assessment_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            CoverageAssessment.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    # -- alerting, subscriptions and escalation (R9) -------------------
    # Subscriptions, crossings, alerts, acts and digests are
    # insert-only, like every other artefact: the services check
    # the content address before inserting, so a re-derivation or
    # re-entry that lands on the same content is a no-op rather
    # than a duplicate-write error.

    def insert_alert_subscription(self, subscription: AlertSubscription) -> None:
        sql = self._q(
            "INSERT INTO alert_subscriptions (subscription_id, "
            "subscriber, payload) VALUES (?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                subscription.subscription_id,
                subscription.subscriber,
                subscription.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_alert_subscription(
        self, subscription_id: str
    ) -> AlertSubscription | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM alert_subscriptions "
                "WHERE subscription_id = ?"
            ),
            (subscription_id,),
        )
        row = cur.fetchone()
        return (
            AlertSubscription.model_validate(json.loads(row[0]))
            if row
            else None
        )

    def list_alert_subscriptions(
        self, subscriber: str | None = None
    ) -> list[AlertSubscription]:
        sql = "SELECT payload FROM alert_subscriptions"
        params: list = []
        if subscriber is not None:
            sql += " WHERE subscriber = ?"
            params.append(subscriber)
        sql += " ORDER BY subscriber, subscription_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            AlertSubscription.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_price_crossing(self, crossing: PriceCrossing) -> None:
        sql = self._q(
            "INSERT INTO price_crossings (crossing_id, commodity, "
            "market, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                crossing.crossing_id,
                crossing.commodity,
                crossing.market,
                crossing.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_price_crossing(self, crossing_id: str) -> PriceCrossing | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM price_crossings WHERE crossing_id = ?"
            ),
            (crossing_id,),
        )
        row = cur.fetchone()
        return PriceCrossing.model_validate(json.loads(row[0])) if row else None

    def list_price_crossings(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[PriceCrossing]:
        sql = "SELECT payload FROM price_crossings"
        clauses, params = [], []
        if commodity is not None:
            clauses.append("commodity = ?")
            params.append(commodity)
        if market is not None:
            clauses.append("market = ?")
            params.append(market)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY commodity, market, crossing_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            PriceCrossing.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_alert(self, alert: AlertInstance) -> None:
        sql = self._q(
            "INSERT INTO alerts (alert_id, subscription_id, commodity, "
            "market, kind, payload) VALUES (?, ?, ?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                alert.alert_id,
                alert.subscription_id,
                alert.commodity,
                alert.market,
                alert.kind,
                alert.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_alert(self, alert_id: str) -> AlertInstance | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM alerts WHERE alert_id = ?"),
            (alert_id,),
        )
        row = cur.fetchone()
        return AlertInstance.model_validate(json.loads(row[0])) if row else None

    def list_alerts(
        self,
        commodity: str | None = None,
        market: str | None = None,
        subscription_id: str | None = None,
    ) -> list[AlertInstance]:
        sql = "SELECT payload FROM alerts"
        clauses, params = [], []
        if commodity is not None:
            clauses.append("commodity = ?")
            params.append(commodity)
        if market is not None:
            clauses.append("market = ?")
            params.append(market)
        if subscription_id is not None:
            clauses.append("subscription_id = ?")
            params.append(subscription_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY subscription_id, kind, commodity, market, alert_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            AlertInstance.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_alert_act(self, act: AlertAct) -> None:
        sql = self._q(
            "INSERT INTO alert_acts (act_id, alert_id, payload) "
            "VALUES (?, ?, ?)"
        )
        self._conn.execute(
            sql, (act.act_id, act.alert_id, act.model_dump_json())
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_alert_act(self, act_id: str) -> AlertAct | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM alert_acts WHERE act_id = ?"),
            (act_id,),
        )
        row = cur.fetchone()
        return AlertAct.model_validate(json.loads(row[0])) if row else None

    def list_alert_acts(self, alert_id: str | None = None) -> list[AlertAct]:
        sql = "SELECT payload FROM alert_acts"
        params: list = []
        if alert_id is not None:
            sql += " WHERE alert_id = ?"
            params.append(alert_id)
        sql += " ORDER BY alert_id, act_id"
        cur = self._conn.execute(self._q(sql), params)
        return [AlertAct.model_validate(json.loads(r[0])) for r in cur.fetchall()]

    def insert_alert_digest(self, digest: AlertDigest) -> None:
        sql = self._q(
            "INSERT INTO alert_digests (digest_id, subscription_id, "
            "digest_date, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                digest.digest_id,
                digest.subscription_id,
                self._date_param(digest.digest_date),
                digest.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_alert_digest(self, digest_id: str) -> AlertDigest | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM alert_digests WHERE digest_id = ?"
            ),
            (digest_id,),
        )
        row = cur.fetchone()
        return AlertDigest.model_validate(json.loads(row[0])) if row else None

    def list_alert_digests(
        self, subscription_id: str | None = None
    ) -> list[AlertDigest]:
        sql = "SELECT payload FROM alert_digests"
        params: list = []
        if subscription_id is not None:
            sql += " WHERE subscription_id = ?"
            params.append(subscription_id)
        sql += " ORDER BY subscription_id, digest_date, digest_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            AlertDigest.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    # -- thin-data assessments + assisted intake (R10) -----------------
    # Assessments, entries and check acts are insert-only payload
    # tables in the standing idiom: the services check the
    # content address before inserting, so a recomputation or
    # re-entry that lands on the same content is a no-op rather
    # than a duplicate-write error.

    def insert_thin_assessment(self, assessment: ThinAssessment) -> None:
        sql = self._q(
            "INSERT INTO thin_assessments (assessment_id, "
            "forecast_id, commodity, market, payload) "
            "VALUES (?, ?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                assessment.assessment_id,
                assessment.forecast_id,
                assessment.commodity,
                assessment.market,
                assessment.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_thin_assessment(
        self, assessment_id: str
    ) -> ThinAssessment | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM thin_assessments "
                "WHERE assessment_id = ?"
            ),
            (assessment_id,),
        )
        row = cur.fetchone()
        return (
            ThinAssessment.model_validate(json.loads(row[0])) if row else None
        )

    def list_thin_assessments(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[ThinAssessment]:
        sql = "SELECT payload FROM thin_assessments"
        clauses, params = [], []
        if commodity is not None:
            clauses.append("commodity = ?")
            params.append(commodity)
        if market is not None:
            clauses.append("market = ?")
            params.append(market)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY commodity, market, assessment_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            ThinAssessment.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_intake_entry(self, entry: IntakeEntry) -> None:
        sql = self._q(
            "INSERT INTO intake_entries (entry_id, commodity, "
            "market, obs_date, driver, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                entry.entry_id,
                entry.commodity,
                entry.market,
                self._date_param(entry.obs_date),
                entry.driver,
                entry.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_intake_entry(self, entry_id: str) -> IntakeEntry | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM intake_entries WHERE entry_id = ?"
            ),
            (entry_id,),
        )
        row = cur.fetchone()
        return IntakeEntry.model_validate(json.loads(row[0])) if row else None

    def list_intake_entries(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[IntakeEntry]:
        sql = "SELECT payload FROM intake_entries"
        clauses, params = [], []
        if commodity is not None:
            clauses.append("commodity = ?")
            params.append(commodity)
        if market is not None:
            clauses.append("market = ?")
            params.append(market)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY commodity, market, entry_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            IntakeEntry.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_intake_check_act(self, act: IntakeCheckAct) -> None:
        sql = self._q(
            "INSERT INTO intake_check_acts (act_id, entry_id, "
            "payload) VALUES (?, ?, ?)"
        )
        self._conn.execute(
            sql, (act.act_id, act.entry_id, act.model_dump_json())
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_intake_check_act(self, act_id: str) -> IntakeCheckAct | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM intake_check_acts WHERE act_id = ?"
            ),
            (act_id,),
        )
        row = cur.fetchone()
        return (
            IntakeCheckAct.model_validate(json.loads(row[0])) if row else None
        )

    def list_intake_check_acts(
        self, entry_id: str | None = None
    ) -> list[IntakeCheckAct]:
        sql = "SELECT payload FROM intake_check_acts"
        params: list = []
        if entry_id is not None:
            sql += " WHERE entry_id = ?"
            params.append(entry_id)
        sql += " ORDER BY entry_id, act_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            IntakeCheckAct.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def close(self) -> None:
        self._conn.close()


def build_store(sqlite_path: str | None = None, database_url: str | None = None) -> SqlStore:
    store = SqlStore(sqlite_path=sqlite_path, database_url=database_url)
    store.migrate()
    return store
