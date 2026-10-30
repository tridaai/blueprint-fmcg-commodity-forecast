"""The operations API: read surfaces over the store port.

Round 1 ships reads only — series, the event registry, the manifest,
coverage — plus /health and /readiness. Round 2 adds the forecast
surface: run a forecast, read its contribution breakdown, take the
approval act that makes it the desk's official view, and draft
figure-verified commentary. Round 3 adds the accuracy surface
(Law 2): run the backtest harness, read its results, read the
accuracy ledger, and read any forecast's pinned accuracy snapshot —
the degraded flag rides on every forecast read; there is no
parameter that takes it off. Round 4 adds the sentiment surface
(Law 3): the corpus items, their extractions, the weekly index per
commodity and week, the pipeline run, a re-performance read, and
any forecast's sentiment line. Round 5 adds the governed event
registry (Law 4): declare an event (a named analyst act), seed the
planted historical shocks from the manifest, read any event with
its transmission verdict on its face, read the what-happened
impact view, and read any forecast's per-event lines — the desk's
forecasts now run with the registry wired in, so a declared event
whose window touches a run lands as its own named line. Round 7
adds the dashboard surface (Law 6): a plain-language prompt
becomes a stated dashboard spec (catalogue panels or named gap
panels), specs save as named views and assemble into verified
static pages whose every figure carries its lineage to stored
facts in a provenance appendix, plus the morning desk board —
the exception inbox derived from artefacts only. Round 8 adds
the buy-window signals (a computed buy_now / phased / wait call
per series under a versioned signal pack, reasoning on its face,
degraded series capped by rule) and the coverage & exposure
planner (the desk's own requirement plans — desk-entered
artefacts with a lineage class of their own — priced against
pinned forecasts or adopted scenario forks, with ranked
purchase options). Every
response carries the request id the logging middleware assigned,
so a figure on a desk screen can be traced to the exact stored
rows behind it.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from fmcg_forecast.analytics.engine import AnalyticsError
from fmcg_forecast.analytics.pack import load_analytics_pack
from fmcg_forecast.analytics.service import (
    AnalyticsNotFoundError,
    AnalyticsService,
)
from fmcg_forecast.alerts.pack import load_alert_pack
from fmcg_forecast.alerts.service import (
    AlertNotFoundError,
    AlertService,
    AlertStateError,
    AlertValidationError,
)
from fmcg_forecast.backtest.harness import run_all as run_backtest_harness
from fmcg_forecast.backtest.pack import load_accuracy_pack
from fmcg_forecast.catalogue import COMMODITIES
from fmcg_forecast.console.engine import (
    ConsoleNotFoundError,
    ConsoleStateError,
    ConsoleValidationError,
)
from fmcg_forecast.console.pack import load_console_pack
from fmcg_forecast.console.render import render_console, render_console_phone
from fmcg_forecast.console.service import ConsoleService
from fmcg_forecast.dashboards.pack import load_dashboard_pack
from fmcg_forecast.dashboards.service import (
    DashboardNotFoundError,
    DashboardParseError,
    DashboardService,
    DashboardValidationError,
    DashboardVerificationError,
)
from fmcg_forecast.events.service import (
    EventNotFoundError,
    EventService,
    EventValidationError,
)
from fmcg_forecast.forecast.engine import (
    ForecastError,
    InsufficientHistoryError,
    SealedWindowRefusal,
    UnknownSeriesError,
)
from fmcg_forecast.forecast.service import (
    ApprovalStateError,
    ApprovalValidationError,
    CommentaryVerificationError,
    ForecastNotFoundError,
    ForecastService,
)
from fmcg_forecast.logging_config import new_request_id, request_id_var
from fmcg_forecast.modelport import (
    ModelNotConfiguredError,
    ModelPort,
    OfflineModel,
)
from fmcg_forecast.planning.models import PlanLine
from fmcg_forecast.planning.pack import load_planning_pack
from fmcg_forecast.planning.service import (
    PlanningError,
    PlanningNotFoundError,
    PlanningService,
    PlanningStateError,
    PlanningValidationError,
)
from fmcg_forecast.scenarios.models import LeverApplication
from fmcg_forecast.scenarios.pack import load_scenario_pack
from fmcg_forecast.scenarios.service import (
    AdoptionStateError,
    AdoptionValidationError,
    ScenarioNotFoundError,
    ScenarioParseError,
    ScenarioService,
    ScenarioValidationError,
)
from fmcg_forecast.sentiment.service import (
    SentimentConflictError,
    SentimentService,
)
from fmcg_forecast.ingest.pack import load_ingest_pack
from fmcg_forecast.ingest.service import (
    IngestNotFoundError,
    IngestService,
    IngestValidationError,
)
from fmcg_forecast.intake.service import (
    IntakeNotFoundError,
    IntakeService,
    IntakeStateError,
    IntakeValidationError,
)
from fmcg_forecast.signals.pack import load_signal_pack
from fmcg_forecast.signals.service import (
    SignalError,
    SignalNotFoundError,
    SignalService,
)
from fmcg_forecast.store import SqlStore
from fmcg_forecast.thin.engine import ThinDataError
from fmcg_forecast.thin.pack import load_thin_data_pack
from fmcg_forecast.thin.service import ThinDataNotFoundError, ThinDataService

log = logging.getLogger("fmcg.api")


class RunForecastRequest(BaseModel):
    commodity: str
    market: str
    as_of: date | None = None
    via_backtest: bool = False
    preflight_id: str | None = None


class ApproveRequest(BaseModel):
    approver: str
    role: str
    decided_on: date | None = None


class BacktestRunRequest(BaseModel):
    pack_version: str | None = None


class RegisterEventRequest(BaseModel):
    event_class: str
    commodity: str
    window_start: date
    window_end: date | None = None
    channel: str
    driver_effect: float | None = None
    peak_log_price_effect: float
    basis: str
    basis_detail: str
    decay_days: int
    description: str
    declared_by: str
    declared_on: date | None = None


class ParseScenarioRequest(BaseModel):
    commodity: str
    market: str
    text: str
    base_forecast_id: str | None = None


class CreateScenarioRequest(BaseModel):
    commodity: str
    market: str
    levers: list[LeverApplication]


class RunScenarioRequest(BaseModel):
    request_id: str
    base_forecast_id: str
    author: str
    created_on: date | None = None


class AdoptScenarioRequest(BaseModel):
    adopter: str
    role: str
    decided_on: date | None = None


class AskDashboardRequest(BaseModel):
    prompt: str
    asked_by: str
    created_on: date | None = None


class SaveViewRequest(BaseModel):
    name: str
    saved_by: str
    saved_on: date | None = None


class AssembleDashboardRequest(BaseModel):
    assembled_on: date | None = None


class ComputeSignalRequest(BaseModel):
    commodity: str
    market: str


class EnterPlanRequest(BaseModel):
    commodity: str
    market: str
    entered_by: str
    entered_on: date | None = None
    opening_stock_tonnes: float = 0.0
    lines: list[PlanLine]
    note: str = ""


class AssessPlanRequest(BaseModel):
    basis: str = "official_forecast"


class SubscribeRequest(BaseModel):
    subscriber: str
    role: str
    entered_on: date | None = None
    commodities: list[str] = []
    markets: list[str] = []
    kinds: list[str]
    min_severity: str = "minor"
    note: str = ""


class SweepRequest(BaseModel):
    at: datetime


class AlertActRequest(BaseModel):
    actor: str
    role: str
    at: datetime
    note: str = ""


class CloseAlertRequest(AlertActRequest):
    reason: str


class DigestRequest(BaseModel):
    subscription_id: str
    digest_date: date


class AssessForecastRequest(BaseModel):
    forecast_id: str


class TierClaimRequest(BaseModel):
    forecast_id: str
    horizon_days: int
    claimed_tier: str


class EnterIntakeRequest(BaseModel):
    commodity: str
    market: str
    obs_date: date
    driver: str
    value: float
    entered_by: str
    entered_by_role: str
    entered_at: datetime | None = None
    source_note: str


class IntakeCheckRequest(BaseModel):
    checker: str
    checker_role: str
    at: datetime | None = None
    note: str = ""


class RegisterSourceRequest(BaseModel):
    source_id: str
    kind: str
    display: str
    owner: str
    cadence: str
    drivers: list[str]
    licence_note: str
    registered_by: str
    registered_by_role: str
    at: datetime | None = None


class LoadFileRequest(BaseModel):
    source_id: str
    csv_text: str
    as_of: date | None = None
    kind: str = "file_drop"
    received_by: str
    at: datetime | None = None


class LoadPushRequest(BaseModel):
    source_id: str
    rows: list[dict]
    as_of: date | None = None
    received_by: str
    at: datetime | None = None


class CorrectRequest(BaseModel):
    commodity: str
    market: str
    obs_date: date
    driver: str
    value: float
    reason: str
    corrected_by: str
    corrected_by_role: str
    at: datetime | None = None
    corrects_quarantine_id: str | None = None


class ReplayRequest(BaseModel):
    commodity: str
    market: str
    origins: list[date]
    replayed_by: str
    at: datetime | None = None


class RejectForecastRequest(BaseModel):
    rejected_by: str
    role: str
    decided_on: date | None = None
    reason: str
    note: str = ""


class StrikePreflightRequest(BaseModel):
    commodity: str
    market: str
    as_of: date | None = None


class TriageActRequest(BaseModel):
    actor: str
    role: str
    acted_on: date | None = None
    note: str = ""


class AmendEventRequest(BaseModel):
    actor: str
    role: str
    acted_on: date | None = None
    note: str = ""
    replacement: RegisterEventRequest


class ConsoleActionRequest(BaseModel):
    kind: str
    forecast_id: str | None = None
    event_id: str | None = None
    alert_id: str | None = None
    approver: str | None = None
    rejected_by: str | None = None
    actor: str | None = None
    role: str | None = None
    decided_on: date | None = None
    acted_on: date | None = None
    acted_at: datetime | None = None
    reason: str | None = None
    note: str = ""
    replacement: RegisterEventRequest | None = None


def create_app(store: SqlStore, model: ModelPort | None = None) -> FastAPI:
    model_port = model or OfflineModel()
    sentiment = SentimentService(store, model_port)
    event_service = EventService(store)
    console_service = ConsoleService(store, event_service)
    service = ForecastService(
        store,
        model_port,
        sentiment_provider=sentiment.forecast_input,
        sentiment_claim_verifier=sentiment.verify_claims,
        events_provider=event_service.forecast_adjustments,
        approval_guard=console_service.approval_blockers,
    )
    event_service.triage_exclusions = console_service.excluded_event_ids
    scenario_service = ScenarioService(
        store,
        model_port,
        service,
        event_service,
        sentiment_provider=sentiment.forecast_input,
    )
    dashboard_service = DashboardService(
        store, model_port, event_service, sentiment
    )
    signal_service = SignalService(store)
    planning_service = PlanningService(store, signal_service)
    alert_service = AlertService(store)
    thin_service = ThinDataService(store)
    intake_service = IntakeService(store)
    ingest_service = IngestService(store)
    analytics_service = AnalyticsService(store)
    app = FastAPI(
        title="FMCG Commodity Forecast — Operations API",
        version="0.13.0",
        description="Read surfaces for the commodity price & driver store, "
        "the governed forecast surface, the backtest/accuracy surface, "
        "the sentiment surface, the event registry, the scenario "
        "studio, the dashboard assembler with the morning desk "
        "board, the buy-window signals, the coverage & "
        "exposure planner, the alerting surface: desk-entered "
        "subscriptions, derived alerts, attributed acts and the "
        "escalation clock, the thin-data surface: multi-window "
        "assessments and per-horizon confidence tiers, and the "
        "assisted intake surface: phoned-in figures under "
        "maker–checker, and the production data plane: the "
        "source registry, connector loads with quarantine and "
        "provenance, correction overlays, and backfill replay, "
        "and the forecast-ops analytics surface: accuracy "
        "trends, signal outcomes, transmission error by event "
        "class and shock-window grades, computed from the "
        "artefacts of record, and the operator console: the "
        "forecast review queue with rejection acts, the event "
        "triage queue gating the official view, coverage "
        "pre-flights a run can pin, and the desktop and "
        "phone-first console pages whose actions strike the "
        "same acts.",
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = request.headers.get("x-request-id") or new_request_id()
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/readiness")
    def readiness() -> JSONResponse:
        manifest = store.get_manifest()
        if manifest is None:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "reason": "dataset not loaded"},
            )
        counts = store.row_counts()
        return JSONResponse(
            content={
                "status": "ready",
                "seed": manifest.seed,
                "history_rows": sum(counts.values()),
                "digest": manifest.history_digest,
            }
        )

    @app.get("/catalogue")
    def catalogue() -> dict:
        return {
            "commodities": [
                {
                    "commodity": c.commodity,
                    "display": c.display,
                    "markets": [m.market for m in c.markets],
                    "drivers": list(c.drivers),
                    "reporting": c.reporting,
                }
                for c in COMMODITIES
            ]
        }

    @app.get("/series")
    def series(
        commodity: str = Query(...),
        market: str = Query(...),
        driver: str = Query(...),
        start: date | None = Query(None),
        end: date | None = Query(None),
    ) -> dict:
        rows = store.series(commodity, market, driver, start, end)
        if not rows:
            raise HTTPException(
                status_code=404,
                detail=f"no observations for {commodity}/{market}/{driver} in range",
            )
        return {
            "commodity": commodity,
            "market": market,
            "driver": driver,
            "unit": rows[0].unit,
            "points": [
                {"date": r.obs_date.isoformat(), "value": r.value} for r in rows
            ],
        }

    @app.get("/events")
    def events(commodity: str | None = Query(None)) -> dict:
        found = store.list_events(commodity)
        return {"events": [e.model_dump(mode="json") for e in found]}

    @app.get("/events/{event_id}")
    def event(event_id: str) -> dict:
        found = store.get_event(event_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"unknown event {event_id}")
        return found.model_dump(mode="json")

    @app.get("/manifest")
    def manifest() -> dict:
        found = store.get_manifest()
        if found is None:
            raise HTTPException(status_code=404, detail="dataset not loaded")
        return found.model_dump(mode="json")

    @app.get("/coverage/{commodity}")
    def coverage(commodity: str) -> dict:
        found = store.get_manifest()
        if found is None:
            raise HTTPException(status_code=404, detail="dataset not loaded")
        for entry in found.commodities:
            if entry.commodity == commodity:
                return entry.model_dump(mode="json")
        raise HTTPException(status_code=404, detail=f"unknown commodity {commodity}")

    # -- forecasts (R2) -------------------------------------------------

    @app.post("/forecasts/run")
    def run_forecast(body: RunForecastRequest) -> dict:
        try:
            forecast = service.run_forecast(
                body.commodity,
                body.market,
                body.as_of,
                via_backtest=body.via_backtest,
                preflight_id=body.preflight_id,
            )
        except SealedWindowRefusal as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except UnknownSeriesError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InsufficientHistoryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ForecastError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return forecast.model_dump(mode="json")

    @app.get("/forecasts")
    def list_forecasts(
        commodity: str | None = Query(None), market: str | None = Query(None)
    ) -> dict:
        found = service.list_forecasts(commodity, market)
        return {
            "forecasts": [
                {
                    "forecast_id": f.forecast_id,
                    "commodity": f.commodity,
                    "market": f.market,
                    "as_of": f.as_of.isoformat(),
                    "status": f.status,
                    "engine_version": f.engine_version,
                }
                for f in found
            ]
        }

    @app.get("/forecasts/{forecast_id}")
    def get_forecast(forecast_id: str) -> dict:
        try:
            view = service.get_forecast(forecast_id).model_dump(mode="json")
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        # The forecast view carries its thin-data assessment
        # (R10): the earned tier per horizon and every named
        # gap ride on the read, never as an optional extra a
        # caller can leave off.
        try:
            view["thin_data"] = thin_service.forecast_view(forecast_id)
        except (ThinDataError, ValueError) as exc:
            view["thin_data"] = None
            view["thin_data_problems"] = [str(exc)]
        return view

    @app.get("/forecasts/{forecast_id}/contributions")
    def get_contributions(forecast_id: str) -> dict:
        try:
            return service.contributions(forecast_id)
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/forecasts/{forecast_id}/verify")
    def verify_forecast_endpoint(forecast_id: str) -> dict:
        try:
            problems = service.verify_stored(forecast_id)
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"forecast_id": forecast_id, "problems": problems}

    @app.post("/forecasts/{forecast_id}/approve")
    def approve(forecast_id: str, body: ApproveRequest) -> dict:
        try:
            approval = service.approve(
                forecast_id,
                body.approver,
                body.role,
                body.decided_on or date.today(),
            )
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ApprovalValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ApprovalStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return approval.model_dump(mode="json")

    @app.get("/forecasts/{forecast_id}/approval")
    def get_approval(forecast_id: str) -> dict:
        try:
            approval = service.get_approval(forecast_id)
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if approval is None:
            raise HTTPException(
                status_code=404, detail=f"forecast {forecast_id} has no approval act"
            )
        return approval.model_dump(mode="json")

    @app.post("/forecasts/{forecast_id}/reject")
    def reject_forecast(forecast_id: str, body: RejectForecastRequest) -> dict:
        try:
            act = console_service.reject_forecast(
                forecast_id,
                body.rejected_by,
                body.role,
                body.decided_on or date.today(),
                body.reason,
                body.note,
            )
        except ConsoleNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConsoleValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ConsoleStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return act.model_dump(mode="json")

    @app.get("/forecasts/{forecast_id}/rejection")
    def get_rejection(forecast_id: str) -> dict:
        try:
            return console_service.rejection_view(forecast_id)
        except ConsoleNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/forecasts/{forecast_id}/commentary")
    def draft_commentary(forecast_id: str) -> dict:
        try:
            commentary = service.draft_commentary(forecast_id)
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except CommentaryVerificationError as exc:
            raise HTTPException(
                status_code=422,
                detail={"message": str(exc), "problems": exc.problems},
            ) from exc
        return commentary.model_dump(mode="json")

    @app.get("/forecasts/{forecast_id}/commentary")
    def get_commentary(forecast_id: str) -> dict:
        try:
            commentary = service.get_commentary(forecast_id)
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if commentary is None:
            raise HTTPException(
                status_code=404, detail=f"forecast {forecast_id} has no commentary"
            )
        return commentary.model_dump(mode="json")

    @app.get("/forecasts/{forecast_id}/accuracy")
    def get_forecast_accuracy(forecast_id: str) -> dict:
        try:
            return service.accuracy_view(forecast_id)
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/forecasts/{forecast_id}/sentiment")
    def get_forecast_sentiment(forecast_id: str) -> dict:
        try:
            return service.sentiment_view(forecast_id)
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/forecasts/{forecast_id}/events")
    def get_forecast_events(forecast_id: str) -> dict:
        try:
            view = service.events_view(forecast_id)
            forecast = service.get_forecast(forecast_id)
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        # R13: every applied event is labelled with its triage
        # state and transmission verdict, and the blockers that
        # would refuse this draft's approval ride on the read —
        # an unconfirmed event's full amount is in the draft,
        # labelled as such, and contributes zero to any official
        # view until triage clears it.
        from fmcg_forecast.console.engine import applied_event_flags

        flags = {
            flag.event_id: flag
            for flag in applied_event_flags(store, event_service, forecast)
        }
        for entry in view["events"]:
            flag = flags.get(entry["event_id"])
            entry["verification_status"] = (
                flag.verification_status if flag else "not_in_registry"
            )
            entry["triage_state"] = (
                flag.triage_state if flag else "not_in_registry"
            )
        view["official_blockers"] = console_service.approval_blockers(forecast)
        return view

    # -- the governed event registry (R5, Law 4) -----------------------

    @app.post("/market-events", status_code=201)
    def register_market_event(body: RegisterEventRequest) -> dict:
        try:
            event = event_service.register_event(
                event_class=body.event_class,
                commodity=body.commodity,
                window_start=body.window_start,
                window_end=body.window_end,
                channel=body.channel,
                driver_effect=body.driver_effect,
                peak_log_price_effect=body.peak_log_price_effect,
                basis=body.basis,
                basis_detail=body.basis_detail,
                decay_days=body.decay_days,
                description=body.description,
                declared_by=body.declared_by,
                declared_on=body.declared_on or date.today(),
            )
        except EventValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return event_service.event_view(event.event_id)

    @app.post("/market-events/seed-historical")
    def seed_historical_events() -> dict:
        found = store.get_manifest()
        if found is None:
            raise HTTPException(status_code=404, detail="dataset not loaded")
        return event_service.seed_historical(found)

    @app.get("/market-events/verify")
    def verify_market_events() -> dict:
        return event_service.verify_registry()

    @app.get("/market-events")
    def list_market_events(commodity: str | None = Query(None)) -> dict:
        found = event_service.list_events(commodity)
        return {"events": [event_service.event_view(e.event_id) for e in found]}

    @app.get("/market-events/{event_id}")
    def get_market_event(event_id: str) -> dict:
        try:
            return event_service.event_view(event_id)
        except EventNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/market-events/{event_id}/verify")
    def verify_market_event(event_id: str) -> dict:
        try:
            return event_service.verify_event(event_id).model_dump(mode="json")
        except EventNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/market-events/{event_id}/impact")
    def get_market_event_impact(
        event_id: str, market: str | None = Query(None)
    ) -> dict:
        try:
            return event_service.impact(event_id, market).model_dump(mode="json")
        except EventNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except EventValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # -- the scenario studio (R6, Law 5) -------------------------------

    @app.get("/scenarios/pack")
    def scenario_pack() -> dict:
        return load_scenario_pack().model_dump(mode="json")

    @app.post("/scenarios/requests", status_code=201)
    def parse_scenario_request(body: ParseScenarioRequest) -> dict:
        try:
            request = scenario_service.parse_request(
                body.commodity, body.market, body.text, body.base_forecast_id
            )
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ScenarioParseError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": str(exc),
                    "clause": exc.clause,
                    "reason": exc.reason,
                },
            ) from exc
        except ScenarioValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return request.model_dump(mode="json")

    @app.post("/scenarios/requests/structured", status_code=201)
    def create_scenario_request(body: CreateScenarioRequest) -> dict:
        try:
            request = scenario_service.create_request(
                body.commodity, body.market, body.levers
            )
        except ScenarioValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return request.model_dump(mode="json")

    @app.get("/scenarios/requests")
    def list_scenario_requests(
        commodity: str | None = Query(None), market: str | None = Query(None)
    ) -> dict:
        found = scenario_service.list_requests(commodity, market)
        return {"requests": [r.model_dump(mode="json") for r in found]}

    @app.get("/scenarios/requests/{request_id}")
    def get_scenario_request(request_id: str) -> dict:
        try:
            return scenario_service.get_request(request_id).model_dump(mode="json")
        except ScenarioNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/scenarios", status_code=201)
    def run_scenario(body: RunScenarioRequest) -> dict:
        try:
            run = scenario_service.run_scenario(
                body.request_id,
                body.base_forecast_id,
                body.author,
                body.created_on or date.today(),
            )
        except ScenarioNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ScenarioValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return scenario_service.scenario_view(run.scenario_id)

    @app.get("/scenarios")
    def list_scenarios(
        commodity: str | None = Query(None), market: str | None = Query(None)
    ) -> dict:
        found = scenario_service.list_scenarios(commodity, market)
        return {
            "scenarios": [
                {
                    "scenario_id": s.scenario_id,
                    "request_id": s.request_id,
                    "base_forecast_id": s.base_forecast_id,
                    "fork_forecast_id": s.fork_forecast_id,
                    "commodity": s.commodity,
                    "market": s.market,
                    "as_of": s.as_of.isoformat(),
                    "author": s.author,
                    "status": s.status,
                    "view_kind": ScenarioService._VIEW_KINDS[s.status],
                }
                for s in found
            ]
        }

    @app.get("/scenarios/adopted/{commodity}/{market}")
    def get_adopted_view(commodity: str, market: str) -> dict:
        return scenario_service.adopted_view(commodity, market)

    @app.get("/scenarios/{scenario_id}")
    def get_scenario(scenario_id: str) -> dict:
        try:
            return scenario_service.scenario_view(scenario_id)
        except ScenarioNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/scenarios/{scenario_id}/diff")
    def get_scenario_diff(scenario_id: str) -> dict:
        try:
            return scenario_service.diff(scenario_id).model_dump(mode="json")
        except ScenarioNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ScenarioValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/scenarios/{scenario_id}/verify")
    def verify_scenario_endpoint(scenario_id: str) -> dict:
        try:
            problems = scenario_service.verify_stored(scenario_id)
        except ScenarioNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"scenario_id": scenario_id, "problems": problems}

    @app.post("/scenarios/{scenario_id}/adopt")
    def adopt_scenario(scenario_id: str, body: AdoptScenarioRequest) -> dict:
        try:
            adoption = scenario_service.adopt(
                scenario_id,
                body.adopter,
                body.role,
                body.decided_on or date.today(),
            )
        except ScenarioNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AdoptionValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AdoptionStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return adoption.model_dump(mode="json")

    @app.get("/scenarios/{scenario_id}/adoption")
    def get_scenario_adoption(scenario_id: str) -> dict:
        try:
            adoption = scenario_service.get_adoption(scenario_id)
        except ScenarioNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if adoption is None:
            raise HTTPException(
                status_code=404,
                detail=f"scenario {scenario_id} has no adoption act",
            )
        return adoption.model_dump(mode="json")

    # -- sentiment (R4, Law 3) ------------------------------------------

    @app.post("/sentiment/run")
    def run_sentiment() -> dict:
        try:
            return sentiment.run_pipeline()
        except SentimentConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/sentiment/manifest")
    def sentiment_manifest() -> dict:
        found = store.get_sentiment_manifest()
        if found is None:
            raise HTTPException(status_code=404, detail="sentiment corpus not loaded")
        return found.model_dump(mode="json")

    @app.get("/sentiment/items")
    def sentiment_items(commodity: str | None = Query(None)) -> dict:
        found = sentiment.list_items(commodity)
        return {"items": [i.model_dump(mode="json") for i in found]}

    @app.get("/sentiment/items/{item_id}")
    def sentiment_item(item_id: str) -> dict:
        found = sentiment.get_item(item_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"unknown item {item_id}")
        extraction = sentiment.get_extraction(item_id)
        return {
            "item": found.model_dump(mode="json"),
            "extraction": (
                extraction.model_dump(mode="json") if extraction is not None else None
            ),
        }

    @app.get("/sentiment/extractions")
    def sentiment_extractions(commodity: str | None = Query(None)) -> dict:
        found = sentiment.list_extractions(commodity)
        return {"extractions": [e.model_dump(mode="json") for e in found]}

    @app.get("/sentiment/index/{commodity}")
    def sentiment_index_list(commodity: str) -> dict:
        found = sentiment.list_indices(commodity)
        return {"indices": [i.model_dump(mode="json") for i in found]}

    @app.get("/sentiment/index/{commodity}/{week_start}")
    def sentiment_index_one(commodity: str, week_start: date) -> dict:
        found = sentiment.get_index(commodity, week_start)
        if found is None:
            raise HTTPException(
                status_code=404,
                detail=f"no sentiment index for {commodity} in the week "
                f"of {week_start.isoformat()} — the index is absent there, "
                "never zero-filled",
            )
        return found.model_dump(mode="json")

    @app.get("/sentiment/verify")
    def sentiment_verify() -> dict:
        return sentiment.verify_stored()

    # -- backtests + the accuracy ledger (R3) ---------------------------

    @app.post("/backtests/run")
    def run_backtests(body: BacktestRunRequest | None = None) -> dict:
        try:
            pack = load_accuracy_pack(body.pack_version if body else None)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            report, records = run_backtest_harness(store, pack)
        except ForecastError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "pack_version": pack.version,
            "results_stored": report.results_stored,
            "results_already_on_record": report.results_already_on_record,
            "engine_runs": report.engine_runs,
            "skipped": report.skipped,
            "ledger_records": len(records),
            "degraded_records": [
                {
                    "commodity": r.commodity,
                    "market": r.market,
                    "horizon_days": r.horizon_days,
                    "mape": r.mape,
                }
                for r in records
                if r.degraded
            ],
        }

    @app.get("/backtests")
    def list_backtests(
        commodity: str | None = Query(None),
        market: str | None = Query(None),
        horizon_days: int | None = Query(None),
    ) -> dict:
        found = store.list_backtest_results(commodity, market, horizon_days)
        return {
            "results": [
                {
                    "result_id": r.result_id,
                    "commodity": r.commodity,
                    "market": r.market,
                    "origin": r.origin.isoformat(),
                    "horizon_days": r.horizon_days,
                    "forecast_id": r.forecast_id,
                    "n_days": r.n_days,
                    "mae": r.mae,
                    "mape": r.mape,
                    "bias": r.bias,
                    "coverage": r.coverage,
                }
                for r in found
            ]
        }

    @app.get("/backtests/{result_id}")
    def get_backtest(result_id: str) -> dict:
        found = store.get_backtest_result(result_id)
        if found is None:
            raise HTTPException(
                status_code=404, detail=f"unknown backtest result {result_id}"
            )
        return found.model_dump(mode="json")

    @app.get("/accuracy")
    def list_accuracy(
        commodity: str | None = Query(None), market: str | None = Query(None)
    ) -> dict:
        found = store.list_accuracy_records(commodity, market)
        return {"records": [r.model_dump(mode="json") for r in found]}

    @app.get("/accuracy/{commodity}/{market}/{horizon_days}")
    def get_accuracy(commodity: str, market: str, horizon_days: int) -> dict:
        found = store.get_accuracy_record(commodity, market, horizon_days)
        if found is None:
            raise HTTPException(
                status_code=404,
                detail=f"no accuracy record for {commodity}/{market} at "
                f"{horizon_days} days — the harness has not covered it",
            )
        return found.model_dump(mode="json")

    # -- dashboards + the morning board (R7, Law 6) ---------------------

    @app.get("/dashboards/pack")
    def dashboard_pack() -> dict:
        return load_dashboard_pack().model_dump(mode="json")

    @app.post("/dashboards/ask")
    def ask_dashboard(body: AskDashboardRequest) -> dict:
        try:
            spec = dashboard_service.ask(
                body.prompt, body.asked_by, body.created_on or date.today()
            )
        except DashboardParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except DashboardValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ModelNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return spec.model_dump(mode="json")

    @app.get("/dashboards/specs")
    def list_dashboard_specs() -> dict:
        found = dashboard_service.list_specs()
        return {"specs": [s.model_dump(mode="json") for s in found]}

    @app.get("/dashboards/specs/{spec_id}")
    def get_dashboard_spec(spec_id: str) -> dict:
        try:
            return dashboard_service.get_spec(spec_id).model_dump(mode="json")
        except DashboardNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/dashboards/specs/{spec_id}/save")
    def save_dashboard_view(spec_id: str, body: SaveViewRequest) -> dict:
        try:
            view = dashboard_service.save_view(
                spec_id, body.name, body.saved_by, body.saved_on or date.today()
            )
        except DashboardNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DashboardValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return view.model_dump(mode="json")

    @app.get("/dashboards/views")
    def list_dashboard_views(name: str | None = Query(None)) -> dict:
        found = dashboard_service.list_views(name)
        return {"views": [v.model_dump(mode="json") for v in found]}

    @app.post("/dashboards/specs/{spec_id}/assemble")
    def assemble_dashboard(
        spec_id: str, body: AssembleDashboardRequest | None = None
    ) -> dict:
        try:
            assembly = dashboard_service.assemble(
                spec_id,
                (body.assembled_on if body else None) or date.today(),
            )
        except DashboardNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DashboardVerificationError as exc:
            raise HTTPException(
                status_code=422,
                detail={"problems": exc.problems},
            ) from exc
        return assembly.model_dump(mode="json")

    @app.get("/dashboards/assemblies/{assembly_id}")
    def get_dashboard_assembly(assembly_id: str) -> dict:
        try:
            return dashboard_service.get_assembly(assembly_id).model_dump(
                mode="json"
            )
        except DashboardNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/dashboards/assemblies/{assembly_id}/html")
    def get_dashboard_html(assembly_id: str) -> HTMLResponse:
        try:
            assembly = dashboard_service.get_assembly(assembly_id)
        except DashboardNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return HTMLResponse(content=assembly.html)

    @app.get("/dashboards/assemblies/{assembly_id}/appendix")
    def get_dashboard_appendix(assembly_id: str) -> dict:
        try:
            return dashboard_service.appendix(assembly_id)
        except DashboardNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/dashboards/assemblies/{assembly_id}/verify")
    def verify_dashboard(assembly_id: str) -> dict:
        try:
            problems = dashboard_service.verify_stored(assembly_id)
        except DashboardNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"assembly_id": assembly_id, "problems": problems}

    @app.get("/board")
    def get_board(board_date: date | None = Query(None)) -> dict:
        try:
            view = dashboard_service.board_view(board_date)
        except DashboardValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"board": view["board"], "sections": view["sections"]}

    @app.get("/board/html")
    def get_board_html(board_date: date | None = Query(None)) -> HTMLResponse:
        try:
            view = dashboard_service.board_view(board_date)
        except DashboardValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return HTMLResponse(content=view["html"])

    # -- buy-window signals (R8, F20-PO2) -------------------------------

    @app.get("/signals/pack")
    def signal_pack() -> dict:
        return load_signal_pack().model_dump(mode="json")

    @app.post("/signals/compute")
    def compute_signal(body: ComputeSignalRequest) -> dict:
        try:
            signal = signal_service.compute_for_series(
                body.commodity, body.market
            )
        except SignalNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SignalError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return signal.model_dump(mode="json")

    @app.get("/signals")
    def list_signals(
        commodity: str | None = Query(None),
        market: str | None = Query(None),
    ) -> dict:
        found = signal_service.list_signals(commodity, market)
        return {"signals": [s.model_dump(mode="json") for s in found]}

    @app.get("/signals/{signal_id}")
    def get_signal(signal_id: str) -> dict:
        try:
            return signal_service.signal_view(signal_id)
        except SignalNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/signals/{signal_id}/verify")
    def verify_signal_endpoint(signal_id: str) -> dict:
        try:
            problems = signal_service.verify_stored(signal_id)
        except SignalNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"signal_id": signal_id, "problems": problems}

    # -- coverage & exposure planning (R8, F20-PO3) ---------------------

    @app.get("/planning/pack")
    def planning_pack() -> dict:
        return load_planning_pack().model_dump(mode="json")

    @app.post("/planning/plans", status_code=201)
    def enter_plan(body: EnterPlanRequest) -> dict:
        try:
            plan = planning_service.enter_plan(
                commodity=body.commodity,
                market=body.market,
                entered_by=body.entered_by,
                entered_on=body.entered_on or date.today(),
                opening_stock_tonnes=body.opening_stock_tonnes,
                lines=body.lines,
                note=body.note,
            )
        except PlanningValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return planning_service.plan_view(plan.plan_id)

    @app.get("/planning/plans")
    def list_plans(
        commodity: str | None = Query(None),
        market: str | None = Query(None),
    ) -> dict:
        found = planning_service.list_plans(commodity, market)
        return {"plans": [p.model_dump(mode="json") for p in found]}

    @app.get("/planning/plans/{plan_id}")
    def get_plan(plan_id: str) -> dict:
        try:
            return planning_service.plan_view(plan_id)
        except PlanningNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/planning/plans/{plan_id}/assess")
    def assess_plan(plan_id: str, body: AssessPlanRequest) -> dict:
        try:
            assessment = planning_service.assess(plan_id, basis=body.basis)
        except PlanningNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PlanningValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PlanningStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PlanningError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return assessment.model_dump(mode="json")

    @app.get("/planning/assessments")
    def list_assessments(plan_id: str | None = Query(None)) -> dict:
        found = planning_service.list_assessments(plan_id)
        return {
            "assessments": [a.model_dump(mode="json") for a in found]
        }

    @app.get("/planning/assessments/{assessment_id}")
    def get_assessment(assessment_id: str) -> dict:
        try:
            return planning_service.assessment_view(assessment_id)
        except PlanningNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/planning/assessments/{assessment_id}/verify")
    def verify_assessment_endpoint(assessment_id: str) -> dict:
        try:
            problems = planning_service.verify_assessment_stored(
                assessment_id
            )
        except PlanningNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"assessment_id": assessment_id, "problems": problems}

    # -- alerting, subscriptions and escalation (R9, F20-AL1/AL2/AL3) --

    @app.get("/alerts/pack")
    def alert_pack() -> dict:
        return load_alert_pack().model_dump(mode="json")

    @app.post("/alerts/subscriptions", status_code=201)
    def subscribe(body: SubscribeRequest) -> dict:
        try:
            subscription = alert_service.enter_subscription(
                subscriber=body.subscriber,
                role=body.role,
                entered_on=body.entered_on or date.today(),
                commodities=body.commodities,
                markets=body.markets,
                kinds=body.kinds,
                min_severity=body.min_severity,
                note=body.note,
            )
        except AlertValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return alert_service.subscription_view(subscription.subscription_id)

    @app.get("/alerts/subscriptions")
    def list_subscriptions(
        subscriber: str | None = Query(None),
    ) -> dict:
        found = alert_service.list_subscriptions(subscriber)
        return {
            "subscriptions": [
                alert_service.subscription_view(s.subscription_id)
                for s in found
            ]
        }

    @app.post("/alerts/sweep")
    def sweep(body: SweepRequest) -> dict:
        return alert_service.sweep(body.at)

    @app.get("/alerts/crossings")
    def list_crossings(
        commodity: str | None = Query(None),
        market: str | None = Query(None),
    ) -> dict:
        found = store.list_price_crossings(commodity, market)
        return {"crossings": [c.model_dump(mode="json") for c in found]}

    @app.get("/alerts")
    def list_alerts(
        commodity: str | None = Query(None),
        market: str | None = Query(None),
        subscription_id: str | None = Query(None),
    ) -> dict:
        found = alert_service.list_alerts(commodity, market, subscription_id)
        return {"alerts": [a.model_dump(mode="json") for a in found]}

    @app.get("/alerts/{alert_id}")
    def get_alert(
        alert_id: str, at: datetime | None = Query(None)
    ) -> dict:
        try:
            return alert_service.alert_view(alert_id, at or datetime.now())
        except AlertNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/alerts/{alert_id}/acknowledge")
    def acknowledge_alert(alert_id: str, body: AlertActRequest) -> dict:
        try:
            act = alert_service.acknowledge(
                alert_id,
                actor=body.actor,
                role=body.role,
                acted_at=body.at,
                note=body.note,
            )
        except AlertNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AlertValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AlertStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return act.model_dump(mode="json")

    @app.post("/alerts/{alert_id}/close")
    def close_alert(alert_id: str, body: CloseAlertRequest) -> dict:
        try:
            act = alert_service.close(
                alert_id,
                actor=body.actor,
                role=body.role,
                acted_at=body.at,
                reason=body.reason,
                note=body.note,
            )
        except AlertNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AlertValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AlertStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return act.model_dump(mode="json")

    @app.get("/alerts/{alert_id}/verify")
    def verify_alert_endpoint(alert_id: str) -> dict:
        try:
            problems = alert_service.verify_stored(alert_id)
        except AlertNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"alert_id": alert_id, "problems": problems}

    @app.post("/alerts/digests", status_code=201)
    def build_digest(body: DigestRequest) -> dict:
        try:
            digest = alert_service.build_digest(
                body.subscription_id, body.digest_date
            )
        except AlertNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return alert_service.digest_view(digest.digest_id)

    @app.get("/alerts/digests/{digest_id}")
    def get_digest(digest_id: str) -> dict:
        try:
            return alert_service.digest_view(digest_id)
        except AlertNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # -- thin-data assessments (R10, Law 7 depth) ------------------------

    @app.get("/thin-data/pack")
    def thin_data_pack() -> dict:
        return load_thin_data_pack().model_dump(mode="json")

    @app.post("/thin-data/assessments", status_code=201)
    def assess_forecast(body: AssessForecastRequest) -> dict:
        try:
            assessment = thin_service.assess_forecast(body.forecast_id)
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ThinDataError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return thin_service.assessment_view(assessment.assessment_id)

    @app.get("/thin-data/assessments")
    def list_thin_assessments(
        commodity: str | None = Query(None),
        market: str | None = Query(None),
    ) -> dict:
        found = thin_service.list_assessments(commodity, market)
        return {
            "assessments": [a.model_dump(mode="json") for a in found]
        }

    @app.get("/thin-data/assessments/{assessment_id}")
    def get_thin_assessment(assessment_id: str) -> dict:
        try:
            return thin_service.assessment_view(assessment_id)
        except ThinDataNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/thin-data/assessments/{assessment_id}/verify")
    def verify_thin_assessment(assessment_id: str) -> dict:
        try:
            problems = thin_service.verify_stored(assessment_id)
        except ThinDataNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"assessment_id": assessment_id, "problems": problems}

    @app.get("/thin-data/forecasts/{forecast_id}")
    def get_forecast_thin_data(forecast_id: str) -> dict:
        try:
            return thin_service.forecast_view(forecast_id)
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ThinDataError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/thin-data/claims/verify")
    def verify_tier_claim(body: TierClaimRequest) -> dict:
        try:
            problems = thin_service.verify_claim(
                body.forecast_id, body.horizon_days, body.claimed_tier
            )
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ThinDataError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "forecast_id": body.forecast_id,
            "horizon_days": body.horizon_days,
            "claimed_tier": body.claimed_tier,
            "problems": problems,
        }

    # -- assisted intake, maker–checker (R10, F20-DI3) -------------------

    @app.post("/intake/entries", status_code=201)
    def enter_intake(body: EnterIntakeRequest) -> dict:
        try:
            entry = intake_service.enter(
                commodity=body.commodity,
                market=body.market,
                obs_date=body.obs_date,
                driver=body.driver,
                value=body.value,
                entered_by=body.entered_by,
                entered_by_role=body.entered_by_role,
                entered_at=body.entered_at or datetime.now(),
                source_note=body.source_note,
            )
        except IntakeValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return intake_service.entry_view(entry.entry_id)

    @app.get("/intake/entries")
    def list_intake_entries(
        commodity: str | None = Query(None),
        market: str | None = Query(None),
        state: str | None = Query(None),
    ) -> dict:
        found = intake_service.list_entries(commodity, market, state)
        return {
            "entries": [
                intake_service.entry_view(e.entry_id) for e in found
            ]
        }

    @app.get("/intake/entries/{entry_id}")
    def get_intake_entry(entry_id: str) -> dict:
        try:
            return intake_service.entry_view(entry_id)
        except IntakeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/intake/entries/{entry_id}/confirm")
    def confirm_intake(entry_id: str, body: IntakeCheckRequest) -> dict:
        try:
            act = intake_service.confirm(
                entry_id,
                checker=body.checker,
                checker_role=body.checker_role,
                acted_at=body.at or datetime.now(),
                note=body.note,
            )
        except IntakeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except IntakeValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except IntakeStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return act.model_dump(mode="json")

    @app.post("/intake/entries/{entry_id}/reject")
    def reject_intake(entry_id: str, body: IntakeCheckRequest) -> dict:
        try:
            act = intake_service.reject(
                entry_id,
                checker=body.checker,
                checker_role=body.checker_role,
                acted_at=body.at or datetime.now(),
                note=body.note,
            )
        except IntakeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except IntakeValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except IntakeStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return act.model_dump(mode="json")

    @app.get("/intake/entries/{entry_id}/verify")
    def verify_intake_entry(entry_id: str) -> dict:
        try:
            problems = intake_service.verify_stored(entry_id)
        except IntakeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"entry_id": entry_id, "problems": problems}

    # -- production data plane (R11, F20-DI1/DI2/DI4) --------------------

    @app.get("/ingest/pack")
    def ingest_pack() -> dict:
        return load_ingest_pack().model_dump(mode="json")

    @app.get("/ingest/sources")
    def list_ingest_sources() -> dict:
        return {
            "sources": [
                s.model_dump(mode="json") for s in ingest_service.list_sources()
            ]
        }

    @app.post("/ingest/sources", status_code=201)
    def register_ingest_source(body: RegisterSourceRequest) -> dict:
        try:
            registration = ingest_service.register_source(
                body.source_id,
                body.kind,
                body.display,
                body.owner,
                body.cadence,
                body.drivers,
                body.licence_note,
                body.registered_by,
                body.registered_by_role,
                body.at or datetime.now(timezone.utc),
            )
        except IngestValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return registration.model_dump(mode="json")

    @app.post("/ingest/batches/file", status_code=201)
    def load_ingest_file(body: LoadFileRequest) -> dict:
        try:
            batch = ingest_service.load_file_drop(
                body.source_id,
                body.csv_text,
                as_of=body.as_of,
                received_by=body.received_by,
                received_at=body.at or datetime.now(timezone.utc),
                connector_kind=body.kind,
            )
        except IngestValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ingest_service.batch_view(batch.batch_id)

    @app.post("/ingest/batches/push", status_code=201)
    def load_ingest_push(body: LoadPushRequest) -> dict:
        try:
            batch = ingest_service.load_api_push(
                body.source_id,
                body.rows,
                as_of=body.as_of,
                received_by=body.received_by,
                received_at=body.at or datetime.now(timezone.utc),
            )
        except IngestValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ingest_service.batch_view(batch.batch_id)

    @app.get("/ingest/batches")
    def list_ingest_batches(source: str | None = None) -> dict:
        return {
            "batches": [
                b.model_dump(mode="json")
                for b in ingest_service.list_batches(source)
            ]
        }

    @app.get("/ingest/batches/{batch_id}")
    def get_ingest_batch(batch_id: str) -> dict:
        try:
            return ingest_service.batch_view(batch_id)
        except IngestNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/ingest/quarantine")
    def list_ingest_quarantine(batch: str | None = None) -> dict:
        return {
            "quarantine": [
                r.model_dump(mode="json")
                for r in ingest_service.list_quarantine(batch_id=batch)
            ]
        }

    @app.post("/ingest/corrections", status_code=201)
    def create_ingest_correction(body: CorrectRequest) -> dict:
        try:
            correction = ingest_service.correct(
                body.commodity,
                body.market,
                body.obs_date,
                body.driver,
                body.value,
                reason=body.reason,
                corrected_by=body.corrected_by,
                corrected_by_role=body.corrected_by_role,
                corrected_at=body.at or datetime.now(timezone.utc),
                corrects_quarantine_id=body.corrects_quarantine_id,
            )
        except IngestNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except IngestValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return correction.model_dump(mode="json")

    @app.get("/ingest/corrections")
    def list_ingest_corrections(
        commodity: str, market: str, obs_date: date, driver: str
    ) -> dict:
        chain = ingest_service.correction_chain(commodity, market, obs_date, driver)
        return {"corrections": [c.model_dump(mode="json") for c in chain]}

    @app.get("/ingest/effective")
    def get_ingest_effective(
        commodity: str, market: str, obs_date: date, driver: str
    ) -> dict:
        return ingest_service.effective_fact(commodity, market, obs_date, driver)

    @app.post("/ingest/backfill/replay", status_code=201)
    def create_backfill_replay(body: ReplayRequest) -> dict:
        try:
            replay = ingest_service.replay_backtests(
                body.commodity,
                body.market,
                body.origins,
                replayed_by=body.replayed_by,
                replayed_at=body.at or datetime.now(timezone.utc),
            )
        except IngestValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return replay.model_dump(mode="json")

    @app.get("/ingest/verify")
    def verify_ingest() -> dict:
        return {"problems": ingest_service.verify_all()}

    # -- forecast-ops analytics (R12, F20-AM1) ---------------------------

    @app.get("/analytics/pack")
    def analytics_pack() -> dict:
        return load_analytics_pack().model_dump(mode="json")

    @app.post("/analytics/reports", status_code=201)
    def build_analytics_report() -> dict:
        try:
            report = analytics_service.build_report()
        except AnalyticsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return analytics_service.report_view(report.report_id)

    @app.get("/analytics/reports")
    def list_analytics_reports() -> dict:
        return {
            "reports": [
                r.model_dump(mode="json")
                for r in analytics_service.list_reports()
            ]
        }

    @app.get("/analytics/reports/{report_id}")
    def get_analytics_report(report_id: str) -> dict:
        try:
            return analytics_service.report_view(report_id)
        except AnalyticsNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/analytics/reports/{report_id}/verify")
    def verify_analytics_report(report_id: str) -> dict:
        try:
            problems = analytics_service.verify_stored(report_id)
        except AnalyticsNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"report_id": report_id, "problems": problems}

    # -- operator console (R13: F20-OW2, F20-OW3, F20-OW4, F20-MF2) ----

    @app.get("/console/pack")
    def console_pack() -> dict:
        return load_console_pack().model_dump(mode="json")

    @app.post("/console/preflights", status_code=201)
    def strike_preflight(body: StrikePreflightRequest) -> dict:
        try:
            report = console_service.strike_preflight(
                body.commodity, body.market, body.as_of
            )
        except ConsoleValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return console_service.preflight_view(report.report_id)

    @app.get("/console/preflights")
    def list_preflights(
        commodity: str | None = Query(None), market: str | None = Query(None)
    ) -> dict:
        return {
            "reports": [
                r.model_dump(mode="json")
                for r in console_service.list_preflights(commodity, market)
            ]
        }

    @app.get("/console/preflights/{report_id}")
    def get_preflight(report_id: str) -> dict:
        try:
            return console_service.preflight_view(report_id)
        except ConsoleNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/console/preflights/{report_id}/verify")
    def verify_preflight_endpoint(report_id: str) -> dict:
        try:
            report = console_service.get_preflight(report_id)
        except ConsoleNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        from fmcg_forecast.console.verify import verify_preflight

        return {
            "report_id": report_id,
            "problems": verify_preflight(store, report),
        }

    @app.get("/console/review-queue")
    def get_review_queue() -> dict:
        return {"rows": console_service.review_queue()}

    @app.get("/console/triage-queue")
    def get_triage_queue() -> dict:
        return {"rows": console_service.triage_queue()}

    @app.get("/market-events/{event_id}/triage")
    def get_event_triage(event_id: str) -> dict:
        try:
            return console_service.triage_view(event_id)
        except EventNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/market-events/{event_id}/triage/confirm")
    def confirm_event(event_id: str, body: TriageActRequest) -> dict:
        try:
            act = console_service.confirm_event(
                event_id,
                body.actor,
                body.role,
                body.acted_on or date.today(),
                body.note,
            )
        except EventNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConsoleValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ConsoleStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return act.model_dump(mode="json")

    @app.post("/market-events/{event_id}/triage/retire")
    def retire_event(event_id: str, body: TriageActRequest) -> dict:
        try:
            act = console_service.retire_event(
                event_id,
                body.actor,
                body.role,
                body.acted_on or date.today(),
                body.note,
            )
        except EventNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConsoleValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ConsoleStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return act.model_dump(mode="json")

    @app.post("/market-events/{event_id}/triage/amend")
    def amend_event(event_id: str, body: AmendEventRequest) -> dict:
        replacement = body.replacement.model_dump(mode="json")
        replacement["window_start"] = body.replacement.window_start
        replacement["window_end"] = body.replacement.window_end
        replacement["declared_on"] = (
            body.replacement.declared_on or body.acted_on or date.today()
        )
        try:
            act = console_service.amend_event(
                event_id,
                body.actor,
                body.role,
                body.acted_on or date.today(),
                replacement,
                body.note,
            )
        except EventNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ConsoleValidationError, EventValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ConsoleStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return act.model_dump(mode="json")

    @app.get("/console")
    def get_console(
        board_date: date | None = Query(None),
        now: datetime | None = Query(None),
    ) -> dict:
        try:
            return console_service.console_view(board_date, now)
        except ConsoleNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/console/html")
    def get_console_html(
        board_date: date | None = Query(None),
        now: datetime | None = Query(None),
    ) -> HTMLResponse:
        try:
            view = console_service.console_view(board_date, now)
        except ConsoleNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return HTMLResponse(render_console(view))

    @app.get("/console/phone")
    def get_console_phone(
        board_date: date | None = Query(None),
        now: datetime | None = Query(None),
    ) -> HTMLResponse:
        try:
            view = console_service.console_view(board_date, now)
        except ConsoleNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return HTMLResponse(render_console_phone(view))

    @app.post("/console/actions")
    def console_action(body: ConsoleActionRequest) -> dict:
        action = body.model_dump(mode="json")
        action = {k: v for k, v in action.items() if v is not None}
        if body.replacement is not None:
            replacement = body.replacement.model_dump(mode="json")
            replacement["window_start"] = body.replacement.window_start
            replacement["window_end"] = body.replacement.window_end
            replacement["declared_on"] = (
                body.replacement.declared_on or body.acted_on or date.today()
            )
            action["replacement"] = replacement
        try:
            return console_service.dispatch_action(action)
        except (ConsoleNotFoundError, EventNotFoundError, AlertNotFoundError,
                ForecastNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ConsoleValidationError, EventValidationError,
                AlertValidationError, ApprovalValidationError,
                KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (ConsoleStateError, AlertStateError,
                ApprovalStateError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/console/verify")
    def verify_console_endpoint() -> dict:
        return {"problems": console_service.verify_stored()}

    return app
