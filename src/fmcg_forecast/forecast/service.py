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
  refused wholesale and nothing is stored;
- every run carries its measured accuracy (Law 2, R3): before the
  artefact is stored, the service pins the accuracy ledger's
  current records for its series onto it as a snapshot — degraded
  where the ledger stamps degraded, unmeasured (named, never
  blank) where the harness has not covered the series yet. The
  snapshot is part of the content address, and no read path offers
  a view without it;
- when a sentiment provider is wired (R4, Law 3), each run asks it
  for the commodity's index input and hands it to the engine, and
  commentary drafts pass a second gate: every sentiment claim in
  the text must cite items whose stored extractions support it.
  Unwired, both behaviours are exactly as before.
- when an events provider is wired (R5, Law 4), a run that was not
  handed explicit event adjustments asks the registry for the
  declared events touching its forecast window; each applied
  event lands on the artefact as its own named line, with the
  pack's interval widening. Unwired — or with an empty registry —
  the events slot stays exactly as it was.
- two R13 gates stand on the lifecycle: a forecast a rejection
  act stands against (F20-OW2) can never be approved — the
  check reads the act record directly, on every surface — and
  when an approval guard is wired (the console's triage gate,
  F20-OW3), approval is refused while the guard names a
  blocker, so an event that is not officially clear cannot
  enter the official view through any surface. A run may also
  pin a coverage pre-flight (F20-OW4): the checklist's named
  gaps then ride on the artefact as part of its content
  address.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import date

from fmcg_forecast.forecast.commentary import (
    commentary_figures,
    commentary_subject,
    verify_commentary,
)
from fmcg_forecast.forecast.engine import (
    EventAdjustment,
    ForecastError,
    SentimentInput,
    forecast_content_id,
    run_engine,
)
from fmcg_forecast.forecast.models import (
    HORIZONS,
    AccuracyAttachment,
    Commentary,
    Forecast,
    ForecastApproval,
    HorizonAccuracy,
    PreflightPin,
)
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
    def __init__(
        self,
        store,
        model: ModelPort,
        sentiment_provider: Callable[[str, date], SentimentInput | None] | None = None,
        sentiment_claim_verifier: Callable[[str, Forecast], list[str]] | None = None,
        events_provider: Callable[[str, date], list[EventAdjustment]] | None = None,
        approval_guard: Callable[[Forecast], list[str]] | None = None,
    ):
        self.store = store
        self.model = model
        self.sentiment_provider = sentiment_provider
        self.sentiment_claim_verifier = sentiment_claim_verifier
        self.events_provider = events_provider
        self.approval_guard = approval_guard

    # -- runs ---------------------------------------------------------
    def run_forecast(
        self,
        commodity: str,
        market: str,
        as_of: date | None = None,
        *,
        via_backtest: bool = False,
        event_adjustments: list[EventAdjustment] | tuple[EventAdjustment, ...] = (),
        preflight_id: str | None = None,
    ) -> Forecast:
        manifest = self.store.get_manifest()
        if manifest is None:
            raise ForecastError("dataset not loaded; run the ingest workflow first")
        effective_as_of = as_of or manifest.history_end
        sentiment_input = (
            self.sentiment_provider(commodity, effective_as_of)
            if self.sentiment_provider is not None
            else None
        )
        adjustments = event_adjustments
        if not adjustments and self.events_provider is not None:
            adjustments = self.events_provider(commodity, effective_as_of)
        forecast = run_engine(
            self.store,
            manifest,
            commodity,
            market,
            effective_as_of,
            via_backtest=via_backtest,
            event_adjustments=adjustments,
            sentiment_input=sentiment_input,
        )
        forecast = self._attach_accuracy(forecast)
        if preflight_id is not None:
            forecast = self._pin_preflight(forecast, preflight_id)
        existing = self.store.get_forecast(forecast.forecast_id)
        if existing is not None:
            return existing
        self.store.insert_forecast(forecast)
        return forecast

    def _pin_preflight(self, forecast: Forecast, preflight_id: str) -> Forecast:
        """Pin a coverage pre-flight's named gaps on the run (R13).

        The checklist must have been struck for this run's own
        series and as-of — a pre-flight is a judgement about a
        moment, and pinning another moment's gaps would put the
        wrong record on the artefact. The pin joins the content
        address, like the accuracy attachment.
        """
        report = self.store.get_preflight_report(preflight_id)
        if report is None:
            raise ForecastError(
                f"unknown preflight report {preflight_id} — strike "
                "the checklist before pinning it to a run"
            )
        if (report.commodity, report.market, report.as_of) != (
            forecast.commodity,
            forecast.market,
            forecast.as_of,
        ):
            raise ForecastError(
                f"preflight {preflight_id} was struck for "
                f"{report.commodity}/{report.market} at "
                f"{report.as_of.isoformat()} — it cannot be pinned "
                f"to a run for {forecast.commodity}/{forecast.market} "
                f"at {forecast.as_of.isoformat()}"
            )
        forecast.preflight = PreflightPin(
            preflight_id=report.report_id,
            pack_version=report.pack_version,
            gaps=list(report.gaps),
        )
        forecast.forecast_id = forecast_content_id(forecast)
        return forecast

    def _attach_accuracy(self, forecast: Forecast) -> Forecast:
        """Pin the ledger's current records for this series (Law 2).

        The degraded judgement is the ledger's — stamped on the
        record when it was built — copied here, never re-judged and
        never suppressible: every read of the forecast carries this
        attachment, including the state.
        """
        per_horizon: list[HorizonAccuracy] = []
        pack_version: str | None = None
        threshold: float | None = None
        for horizon in HORIZONS:
            record = self.store.get_accuracy_record(
                forecast.commodity, forecast.market, horizon
            )
            if record is None:
                per_horizon.append(
                    HorizonAccuracy(
                        horizon_days=horizon,
                        state="unmeasured",
                        record_id=None,
                        n_origins=0,
                        mae=None,
                        mape=None,
                        bias=None,
                        coverage=None,
                    )
                )
                continue
            pack_version = record.pack_version
            threshold = record.degraded_threshold_mape_pct
            per_horizon.append(
                HorizonAccuracy(
                    horizon_days=horizon,
                    state="degraded" if record.degraded else "measured",
                    record_id=record.record_id,
                    n_origins=record.n_results,
                    mae=record.mae,
                    mape=record.mape,
                    bias=record.bias,
                    coverage=record.coverage,
                )
            )
        degraded_at = [s.horizon_days for s in per_horizon if s.state == "degraded"]
        measured_at = [s.horizon_days for s in per_horizon if s.state != "unmeasured"]
        unmeasured_at = [s.horizon_days for s in per_horizon if s.state == "unmeasured"]
        if degraded_at:
            state = "degraded"
            horizons = "/".join(str(h) for h in degraded_at)
            note = (
                f"degraded at the {horizons}-day horizon(s): pooled "
                f"backtest MAPE above the accuracy pack's stated "
                f"{threshold}% bar (pack {pack_version}) — flagged on the "
                "forecast, never hidden"
            )
        elif not measured_at:
            state = "unmeasured"
            note = (
                "accuracy unmeasured: the backtest harness has not "
                "covered this series yet — no figure here claims a "
                "measured accuracy"
            )
        else:
            state = "measured"
            note = (
                f"measured over the accuracy ledger's most recent "
                f"backtest origins (pack {pack_version})"
            )
            if unmeasured_at:
                horizons = "/".join(str(h) for h in unmeasured_at)
                note += f"; no backtest coverage at the {horizons}-day horizon(s) yet"
        forecast.accuracy = AccuracyAttachment(
            state=state,  # type: ignore[arg-type]
            pack_version=pack_version,
            per_horizon=per_horizon,
            note=note,
        )
        forecast.forecast_id = forecast_content_id(forecast)
        return forecast

    def sentiment_view(self, forecast_id: str) -> dict:
        """The forecast's sentiment line, as its own read (R4).

        ``state`` is absent when the run carried no sentiment
        input at all, ``not_estimable`` when the corpus was too
        thin (the line names the failing floors), and
        ``estimated`` when the driver was estimated like any other.
        """
        forecast = self.get_forecast(forecast_id)
        line = next(
            (line for line in forecast.lines if line.driver == "sentiment"), None
        )
        if line is None:
            return {
                "forecast_id": forecast.forecast_id,
                "commodity": forecast.commodity,
                "market": forecast.market,
                "state": "absent",
                "note": "this run carried no sentiment input — the "
                "corpus was not loaded, or the provider was not wired",
                "line": None,
            }
        return {
            "forecast_id": forecast.forecast_id,
            "commodity": forecast.commodity,
            "market": forecast.market,
            "state": line.input_summary.get("state", "estimated"),
            "line": line.model_dump(mode="json"),
        }

    def events_view(self, forecast_id: str) -> dict:
        """The forecast's declared-event lines, as their own read (R5).

        ``state`` is ``clear`` when no declared event touched the
        run's window (the events adjustment is zero throughout)
        and ``shocked`` when at least one did — each such event
        with its own log path, INR contribution path and the
        interval widening it carried.
        """
        forecast = self.get_forecast(forecast_id)
        line = next(
            (line for line in forecast.lines if line.driver == "events"), None
        )
        per_event = (line.input_summary.get("per_event") if line else None) or {}
        return {
            "forecast_id": forecast.forecast_id,
            "commodity": forecast.commodity,
            "market": forecast.market,
            "as_of": forecast.as_of.isoformat(),
            "state": "shocked" if per_event else "clear",
            "events_applied": list(forecast.method.events_applied),
            "interval_widening": (
                line.input_summary.get("interval_widening") if line else None
            ),
            "events": [
                {"event_id": event_id, **entry}
                for event_id, entry in per_event.items()
            ],
            "line": line.model_dump(mode="json") if line is not None else None,
        }

    def accuracy_view(self, forecast_id: str) -> dict:
        """The forecast's pinned accuracy snapshot, as its own read."""
        forecast = self.get_forecast(forecast_id)
        return {
            "forecast_id": forecast.forecast_id,
            "commodity": forecast.commodity,
            "market": forecast.market,
            "as_of": forecast.as_of.isoformat(),
            "accuracy": (
                forecast.accuracy.model_dump(mode="json")
                if forecast.accuracy is not None
                else None
            ),
        }

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
        rejection = self.store.get_forecast_rejection(forecast_id)
        if rejection is not None:
            raise ApprovalStateError(
                f"forecast {forecast_id} was rejected by "
                f"{rejection.rejected_by} on "
                f"{rejection.decided_on.isoformat()} "
                f"({rejection.reason}) — a rejected forecast cannot "
                "be approved; a new run is required"
            )
        if self.approval_guard is not None:
            blockers = self.approval_guard(forecast)
            if blockers:
                raise ApprovalStateError(
                    "approval refused: " + "; ".join(blockers)
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
        if self.sentiment_claim_verifier is not None:
            problems = problems + self.sentiment_claim_verifier(text, forecast)
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
