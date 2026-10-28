"""The operations API: read surfaces over the store port.

Round 1 ships reads only — series, the event registry, the manifest,
coverage — plus /health and /readiness. Every response carries the
request id the logging middleware assigned, so a figure on a desk
screen can be traced to the exact stored rows behind it.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from fmcg_forecast.catalogue import COMMODITIES
from fmcg_forecast.logging_config import new_request_id, request_id_var
from fmcg_forecast.store import SqlStore

log = logging.getLogger("fmcg.api")


def create_app(store: SqlStore) -> FastAPI:
    app = FastAPI(
        title="FMCG Commodity Forecast — Operations API",
        version="0.1.0",
        description="Read surfaces for the commodity price & driver store.",
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

    return app
