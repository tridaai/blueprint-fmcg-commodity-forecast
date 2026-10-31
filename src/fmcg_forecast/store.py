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
from fmcg_forecast.ingest.models import (
    BackfillReplay,
    CandidateRow,
    Correction,
    IngestBatch,
    ProvenanceRow,
    QuarantineRecord,
    SourceRegistration,
)
from fmcg_forecast.analytics.models import OpsReport
from fmcg_forecast.console.models import (
    EventTriageAct,
    ForecastRejection,
    PreflightReport,
)
from fmcg_forecast.geo.models import (
    BasisReading,
    CostLineEntry,
    LandedComparison,
    MarketMap,
)
from fmcg_forecast.desk.models import (
    ArtefactComment,
    DecisionAct,
    DecisionCase,
    DecisionLog,
    FollowUpTask,
    PolicyVersion,
    TaskAct,
)
from fmcg_forecast.access.models import (
    AccessEntry,
    AccessLog,
    PrincipalGrant,
)
from fmcg_forecast.masterdata.models import MasterDataVersion
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
    # -- production data plane (R11) ------------------------------------
    def insert_ingest_source(self, registration: SourceRegistration) -> None: ...
    def get_ingest_source(self, source_id: str) -> SourceRegistration | None: ...
    def list_ingest_sources(self) -> list[SourceRegistration]: ...
    def insert_ingest_batch(self, batch: IngestBatch) -> None: ...
    def get_ingest_batch(self, batch_id: str) -> IngestBatch | None: ...
    def list_ingest_batches(
        self, source_id: str | None = None
    ) -> list[IngestBatch]: ...
    def insert_ingest_candidates(
        self, batch_id: str, rows: list[CandidateRow]
    ) -> None: ...
    def list_ingest_candidates(self, batch_id: str) -> list[CandidateRow]: ...
    def insert_quarantine_record(self, record: QuarantineRecord) -> None: ...
    def get_quarantine_record(
        self, quarantine_id: str
    ) -> QuarantineRecord | None: ...
    def list_quarantine_records(
        self, batch_id: str | None = None
    ) -> list[QuarantineRecord]: ...
    def insert_provenance(self, rows: list[ProvenanceRow]) -> None: ...
    def get_provenance(
        self, commodity: str, market: str, obs_date: date, driver: str
    ) -> ProvenanceRow | None: ...
    def list_provenance(
        self,
        batch_id: str | None = None,
        source_id: str | None = None,
    ) -> list[ProvenanceRow]: ...
    def insert_correction(self, correction: Correction) -> None: ...
    def get_correction(self, correction_id: str) -> Correction | None: ...
    def list_corrections(
        self,
        commodity: str | None = None,
        market: str | None = None,
        obs_date: date | None = None,
        driver: str | None = None,
    ) -> list[Correction]: ...
    def insert_backfill_replay(self, replay: BackfillReplay) -> None: ...
    def get_backfill_replay(self, replay_id: str) -> BackfillReplay | None: ...
    def list_backfill_replays(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[BackfillReplay]: ...
    def insert_ops_report(self, report: OpsReport) -> None: ...
    def get_ops_report(self, report_id: str) -> OpsReport | None: ...
    def list_ops_reports(self) -> list[OpsReport]: ...
    # -- operator console (R13) --------------------------------------
    def insert_forecast_rejection(self, rejection: ForecastRejection) -> None: ...
    def get_forecast_rejection(
        self, forecast_id: str
    ) -> ForecastRejection | None: ...
    def list_forecast_rejections(self) -> list[ForecastRejection]: ...
    def insert_event_triage_act(self, act: EventTriageAct) -> None: ...
    def get_event_triage_act(self, act_id: str) -> EventTriageAct | None: ...
    def list_event_triage_acts(
        self, event_id: str | None = None
    ) -> list[EventTriageAct]: ...
    def insert_preflight_report(self, report: PreflightReport) -> None: ...
    def get_preflight_report(self, report_id: str) -> PreflightReport | None: ...
    def list_preflight_reports(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[PreflightReport]: ...
    # -- geospatial basis & netting (R14) -----------------------------
    def insert_cost_line_entry(self, entry: CostLineEntry) -> None: ...
    def get_cost_line_entry(
        self, entry_id: str
    ) -> CostLineEntry | None: ...
    def list_cost_line_entries(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[CostLineEntry]: ...
    def insert_basis_reading(self, reading: BasisReading) -> None: ...
    def get_basis_reading(
        self, reading_id: str
    ) -> BasisReading | None: ...
    def list_basis_readings(
        self, commodity: str | None = None
    ) -> list[BasisReading]: ...
    def insert_landed_comparison(
        self, comparison: LandedComparison
    ) -> None: ...
    def get_landed_comparison(
        self, comparison_id: str
    ) -> LandedComparison | None: ...
    def list_landed_comparisons(
        self, commodity: str | None = None
    ) -> list[LandedComparison]: ...
    def insert_market_map(self, market_map: MarketMap) -> None: ...
    def get_market_map(self, map_id: str) -> MarketMap | None: ...
    def list_market_maps(
        self, commodity: str | None = None
    ) -> list[MarketMap]: ...
    # -- desk policy versions, decisions, log, annotations (R15) --
    def insert_policy_version(self, version: PolicyVersion) -> None: ...
    def get_policy_version(
        self, version_id: str
    ) -> PolicyVersion | None: ...
    def list_policy_versions(self) -> list[PolicyVersion]: ...
    def set_policy_version_status(
        self, version_id: str, status: str
    ) -> None: ...
    def insert_decision(self, decision: DecisionCase) -> None: ...
    def get_decision(
        self, decision_id: str
    ) -> DecisionCase | None: ...
    def list_decisions(
        self, kind: str | None = None, target_id: str | None = None
    ) -> list[DecisionCase]: ...
    def insert_decision_act(self, act: DecisionAct) -> None: ...
    def get_decision_act(self, act_id: str) -> DecisionAct | None: ...
    def list_decision_acts(
        self, decision_id: str | None = None
    ) -> list[DecisionAct]: ...
    def insert_decision_log(self, log: DecisionLog) -> None: ...
    def get_decision_log(self, log_id: str) -> DecisionLog | None: ...
    def list_decision_logs(self) -> list[DecisionLog]: ...
    def insert_comment(self, comment: ArtefactComment) -> None: ...
    def get_comment(
        self, comment_id: str
    ) -> ArtefactComment | None: ...
    def list_comments(
        self, target_kind: str | None = None,
        target_id: str | None = None,
    ) -> list[ArtefactComment]: ...
    def insert_task(self, task: FollowUpTask) -> None: ...
    def get_task(self, task_id: str) -> FollowUpTask | None: ...
    def list_tasks(
        self, target_kind: str | None = None,
        target_id: str | None = None,
    ) -> list[FollowUpTask]: ...
    def insert_task_act(self, act: TaskAct) -> None: ...
    def get_task_act(self, act_id: str) -> TaskAct | None: ...
    def list_task_acts(self, task_id: str) -> list[TaskAct]: ...
    # -- access grants, read entries, audit logs (R16) --
    def insert_principal_grant(self, grant: PrincipalGrant) -> None: ...
    def get_principal_grant(
        self, grant_id: str
    ) -> PrincipalGrant | None: ...
    def list_principal_grants(self) -> list[PrincipalGrant]: ...
    def insert_access_entry(self, entry: AccessEntry) -> None: ...
    def get_access_entry(self, entry_id: str) -> AccessEntry | None: ...
    def list_access_entries(self) -> list[AccessEntry]: ...
    def insert_access_log(self, log: AccessLog) -> None: ...
    def get_access_log(self, log_id: str) -> AccessLog | None: ...
    def list_access_logs(self) -> list[AccessLog]: ...
    # -- master data versions (R16) --
    def insert_master_data_version(
        self, version: MasterDataVersion
    ) -> None: ...
    def get_master_data_version(
        self, version_id: str
    ) -> MasterDataVersion | None: ...
    def list_master_data_versions(self) -> list[MasterDataVersion]: ...
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

    def _executemany(self, sql: str, params) -> None:
        # psycopg3 connections have no executemany (cursors do);
        # sqlite3 cursors carry it too, so the cursor is the
        # dialect-neutral surface for batch inserts.
        self._conn.cursor().executemany(sql, params)

    # -- schema --------------------------------------------------------
    def migrate(self) -> list[str]:
        return apply_migrations(self._conn, self.dialect, self._ph)

    # -- writes (insert-only) ------------------------------------------
    def insert_observations(self, rows: list[Observation]) -> int:
        sql = self._q(
            "INSERT INTO observations (commodity, market, obs_date, driver, value) "
            "VALUES (?, ?, ?, ?, ?)"
        )
        self._executemany(
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
        self._executemany(
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
        self._executemany(
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

    # -- production data plane (R11) -----------------------------------
    # Registry entries, batches, candidate rows, quarantine
    # records, corrections and replays are insert-only, like
    # every other artefact: the services check the content
    # address before inserting, so a replayed delivery or a
    # re-entered act is a no-op rather than a duplicate-write
    # error. Provenance rows are written once per landed
    # observation, in the same act that lands it.

    def insert_ingest_source(self, registration: SourceRegistration) -> None:
        sql = self._q(
            "INSERT INTO ingest_sources (source_id, payload) VALUES (?, ?)"
        )
        self._conn.execute(
            sql, (registration.source_id, registration.model_dump_json())
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_ingest_source(self, source_id: str) -> SourceRegistration | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM ingest_sources WHERE source_id = ?"),
            (source_id,),
        )
        row = cur.fetchone()
        return SourceRegistration.model_validate(json.loads(row[0])) if row else None

    def list_ingest_sources(self) -> list[SourceRegistration]:
        cur = self._conn.execute(
            "SELECT payload FROM ingest_sources ORDER BY source_id"
        )
        return [
            SourceRegistration.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_ingest_batch(self, batch: IngestBatch) -> None:
        sql = self._q(
            "INSERT INTO ingest_batches (batch_id, source_id, status, "
            "payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                batch.batch_id,
                batch.source_id,
                batch.status,
                batch.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_ingest_batch(self, batch_id: str) -> IngestBatch | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM ingest_batches WHERE batch_id = ?"),
            (batch_id,),
        )
        row = cur.fetchone()
        return IngestBatch.model_validate(json.loads(row[0])) if row else None

    def list_ingest_batches(
        self, source_id: str | None = None
    ) -> list[IngestBatch]:
        sql = "SELECT payload FROM ingest_batches"
        params: list = []
        if source_id is not None:
            sql += " WHERE source_id = ?"
            params.append(source_id)
        sql += " ORDER BY source_id, batch_id"
        cur = self._conn.execute(self._q(sql), params)
        return [IngestBatch.model_validate(json.loads(r[0])) for r in cur.fetchall()]

    def insert_ingest_candidates(
        self, batch_id: str, rows: list[CandidateRow]
    ) -> None:
        sql = self._q(
            "INSERT INTO ingest_candidates (batch_id, row_index, payload) "
            "VALUES (?, ?, ?)"
        )
        self._executemany(
            sql,
            [(batch_id, r.row_index, r.model_dump_json()) for r in rows],
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def list_ingest_candidates(self, batch_id: str) -> list[CandidateRow]:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM ingest_candidates WHERE batch_id = ? "
                "ORDER BY row_index"
            ),
            (batch_id,),
        )
        return [CandidateRow.model_validate(json.loads(r[0])) for r in cur.fetchall()]

    def insert_quarantine_record(self, record: QuarantineRecord) -> None:
        sql = self._q(
            "INSERT INTO ingest_quarantine (quarantine_id, batch_id, "
            "row_index, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                record.quarantine_id,
                record.batch_id,
                record.row_index,
                record.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_quarantine_record(
        self, quarantine_id: str
    ) -> QuarantineRecord | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM ingest_quarantine WHERE quarantine_id = ?"
            ),
            (quarantine_id,),
        )
        row = cur.fetchone()
        return QuarantineRecord.model_validate(json.loads(row[0])) if row else None

    def list_quarantine_records(
        self, batch_id: str | None = None
    ) -> list[QuarantineRecord]:
        sql = "SELECT payload FROM ingest_quarantine"
        params: list = []
        if batch_id is not None:
            sql += " WHERE batch_id = ?"
            params.append(batch_id)
        sql += " ORDER BY batch_id, row_index"
        cur = self._conn.execute(self._q(sql), params)
        return [
            QuarantineRecord.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_provenance(self, rows: list[ProvenanceRow]) -> None:
        sql = self._q(
            "INSERT INTO observation_provenance (commodity, market, "
            "obs_date, driver, source_id, batch_id, row_index) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        self._executemany(
            sql,
            [
                (
                    r.commodity,
                    r.market,
                    self._date_param(r.obs_date),
                    r.driver,
                    r.source_id,
                    r.batch_id,
                    r.row_index,
                )
                for r in rows
            ],
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_provenance(
        self, commodity: str, market: str, obs_date: date, driver: str
    ) -> ProvenanceRow | None:
        cur = self._conn.execute(
            self._q(
                "SELECT commodity, market, obs_date, driver, source_id, "
                "batch_id, row_index FROM observation_provenance "
                "WHERE commodity = ? AND market = ? AND obs_date = ? "
                "AND driver = ?"
            ),
            (commodity, market, self._date_param(obs_date), driver),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return ProvenanceRow(
            commodity=row[0], market=row[1], obs_date=_as_date(row[2]),
            driver=row[3], source_id=row[4], batch_id=row[5],
            row_index=int(row[6]),
        )

    def list_provenance(
        self,
        batch_id: str | None = None,
        source_id: str | None = None,
    ) -> list[ProvenanceRow]:
        sql = (
            "SELECT commodity, market, obs_date, driver, source_id, "
            "batch_id, row_index FROM observation_provenance"
        )
        clauses, params = [], []
        if batch_id is not None:
            clauses.append("batch_id = ?")
            params.append(batch_id)
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY commodity, market, obs_date, driver"
        cur = self._conn.execute(self._q(sql), params)
        return [
            ProvenanceRow(
                commodity=r[0], market=r[1], obs_date=_as_date(r[2]),
                driver=r[3], source_id=r[4], batch_id=r[5],
                row_index=int(r[6]),
            )
            for r in cur.fetchall()
        ]

    def insert_correction(self, correction: Correction) -> None:
        sql = self._q(
            "INSERT INTO ingest_corrections (correction_id, commodity, "
            "market, obs_date, driver, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                correction.correction_id,
                correction.commodity,
                correction.market,
                self._date_param(correction.obs_date),
                correction.driver,
                correction.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_correction(self, correction_id: str) -> Correction | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM ingest_corrections WHERE correction_id = ?"
            ),
            (correction_id,),
        )
        row = cur.fetchone()
        return Correction.model_validate(json.loads(row[0])) if row else None

    def list_corrections(
        self,
        commodity: str | None = None,
        market: str | None = None,
        obs_date: date | None = None,
        driver: str | None = None,
    ) -> list[Correction]:
        sql = "SELECT payload FROM ingest_corrections"
        clauses, params = [], []
        if commodity is not None:
            clauses.append("commodity = ?")
            params.append(commodity)
        if market is not None:
            clauses.append("market = ?")
            params.append(market)
        if obs_date is not None:
            clauses.append("obs_date = ?")
            params.append(self._date_param(obs_date))
        if driver is not None:
            clauses.append("driver = ?")
            params.append(driver)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY commodity, market, obs_date, driver, correction_id"
        cur = self._conn.execute(self._q(sql), params)
        return [Correction.model_validate(json.loads(r[0])) for r in cur.fetchall()]

    def insert_backfill_replay(self, replay: BackfillReplay) -> None:
        sql = self._q(
            "INSERT INTO backfill_replays (replay_id, commodity, market, "
            "payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                replay.replay_id,
                replay.commodity,
                replay.market,
                replay.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_backfill_replay(self, replay_id: str) -> BackfillReplay | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM backfill_replays WHERE replay_id = ?"
            ),
            (replay_id,),
        )
        row = cur.fetchone()
        return BackfillReplay.model_validate(json.loads(row[0])) if row else None

    def list_backfill_replays(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[BackfillReplay]:
        sql = "SELECT payload FROM backfill_replays"
        clauses, params = [], []
        if commodity is not None:
            clauses.append("commodity = ?")
            params.append(commodity)
        if market is not None:
            clauses.append("market = ?")
            params.append(market)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY commodity, market, replay_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            BackfillReplay.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    # -- forecast-ops analytics reports (R12) --------------------------
    # Insert-only payload table in the standing idiom: the
    # service checks the content address before inserting, so
    # re-building the same store state is a no-op rather than
    # a duplicate-write error.

    def insert_ops_report(self, report: OpsReport) -> None:
        sql = self._q(
            "INSERT INTO ops_reports (report_id, "
            "analytics_pack_version, payload) VALUES (?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                report.report_id,
                report.analytics_pack_version,
                report.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_ops_report(self, report_id: str) -> OpsReport | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM ops_reports WHERE report_id = ?"),
            (report_id,),
        )
        row = cur.fetchone()
        return OpsReport.model_validate(json.loads(row[0])) if row else None

    def list_ops_reports(self) -> list[OpsReport]:
        cur = self._conn.execute(
            self._q("SELECT payload FROM ops_reports ORDER BY report_id")
        )
        return [
            OpsReport.model_validate(json.loads(r[0])) for r in cur.fetchall()
        ]

    # -- operator console artefacts (R13) ------------------------------
    # Insert-only payload tables in the standing idiom: the
    # services check the content address before inserting, so
    # re-striking the same act or report is a no-op rather than
    # a duplicate-write error. Review and triage states are
    # folds of these acts, derived at read — never columns.

    def insert_forecast_rejection(self, rejection: ForecastRejection) -> None:
        sql = self._q(
            "INSERT INTO forecast_rejections (rejection_id, "
            "forecast_id, payload) VALUES (?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                rejection.rejection_id,
                rejection.forecast_id,
                rejection.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_forecast_rejection(
        self, forecast_id: str
    ) -> ForecastRejection | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM forecast_rejections "
                "WHERE forecast_id = ?"
            ),
            (forecast_id,),
        )
        row = cur.fetchone()
        return ForecastRejection.model_validate(json.loads(row[0])) if row else None

    def list_forecast_rejections(self) -> list[ForecastRejection]:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM forecast_rejections "
                "ORDER BY forecast_id"
            )
        )
        return [
            ForecastRejection.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_event_triage_act(self, act: EventTriageAct) -> None:
        sql = self._q(
            "INSERT INTO event_triage_acts (act_id, event_id, "
            "payload) VALUES (?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (act.act_id, act.event_id, act.model_dump_json()),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_event_triage_act(self, act_id: str) -> EventTriageAct | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM event_triage_acts WHERE act_id = ?"),
            (act_id,),
        )
        row = cur.fetchone()
        return EventTriageAct.model_validate(json.loads(row[0])) if row else None

    def list_event_triage_acts(
        self, event_id: str | None = None
    ) -> list[EventTriageAct]:
        sql = "SELECT payload FROM event_triage_acts"
        params: list = []
        if event_id is not None:
            sql += " WHERE event_id = ?"
            params.append(event_id)
        sql += " ORDER BY act_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            EventTriageAct.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_preflight_report(self, report: PreflightReport) -> None:
        sql = self._q(
            "INSERT INTO preflight_reports (report_id, commodity, "
            "market, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                report.report_id,
                report.commodity,
                report.market,
                report.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_preflight_report(self, report_id: str) -> PreflightReport | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM preflight_reports WHERE report_id = ?"
            ),
            (report_id,),
        )
        row = cur.fetchone()
        return PreflightReport.model_validate(json.loads(row[0])) if row else None

    def list_preflight_reports(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[PreflightReport]:
        sql = "SELECT payload FROM preflight_reports"
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
        sql += " ORDER BY commodity, market, report_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            PreflightReport.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    # -- geospatial basis & netting (R14) -----------------------------
    # Cost-line entries, basis readings, landed comparisons
    # and market maps are insert-only, like every other
    # artefact: the geo service checks the content address
    # before inserting, so a re-entry or re-strike is a no-op
    # rather than a duplicate-write error.

    def insert_cost_line_entry(self, entry: CostLineEntry) -> None:
        sql = self._q(
            "INSERT INTO cost_line_entries (entry_id, commodity, "
            "market, line, payload) VALUES (?, ?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                entry.entry_id,
                entry.commodity,
                entry.market,
                entry.line,
                entry.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_cost_line_entry(
        self, entry_id: str
    ) -> CostLineEntry | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM cost_line_entries "
                "WHERE entry_id = ?"
            ),
            (entry_id,),
        )
        row = cur.fetchone()
        return CostLineEntry.model_validate(json.loads(row[0])) if row else None

    def list_cost_line_entries(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[CostLineEntry]:
        sql = "SELECT payload FROM cost_line_entries"
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
        sql += " ORDER BY commodity, market, line, entry_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            CostLineEntry.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_basis_reading(self, reading: BasisReading) -> None:
        sql = self._q(
            "INSERT INTO basis_readings (reading_id, commodity, "
            "as_of, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                reading.reading_id,
                reading.commodity,
                self._date_param(reading.as_of),
                reading.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_basis_reading(
        self, reading_id: str
    ) -> BasisReading | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM basis_readings WHERE reading_id = ?"
            ),
            (reading_id,),
        )
        row = cur.fetchone()
        return BasisReading.model_validate(json.loads(row[0])) if row else None

    def list_basis_readings(
        self, commodity: str | None = None
    ) -> list[BasisReading]:
        sql = "SELECT payload FROM basis_readings"
        params: list = []
        if commodity is not None:
            sql += " WHERE commodity = ?"
            params.append(commodity)
        sql += " ORDER BY commodity, as_of, reading_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            BasisReading.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_landed_comparison(
        self, comparison: LandedComparison
    ) -> None:
        sql = self._q(
            "INSERT INTO landed_comparisons (comparison_id, "
            "commodity, as_of, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                comparison.comparison_id,
                comparison.commodity,
                self._date_param(comparison.as_of),
                comparison.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_landed_comparison(
        self, comparison_id: str
    ) -> LandedComparison | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM landed_comparisons "
                "WHERE comparison_id = ?"
            ),
            (comparison_id,),
        )
        row = cur.fetchone()
        return (
            LandedComparison.model_validate(json.loads(row[0])) if row else None
        )

    def list_landed_comparisons(
        self, commodity: str | None = None
    ) -> list[LandedComparison]:
        sql = "SELECT payload FROM landed_comparisons"
        params: list = []
        if commodity is not None:
            sql += " WHERE commodity = ?"
            params.append(commodity)
        sql += " ORDER BY commodity, as_of, comparison_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            LandedComparison.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_market_map(self, market_map: MarketMap) -> None:
        sql = self._q(
            "INSERT INTO market_maps (map_id, commodity, as_of, "
            "payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                market_map.map_id,
                market_map.commodity,
                self._date_param(market_map.as_of),
                market_map.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_market_map(self, map_id: str) -> MarketMap | None:
        cur = self._conn.execute(
            self._q("SELECT payload FROM market_maps WHERE map_id = ?"),
            (map_id,),
        )
        row = cur.fetchone()
        return MarketMap.model_validate(json.loads(row[0])) if row else None

    def list_market_maps(
        self, commodity: str | None = None
    ) -> list[MarketMap]:
        sql = "SELECT payload FROM market_maps"
        params: list = []
        if commodity is not None:
            sql += " WHERE commodity = ?"
            params.append(commodity)
        sql += " ORDER BY commodity, as_of, map_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            MarketMap.model_validate(json.loads(r[0])) for r in cur.fetchall()
        ]

    # Desk policy versions, decisions and their acts, the
    # decision log, comments and tasks are insert-only,
    # like every other artefact: the desk service checks
    # the content address before inserting, so a re-strike
    # is a no-op rather than a duplicate-write error. The
    # one moving part is a policy version's lifecycle
    # status — a separate column flipped only by the
    # service when a pack-change chain completes, synced
    # onto the artefact at read, the forecast precedent.

    def _policy_version_from_row(self, row) -> PolicyVersion:
        payload = json.loads(row[3])
        payload["status"] = row[2]
        return PolicyVersion.model_validate(payload)

    def insert_policy_version(self, version: PolicyVersion) -> None:
        sql = self._q(
            "INSERT INTO policy_versions (version_id, label, "
            "status, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                version.version_id,
                version.label,
                version.status,
                version.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_policy_version(
        self, version_id: str
    ) -> PolicyVersion | None:
        cur = self._conn.execute(
            self._q(
                "SELECT version_id, label, status, payload "
                "FROM policy_versions WHERE version_id = ?"
            ),
            (version_id,),
        )
        row = cur.fetchone()
        return self._policy_version_from_row(row) if row else None

    def list_policy_versions(self) -> list[PolicyVersion]:
        cur = self._conn.execute(
            self._q(
                "SELECT version_id, label, status, payload "
                "FROM policy_versions ORDER BY label, version_id"
            )
        )
        return [self._policy_version_from_row(r) for r in cur.fetchall()]

    def set_policy_version_status(
        self, version_id: str, status: str
    ) -> None:
        self._conn.execute(
            self._q(
                "UPDATE policy_versions SET status = ? "
                "WHERE version_id = ?"
            ),
            (status, version_id),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def insert_decision(self, decision: DecisionCase) -> None:
        sql = self._q(
            "INSERT INTO decisions (decision_id, kind, "
            "target_id, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                decision.decision_id,
                decision.kind,
                decision.target_id,
                decision.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_decision(self, decision_id: str) -> DecisionCase | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM decisions WHERE decision_id = ?"
            ),
            (decision_id,),
        )
        row = cur.fetchone()
        return DecisionCase.model_validate(json.loads(row[0])) if row else None

    def list_decisions(
        self, kind: str | None = None, target_id: str | None = None
    ) -> list[DecisionCase]:
        sql = "SELECT payload FROM decisions"
        params: list = []
        clauses = []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if target_id is not None:
            clauses.append("target_id = ?")
            params.append(target_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY kind, target_id, decision_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            DecisionCase.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_decision_act(self, act: DecisionAct) -> None:
        sql = self._q(
            "INSERT INTO decision_acts (act_id, decision_id, "
            "decided_on, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                act.act_id,
                act.decision_id,
                self._date_param(act.decided_on),
                act.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_decision_act(self, act_id: str) -> DecisionAct | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM decision_acts WHERE act_id = ?"
            ),
            (act_id,),
        )
        row = cur.fetchone()
        return DecisionAct.model_validate(json.loads(row[0])) if row else None

    def list_decision_acts(
        self, decision_id: str | None = None
    ) -> list[DecisionAct]:
        sql = "SELECT payload FROM decision_acts"
        params: list = []
        if decision_id is not None:
            sql += " WHERE decision_id = ?"
            params.append(decision_id)
        sql += " ORDER BY decided_on, act_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            DecisionAct.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_decision_log(self, log: DecisionLog) -> None:
        sql = self._q(
            "INSERT INTO decision_logs (log_id, struck_on, "
            "payload) VALUES (?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                log.log_id,
                self._date_param(log.struck_on),
                log.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_decision_log(self, log_id: str) -> DecisionLog | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM decision_logs WHERE log_id = ?"
            ),
            (log_id,),
        )
        row = cur.fetchone()
        return DecisionLog.model_validate(json.loads(row[0])) if row else None

    def list_decision_logs(self) -> list[DecisionLog]:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM decision_logs "
                "ORDER BY struck_on, log_id"
            )
        )
        return [
            DecisionLog.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_comment(self, comment: ArtefactComment) -> None:
        sql = self._q(
            "INSERT INTO artefact_comments (comment_id, "
            "target_kind, target_id, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                comment.comment_id,
                comment.target_kind,
                comment.target_id,
                comment.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_comment(self, comment_id: str) -> ArtefactComment | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM artefact_comments "
                "WHERE comment_id = ?"
            ),
            (comment_id,),
        )
        row = cur.fetchone()
        return (
            ArtefactComment.model_validate(json.loads(row[0]))
            if row
            else None
        )

    def list_comments(
        self, target_kind: str | None = None,
        target_id: str | None = None,
    ) -> list[ArtefactComment]:
        sql = "SELECT payload FROM artefact_comments"
        params: list = []
        clauses = []
        if target_kind is not None:
            clauses.append("target_kind = ?")
            params.append(target_kind)
        if target_id is not None:
            clauses.append("target_id = ?")
            params.append(target_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY target_kind, target_id, comment_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            ArtefactComment.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_task(self, task: FollowUpTask) -> None:
        sql = self._q(
            "INSERT INTO follow_up_tasks (task_id, target_kind, "
            "target_id, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                task.task_id,
                task.target_kind,
                task.target_id,
                task.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_task(self, task_id: str) -> FollowUpTask | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM follow_up_tasks WHERE task_id = ?"
            ),
            (task_id,),
        )
        row = cur.fetchone()
        return FollowUpTask.model_validate(json.loads(row[0])) if row else None

    def list_tasks(
        self, target_kind: str | None = None,
        target_id: str | None = None,
    ) -> list[FollowUpTask]:
        sql = "SELECT payload FROM follow_up_tasks"
        params: list = []
        clauses = []
        if target_kind is not None:
            clauses.append("target_kind = ?")
            params.append(target_kind)
        if target_id is not None:
            clauses.append("target_id = ?")
            params.append(target_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY target_kind, target_id, task_id"
        cur = self._conn.execute(self._q(sql), params)
        return [
            FollowUpTask.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_task_act(self, act: TaskAct) -> None:
        sql = self._q(
            "INSERT INTO task_acts (act_id, task_id, acted_on, "
            "payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                act.act_id,
                act.task_id,
                self._date_param(act.acted_on),
                act.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_task_act(self, act_id: str) -> TaskAct | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM task_acts WHERE act_id = ?"
            ),
            (act_id,),
        )
        row = cur.fetchone()
        return TaskAct.model_validate(json.loads(row[0])) if row else None

    def list_task_acts(self, task_id: str) -> list[TaskAct]:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM task_acts WHERE task_id = ? "
                "ORDER BY acted_on, act_id"
            ),
            (task_id,),
        )
        return [
            TaskAct.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    # -- access grants, read entries, audit logs (R16) --

    def insert_principal_grant(self, grant: PrincipalGrant) -> None:
        sql = self._q(
            "INSERT INTO principal_grants (grant_id, subject, "
            "seq, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                grant.grant_id,
                grant.subject,
                grant.seq,
                grant.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_principal_grant(self, grant_id: str) -> PrincipalGrant | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM principal_grants "
                "WHERE grant_id = ?"
            ),
            (grant_id,),
        )
        row = cur.fetchone()
        return PrincipalGrant.model_validate(json.loads(row[0])) if row else None

    def list_principal_grants(self) -> list[PrincipalGrant]:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM principal_grants ORDER BY seq"
            )
        )
        return [
            PrincipalGrant.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_access_entry(self, entry: AccessEntry) -> None:
        sql = self._q(
            "INSERT INTO access_entries (entry_id, seq, payload) "
            "VALUES (?, ?, ?)"
        )
        self._conn.execute(
            sql, (entry.entry_id, entry.seq, entry.model_dump_json())
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_access_entry(self, entry_id: str) -> AccessEntry | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM access_entries WHERE entry_id = ?"
            ),
            (entry_id,),
        )
        row = cur.fetchone()
        return AccessEntry.model_validate(json.loads(row[0])) if row else None

    def list_access_entries(self) -> list[AccessEntry]:
        cur = self._conn.execute(
            self._q("SELECT payload FROM access_entries ORDER BY seq")
        )
        return [
            AccessEntry.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def insert_access_log(self, log: AccessLog) -> None:
        sql = self._q(
            "INSERT INTO access_logs (log_id, struck_on, payload) "
            "VALUES (?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (log.log_id, log.struck_on.isoformat(), log.model_dump_json()),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_access_log(self, log_id: str) -> AccessLog | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM access_logs WHERE log_id = ?"
            ),
            (log_id,),
        )
        row = cur.fetchone()
        return AccessLog.model_validate(json.loads(row[0])) if row else None

    def list_access_logs(self) -> list[AccessLog]:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM access_logs "
                "ORDER BY struck_on, log_id"
            )
        )
        return [
            AccessLog.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    # -- master data versions (R16) --

    def insert_master_data_version(
        self, version: MasterDataVersion
    ) -> None:
        sql = self._q(
            "INSERT INTO master_data_versions (version_id, label, "
            "seq, payload) VALUES (?, ?, ?, ?)"
        )
        self._conn.execute(
            sql,
            (
                version.version_id,
                version.label,
                version.seq,
                version.model_dump_json(),
            ),
        )
        if self.dialect == "sqlite":
            self._conn.commit()

    def get_master_data_version(
        self, version_id: str
    ) -> MasterDataVersion | None:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM master_data_versions "
                "WHERE version_id = ?"
            ),
            (version_id,),
        )
        row = cur.fetchone()
        return (
            MasterDataVersion.model_validate(json.loads(row[0]))
            if row
            else None
        )

    def list_master_data_versions(self) -> list[MasterDataVersion]:
        cur = self._conn.execute(
            self._q(
                "SELECT payload FROM master_data_versions ORDER BY seq"
            )
        )
        return [
            MasterDataVersion.model_validate(json.loads(r[0]))
            for r in cur.fetchall()
        ]

    def close(self) -> None:
        self._conn.close()


def build_store(sqlite_path: str | None = None, database_url: str | None = None) -> SqlStore:
    store = SqlStore(sqlite_path=sqlite_path, database_url=database_url)
    store.migrate()
    return store
