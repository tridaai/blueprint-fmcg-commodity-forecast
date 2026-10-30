"""The console workflow every surface shares (R13).

One service behind the API, the CLI, the rendered pages and
the phone action endpoint:

- *pre-flights* are struck insert-only and re-performed by
  the verifier (F20-OW4);
- *rejections* are recorded acts against a draft, with the
  pack's reason vocabulary enforced at the door (F20-OW2) —
  and the forecast service's approval path itself refuses a
  rejected forecast, so no surface can wave one through;
- *triage acts* fold into an event's state under the pack's
  state machine (F20-OW3), and ``approval_blockers`` is the
  guard the forecast service's approval path enforces: a
  forecast carrying an event that is not officially clear
  cannot become the desk's official view, on any surface;
- the *console view* composes the morning board, the review
  queue, the triage lanes, the open alerts and the
  pre-flights into one read, and ``dispatch_action`` is the
  phone surface's single door into the same act methods the
  canonical endpoints call — which is what makes a phone act
  and a desktop act the same artefact (F20-MF2).
"""

from __future__ import annotations

from datetime import date, datetime

from fmcg_forecast.alerts.service import AlertService
from fmcg_forecast.catalogue import COMMODITIES
from fmcg_forecast.console.engine import (
    ConsoleError,
    ConsoleNotFoundError,
    ConsoleStateError,
    ConsoleValidationError,
)
from fmcg_forecast.console.engine import (
    approval_blockers as _approval_blockers,
)
from fmcg_forecast.console.engine import (
    compute_preflight,
    event_state_view,
    excluded_event_ids as _excluded_event_ids,
)
from fmcg_forecast.console.engine import (
    fold_triage_state,
    review_queue as _review_queue,
)
from fmcg_forecast.console.engine import (
    triage_queue as _triage_queue,
)
from fmcg_forecast.console.models import (
    EventTriageAct,
    ForecastRejection,
    PreflightReport,
    rejection_content_id,
    triage_act_content_id,
)
from fmcg_forecast.console.pack import ConsolePack, load_console_pack
from fmcg_forecast.console.verify import (
    verify_console,
    verify_preflight,
    verify_rejection,
    verify_triage_act,
)
from fmcg_forecast.dashboards.board import build_board
from fmcg_forecast.dashboards.pack import load_dashboard_pack
from fmcg_forecast.events.service import EventService
from fmcg_forecast.forecast.models import Forecast
from fmcg_forecast.forecast.service import ForecastService
from fmcg_forecast.modelport import OfflineModel
from fmcg_forecast.store import Store

_PLACEHOLDERS = {"", "unknown", "n/a", "na", "tbd", "none", "-", "null", "anon", "anonymous"}


def _require_named(value: str, field: str) -> str:
    cleaned = value.strip()
    if cleaned.lower() in _PLACEHOLDERS:
        raise ConsoleValidationError(
            f"{field} must name a person or role of record, not {value!r}"
        )
    return cleaned


def _as_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


class ConsoleService:
    def __init__(
        self,
        store: Store,
        events: EventService,
        pack: ConsolePack | None = None,
    ):
        self.store = store
        self.events = events
        self.pack = pack or load_console_pack()

    # -- pre-flight (F20-OW4) ---------------------------------------------

    def strike_preflight(
        self, commodity: str, market: str, as_of: date | None = None
    ) -> PreflightReport:
        manifest = self.store.get_manifest()
        if manifest is None:
            raise ConsoleError("dataset not loaded; run the ingest workflow first")
        report = compute_preflight(
            self.store, commodity, market, as_of or manifest.history_end, self.pack
        )
        existing = self.store.get_preflight_report(report.report_id)
        if existing is not None:
            return existing
        self.store.insert_preflight_report(report)
        return report

    def get_preflight(self, report_id: str) -> PreflightReport:
        report = self.store.get_preflight_report(report_id)
        if report is None:
            raise ConsoleNotFoundError(f"no preflight report {report_id}")
        return report

    def list_preflights(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[PreflightReport]:
        return self.store.list_preflight_reports(commodity, market)

    def preflight_view(self, report_id: str) -> dict:
        report = self.get_preflight(report_id)
        view = report.model_dump(mode="json")
        view["problems"] = verify_preflight(self.store, report)
        return view

    # -- the review queue and its acts (F20-OW2) ----------------------------

    def review_queue(self) -> list[dict]:
        return [
            row.model_dump(mode="json")
            for row in _review_queue(self.store, self.events, self.pack)
        ]

    def reject_forecast(
        self,
        forecast_id: str,
        rejected_by: str,
        role: str,
        decided_on: date,
        reason: str,
        note: str = "",
    ) -> ForecastRejection:
        forecast = self.store.get_forecast(forecast_id)
        if forecast is None:
            raise ConsoleNotFoundError(f"unknown forecast {forecast_id}")
        rejected_by = _require_named(rejected_by, "rejected_by")
        role = _require_named(role, "role")
        if reason not in self.pack.rejection_reasons:
            raise ConsoleValidationError(
                f"unknown rejection reason {reason!r} — the pack's "
                f"vocabulary is {', '.join(self.pack.rejection_reasons)}"
            )
        if reason == "other_stated_reason" and not note.strip():
            raise ConsoleValidationError(
                "reason other_stated_reason requires the note to spell "
                "the reason out — a bare 'other' is not a reason"
            )
        act = ForecastRejection(
            rejection_id="REJ-pending",
            forecast_id=forecast_id,
            rejected_by=rejected_by,
            role=role,
            decided_on=decided_on,
            reason=reason,
            note=note,
            pack_version=self.pack.version,
        )
        act.rejection_id = rejection_content_id(act)
        existing = self.store.get_forecast_rejection(forecast_id)
        if existing is not None:
            if existing.rejection_id == act.rejection_id:
                return existing
            raise ConsoleStateError(
                f"forecast {forecast_id} already stands rejected by "
                f"{existing.rejected_by} on {existing.decided_on} "
                f"({existing.reason}) — a rejected forecast is "
                "reviewed, not re-rejectable"
            )
        if forecast.status == "official":
            raise ConsoleStateError(
                f"forecast {forecast_id} is the official view — an "
                "official forecast cannot be rejected; run a new "
                "forecast and reject that draft instead"
            )
        self.store.insert_forecast_rejection(act)
        return act

    def get_rejection(self, forecast_id: str) -> ForecastRejection | None:
        if self.store.get_forecast(forecast_id) is None:
            raise ConsoleNotFoundError(f"unknown forecast {forecast_id}")
        return self.store.get_forecast_rejection(forecast_id)

    def list_rejections(self) -> list[ForecastRejection]:
        return self.store.list_forecast_rejections()

    def rejection_view(self, forecast_id: str) -> dict:
        rejection = self.get_rejection(forecast_id)
        if rejection is None:
            return {"forecast_id": forecast_id, "rejection": None, "problems": []}
        return {
            "forecast_id": forecast_id,
            "rejection": rejection.model_dump(mode="json"),
            "problems": verify_rejection(self.store, rejection),
        }

    # -- event triage (F20-OW3) ----------------------------------------------

    def triage_state(self, event_id: str) -> str:
        self.events.get_event(event_id)
        return fold_triage_state(self.store.list_event_triage_acts(event_id))

    def triage_view(self, event_id: str) -> dict:
        event = self.events.get_event(event_id)
        return event_state_view(self.store, self.events, event)

    def triage_queue(self) -> list[dict]:
        return [
            row.model_dump(mode="json")
            for row in _triage_queue(self.store, self.events)
        ]

    def _record_triage_act(
        self,
        event_id: str,
        act: str,
        actor: str,
        role: str,
        acted_on: date,
        replacement_event_id: str | None,
        note: str,
        allowed_from: set[str],
    ) -> EventTriageAct:
        event = self.events.get_event(event_id)
        actor = _require_named(actor, "actor")
        role = _require_named(role, "role")
        state = fold_triage_state(self.store.list_event_triage_acts(event_id))
        if state not in allowed_from:
            raise ConsoleStateError(
                f"event {event_id} is {state} — a {act} act does not "
                f"stand against a {state} event"
            )
        record = EventTriageAct(
            act_id="TRI-pending",
            event_id=event.event_id,
            act=act,  # type: ignore[arg-type]
            actor=actor,
            role=role,
            acted_on=acted_on,
            replacement_event_id=replacement_event_id,
            note=note,
            pack_version=self.pack.version,
        )
        record.act_id = triage_act_content_id(record)
        if self.store.get_event_triage_act(record.act_id) is None:
            self.store.insert_event_triage_act(record)
        return record

    def confirm_event(
        self,
        event_id: str,
        actor: str,
        role: str,
        acted_on: date,
        note: str = "",
    ) -> EventTriageAct:
        return self._record_triage_act(
            event_id, "confirm", actor, role, acted_on, None, note,
            {"declared", "retired"},
        )

    def retire_event(
        self,
        event_id: str,
        actor: str,
        role: str,
        acted_on: date,
        note: str = "",
    ) -> EventTriageAct:
        return self._record_triage_act(
            event_id, "retire", actor, role, acted_on, None, note,
            {"declared", "confirmed"},
        )

    def amend_event(
        self,
        event_id: str,
        actor: str,
        role: str,
        acted_on: date,
        replacement: dict,
        note: str = "",
    ) -> EventTriageAct:
        event = self.events.get_event(event_id)
        actor = _require_named(actor, "actor")
        role = _require_named(role, "role")
        state = fold_triage_state(self.store.list_event_triage_acts(event_id))
        if state not in {"declared", "confirmed"}:
            raise ConsoleStateError(
                f"event {event_id} is {state} — an amend act does not "
                f"stand against a {state} event"
            )
        fields = dict(replacement)
        if fields.get("commodity", event.commodity) != event.commodity:
            raise ConsoleValidationError(
                "an amendment corrects the event's own declaration — "
                f"the replacement is for {fields.get('commodity')!r}, "
                f"the event is for {event.commodity!r}; declare a new "
                "event instead"
            )
        fields["commodity"] = event.commodity
        fields.setdefault("declared_by", actor)
        fields.setdefault("declared_on", acted_on)
        new_event = self.events.register_event(**fields)
        if new_event.event_id == event.event_id:
            raise ConsoleValidationError(
                "the amendment restates the declaration it amends — "
                "an amendment must change the declaration"
            )
        return self._record_triage_act(
            event_id, "amend", actor, role, acted_on, new_event.event_id,
            note, {"declared", "confirmed"},
        )

    def approval_blockers(self, forecast: Forecast) -> list[str]:
        """The guard the approval path enforces (engine-computed)."""
        return _approval_blockers(self.store, self.events, forecast)

    def excluded_event_ids(self) -> set[str]:
        """Events new runs must not apply: retired or superseded."""
        return _excluded_event_ids(self.store)

    # -- the composed console view --------------------------------------------

    def console_view(
        self, board_date: date | None = None, now: datetime | None = None
    ) -> dict:
        manifest = self.store.get_manifest()
        if manifest is None:
            raise ConsoleNotFoundError("dataset not loaded")
        board_date = board_date or manifest.history_end
        now = now or datetime.now()

        dashboard_pack = load_dashboard_pack()
        board = build_board(self.store, self.events, dashboard_pack, board_date)
        sections: dict[str, list[dict]] = {}
        for section in dashboard_pack.board_sections:
            sections[section] = [
                row.model_dump(mode="json")
                for row in board.rows
                if row.kind == section
            ]
        sections["signal"] = [
            row.model_dump(mode="json")
            for row in board.rows
            if row.kind == "signal"
        ]

        queue = self.review_queue()
        queue_counts: dict[str, int] = {}
        for row in queue:
            queue_counts[row["accuracy_state"]] = (
                queue_counts.get(row["accuracy_state"], 0) + 1
            )

        lanes = self.triage_queue()
        lane_counts: dict[str, int] = {}
        for row in lanes:
            lane_counts[row["lane"]] = lane_counts.get(row["lane"], 0) + 1

        alert_service = AlertService(self.store)
        open_alerts: list[dict] = []
        for alert in alert_service.list_alerts():
            view = alert_service.alert_view(alert.alert_id, now)
            if view["state"]["state"] != "closed":
                open_alerts.append(view)

        preflights: list[dict] = []
        for spec in COMMODITIES:
            for market in spec.markets:
                report = compute_preflight(
                    self.store, spec.commodity, market.market, board_date,
                    self.pack,
                )
                row = report.model_dump(mode="json")
                row["struck"] = (
                    self.store.get_preflight_report(report.report_id)
                    is not None
                )
                preflights.append(row)

        return {
            "pack_version": self.pack.version,
            "board_date": board_date.isoformat(),
            "morning_board": {
                "board_id": board.board_id,
                "sections": sections,
                "row_count": len(board.rows),
            },
            "review_queue": {"rows": queue, "counts": queue_counts},
            "triage_queue": {"rows": lanes, "counts_by_lane": lane_counts},
            "rejections": [
                r.model_dump(mode="json") for r in self.list_rejections()
            ],
            "open_alerts": {"rows": open_alerts, "count": len(open_alerts)},
            "preflights": preflights,
            "problems": verify_console(self.store),
        }

    # -- the phone surface's single door (F20-MF2) -----------------------------

    def dispatch_action(self, action: dict) -> dict:
        """One act, struck through the console's action door.

        Every kind delegates to the same service method the
        canonical endpoint calls, with the same inputs — so
        the act artefact a phone strikes is byte-identical to
        the one the desktop path strikes. The approval goes
        through a forecast service carrying the triage guard,
        exactly as the API wires it.
        """
        kind = action.get("kind")
        if kind == "approve_forecast":
            forecasts = ForecastService(
                self.store,
                OfflineModel(),
                approval_guard=self.approval_blockers,
            )
            approval = forecasts.approve(
                action["forecast_id"],
                action["approver"],
                action["role"],
                _as_date(action["decided_on"]),
            )
            return approval.model_dump(mode="json")
        if kind == "reject_forecast":
            act = self.reject_forecast(
                action["forecast_id"],
                action["rejected_by"],
                action["role"],
                _as_date(action["decided_on"]),
                action["reason"],
                action.get("note", ""),
            )
            return act.model_dump(mode="json")
        if kind == "confirm_event":
            act = self.confirm_event(
                action["event_id"],
                action["actor"],
                action["role"],
                _as_date(action["acted_on"]),
                action.get("note", ""),
            )
            return act.model_dump(mode="json")
        if kind == "retire_event":
            act = self.retire_event(
                action["event_id"],
                action["actor"],
                action["role"],
                _as_date(action["acted_on"]),
                action.get("note", ""),
            )
            return act.model_dump(mode="json")
        if kind == "amend_event":
            act = self.amend_event(
                action["event_id"],
                action["actor"],
                action["role"],
                _as_date(action["acted_on"]),
                action["replacement"],
                action.get("note", ""),
            )
            return act.model_dump(mode="json")
        if kind in ("acknowledge_alert", "close_alert"):
            alerts = AlertService(self.store)
            if kind == "acknowledge_alert":
                act = alerts.acknowledge(
                    action["alert_id"],
                    action["actor"],
                    action["role"],
                    _as_datetime(action["acted_at"]),
                    action.get("note", ""),
                )
            else:
                act = alerts.close(
                    action["alert_id"],
                    action["actor"],
                    action["role"],
                    _as_datetime(action["acted_at"]),
                    action["reason"],
                    action.get("note", ""),
                )
            return act.model_dump(mode="json")
        raise ConsoleValidationError(
            f"unknown console action kind {kind!r} — the console "
            "admits approve_forecast, reject_forecast, confirm_event, "
            "amend_event, retire_event, acknowledge_alert and "
            "close_alert"
        )

    # -- verification -----------------------------------------------------------

    def verify_stored(self) -> list[str]:
        return verify_console(self.store)

    def verify_triage_act(self, act_id: str) -> list[str]:
        act = self.store.get_event_triage_act(act_id)
        if act is None:
            raise ConsoleNotFoundError(f"no triage act {act_id}")
        return verify_triage_act(self.store, act)
