"""The operations API: read surfaces over the store port.

Round 1 ships reads only — series, the event registry, the manifest,
coverage — plus /health and /readiness. Round 2 adds the forecast
surface: run a forecast, read its contribution breakdown, take the
approval act that makes it the desk's official view, and draft
figure-verified commentary. Round 3 adds the accuracy surface
(Law 2): run the backtest harness, read its results, read the
accuracy ledger, and read any forecast's pinned accuracy snapshot —
the degraded flag rides on every forecast read; there is no
parameter that takes it off. Every response carries the request id
the logging middleware assigned, so a figure on a desk screen can be
traced to the exact stored rows behind it.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from fmcg_forecast.backtest.harness import run_all as run_backtest_harness
from fmcg_forecast.backtest.pack import load_accuracy_pack
from fmcg_forecast.catalogue import COMMODITIES
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
from fmcg_forecast.modelport import ModelPort, OfflineModel
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


def create_app(store: SqlStore, model: ModelPort | None = None) -> FastAPI:
    service = ForecastService(store, model or OfflineModel())
    app = FastAPI(
        title="FMCG Commodity Forecast — Operations API",
        version="0.3.0",
        description="Read surfaces for the commodity price & driver store, "
        "the governed forecast surface, and the backtest/accuracy surface.",
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

    return app
