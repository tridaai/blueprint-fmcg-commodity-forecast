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
the exception inbox derived from artefacts only. Every
response carries the request id the logging middleware assigned,
so a figure on a desk screen can be traced to the exact stored
rows behind it.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from fmcg_forecast.backtest.harness import run_all as run_backtest_harness
from fmcg_forecast.backtest.pack import load_accuracy_pack
from fmcg_forecast.catalogue import COMMODITIES
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
from fmcg_forecast.store import SqlStore

log = logging.getLogger("fmcg.api")


class RunForecastRequest(BaseModel):
    commodity: str
    market: str
    as_of: date | None = None
    via_backtest: bool = False


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


def create_app(store: SqlStore, model: ModelPort | None = None) -> FastAPI:
    model_port = model or OfflineModel()
    sentiment = SentimentService(store, model_port)
    event_service = EventService(store)
    service = ForecastService(
        store,
        model_port,
        sentiment_provider=sentiment.forecast_input,
        sentiment_claim_verifier=sentiment.verify_claims,
        events_provider=event_service.forecast_adjustments,
    )
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
    app = FastAPI(
        title="FMCG Commodity Forecast — Operations API",
        version="0.7.0",
        description="Read surfaces for the commodity price & driver store, "
        "the governed forecast surface, the backtest/accuracy surface, "
        "the sentiment surface, the event registry, the scenario "
        "studio, and the dashboard assembler with the morning desk "
        "board.",
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
            return service.get_forecast(forecast_id).model_dump(mode="json")
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
            return service.events_view(forecast_id)
        except ForecastNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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

    return app
