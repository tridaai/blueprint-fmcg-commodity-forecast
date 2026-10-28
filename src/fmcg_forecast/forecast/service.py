"""The forecast service: run, publish, explain — one workflow.

Every surface (API, CLI/demo) shares this service. Its rules:

- a run is idempotent: the artefact is content-addressed, so
  re-running the same estimation returns the stored artefact with
  its current status instead of duplicating it;
- a forecast is born a DRAFT; it becomes the desk's official view
  only through a recorded approval act by a named approver with a
  named role (placeholder names are refused);
- commentary is drafted by the model port and stored only if every
  figure in it verifies against the artefact — a bad draft is
  refused wholesale and nothing is stored.
"""

from __future__ import annotations

import hashlib
from datetime import date

from fmcg_forecast.forecast.commentary import (
    commentary_figures,
    commentary_subject,
    verify_commentary,
)
from fmcg_forecast.forecast.engine import EventAdjustment, ForecastError, run_engine
from fmcg_forecast.forecast.models import Commentary, Forecast, ForecastApproval
from fmcg_forecast.forecast.verify import verify_forecast
from fmcg_forecast.modelport import ModelPort

_PLACEHOLDERS = {"", "unknown", "n/a", "na", "tbd", "none", "-", "null", "anon", "anonymous"}


class ForecastNotFoundError(RuntimeError):
    """No forecast artefact with that id."""


class ApprovalError(RuntimeError):
    """Base for approval-act refusals."""


class ApprovalValidationError(ApprovalError):
    """The act itself is malformed (unnamed approver or role)."""


class ApprovalStateError(ApprovalError):
    """The forecast is not in a state that can be approved."""


class CommentaryVerificationError(RuntimeError):
    """A commentary draft stated figures the artefact does not carry."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _require_named(value: str, field: str) -> str:
    cleaned = value.strip()
    if cleaned.lower() in _PLACEHOLDERS:
        raise ApprovalValidationError(
            f"{field} must name a person or role of record, not {value!r}"
        )
    return cleaned


class ForecastService:
    def __init__(self, store, model: ModelPort):
        self.store = store
        self.model = model

    # -- runs ---------------------------------------------------------
    def run_forecast(
        self,
        commodity: str,
        market: str,
        as_of: date | None = None,
        *,
        via_backtest: bool = False,
        event_adjustments: list[EventAdjustment] | tuple[EventAdjustment, ...] = (),
    ) -> Forecast:
        manifest = self.store.get_manifest()
        if manifest is None:
            raise ForecastError("dataset not loaded; run the ingest workflow first")
        forecast = run_engine(
            self.store,
            manifest,
            commodity,
            market,
            as_of or manifest.history_end,
            via_backtest=via_backtest,
            event_adjustments=event_adjustments,
        )
        existing = self.store.get_forecast(forecast.forecast_id)
        if existing is not None:
            return existing
        self.store.insert_forecast(forecast)
        return forecast

    def get_forecast(self, forecast_id: str) -> Forecast:
        forecast = self.store.get_forecast(forecast_id)
        if forecast is None:
            raise ForecastNotFoundError(f"unknown forecast {forecast_id}")
        return forecast

    def list_forecasts(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[Forecast]:
        return self.store.list_forecasts(commodity, market)

    def contributions(self, forecast_id: str) -> dict:
        forecast = self.get_forecast(forecast_id)
        return {
            "forecast_id": forecast.forecast_id,
            "commodity": forecast.commodity,
            "market": forecast.market,
            "as_of": forecast.as_of.isoformat(),
            "attribution_order": list(forecast.method.attribution_order),
            "lines": [line.model_dump(mode="json") for line in forecast.lines],
            "horizons_summary": [
                s.model_dump(mode="json") for s in forecast.horizons_summary
            ],
            "missing_drivers": list(forecast.missing_drivers),
        }

    def verify_stored(self, forecast_id: str) -> list[str]:
        return verify_forecast(self.get_forecast(forecast_id))

    # -- the human gate -------------------------------------------------
    def approve(
        self,
        forecast_id: str,
        approver: str,
        role: str,
        decided_on: date,
    ) -> ForecastApproval:
        forecast = self.get_forecast(forecast_id)
        if forecast.status == "official":
            raise ApprovalStateError(
                f"forecast {forecast_id} is already the official view; "
                "approving it again would rewrite the record of the act"
            )
        approver = _require_named(approver, "approver")
        role = _require_named(role, "role")
        approval_id = "APPR-" + hashlib.sha256(
            f"{forecast_id}|{approver}|{decided_on.isoformat()}".encode()
        ).hexdigest()[:12]
        approval = ForecastApproval(
            approval_id=approval_id,
            forecast_id=forecast_id,
            approver=approver,
            role=role,
            decided_on=decided_on,
        )
        self.store.insert_approval(approval)
        self.store.set_forecast_status(forecast_id, "official")
        return approval

    def get_approval(self, forecast_id: str) -> ForecastApproval | None:
        self.get_forecast(forecast_id)
        return self.store.get_approval(forecast_id)

    # -- commentary -------------------------------------------------------
    def draft_commentary(self, forecast_id: str) -> Commentary:
        forecast = self.get_forecast(forecast_id)
        figures = commentary_figures(forecast)
        subject = commentary_subject(forecast)
        text = self.model.draft_commentary(subject=subject, figures=figures)
        problems = verify_commentary(text, forecast)
        if problems:
            raise CommentaryVerificationError(problems)
        commentary = Commentary(
            forecast_id=forecast_id,
            model_profile=self.model.profile_name,
            subject=subject,
            text=text,
            figures=figures,
        )
        self.store.save_commentary(commentary)
        return commentary

    def get_commentary(self, forecast_id: str) -> Commentary | None:
        self.get_forecast(forecast_id)
        return self.store.get_commentary(forecast_id)
