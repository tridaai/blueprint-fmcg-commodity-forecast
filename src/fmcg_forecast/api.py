"""The operations API: read surfaces over the store port.

Round 1 ships reads only — series, the event registry, the manifest,
coverage — plus /health and /readiness. Round 2 adds the forecast
surface: run a forecast, read its contribution breakdown, take the
approval act that makes it the desk's official view, and draft
figure-verified commentary. Every response carries the request id
the logging middleware assigned, so a figure on a desk screen can be
traced to the exact stored rows behind it.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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


def create_app(store: SqlStore, model: ModelPort | None = None) -> FastAPI:
    service = ForecastService(store, model or OfflineModel())
    app = FastAPI(
        title="FMCG Commodity Forecast — Operations API",
        version="0.2.0",
        description="Read surfaces for the commodity price & driver store, "
        "plus the governed forecast surface.",
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

    return app
