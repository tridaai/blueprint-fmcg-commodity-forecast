"""The scenario service: parse, fork, diff, adopt — one workflow.

Every surface (API, CLI, demo) shares this service. Its rules:

- **Parse is the model port's job, validation is the pack's.**
  A typed what-if goes through the model port (offline: the
  pack's stated grammar; hosted: structured outputs, fail-closed)
  into a lever set, and the set is validated against the scenario
  pack before it becomes a request artefact — bounds included.
  A refusal names the clause or the bound; nothing is silently
  reinterpreted.
- **A run is a pinned fork.** It re-runs the base forecast's own
  estimation with the levers applied to the driver INPUT paths
  (through the engine's shift slot) and the events slot (base
  events re-derived from the insert-only registry, scenario
  events appended in lever order). The decomposition identity
  holds on the fork exactly as on the base, and the baseline is
  shared — only inputs moved. The fork lives on the run; it is
  never inserted into the desk's forecast record, and the base
  artefact is never mutated.
- **Adoption is a named human act.** A scenario becomes the
  desk's adopted view for its series only through an adoption
  act by a named adopter with a named role (placeholders are
  refused, as at the forecast approval gate). The act supersedes
  the series' previously adopted scenario by link. An unadopted
  scenario reads as a draft everywhere — it can be shared, but
  no read calls it the desk's view.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from datetime import date, timedelta

from fmcg_forecast.events.models import (
    EventTransmission,
    MarketEvent,
    event_content_id,
)
from fmcg_forecast.events.pack import EventPack, load_event_pack
from fmcg_forecast.events.paths import build_event_path, path_touches
from fmcg_forecast.events.service import EventNotFoundError, EventService
from fmcg_forecast.forecast.engine import (
    DriverShift,
    EventAdjustment,
    ForecastError,
    SentimentInput,
    run_engine,
)
from fmcg_forecast.forecast.models import FORECAST_DAYS
from fmcg_forecast.forecast.service import ForecastService
from fmcg_forecast.modelport import ModelPort
from fmcg_forecast.scenarios.diff import compute_diff
from fmcg_forecast.scenarios.models import (
    AppliedShift,
    LeverApplication,
    ScenarioAdoption,
    ScenarioDiff,
    ScenarioRequest,
    ScenarioRun,
    request_content_id,
    scenario_content_id,
)
from fmcg_forecast.scenarios.pack import (
    LEVER_DRIVERS,
    ScenarioPack,
    load_scenario_pack,
)
from fmcg_forecast.scenarios.shifts import ShiftError, compute_shift
from fmcg_forecast.scenarios.verify import verify_scenario

_PLACEHOLDERS = {"", "unknown", "n/a", "na", "tbd", "none", "-", "null", "anon", "anonymous"}

_NUMERIC_LEVERS = (
    "arrivals_shift_pct",
    "stock_cover_days",
    "trade_flow_shift_pct",
    "weather_deviation",
    "sentiment_override",
)


class ScenarioError(RuntimeError):
    """Base for scenario studio refusals."""


class ScenarioValidationError(ScenarioError):
    """The request, lever set or run is malformed or inapplicable."""


class ScenarioNotFoundError(ScenarioError):
    """No scenario artefact with that id."""


class ScenarioParseError(ScenarioError):
    """The model port refused the what-if; the clause is named."""

    def __init__(self, clause: str, reason: str):
        super().__init__(f"clause {clause!r} refused: {reason}")
        self.clause = clause
        self.reason = reason


class AdoptionError(ScenarioError):
    """Base for adoption-act refusals."""


class AdoptionValidationError(AdoptionError):
    """The act itself is malformed (unnamed adopter or role)."""


class AdoptionStateError(AdoptionError):
    """The scenario is not in a state that can be adopted."""


def _require_named(value: str, field: str, error=ScenarioValidationError) -> str:
    cleaned = value.strip()
    if cleaned.lower() in _PLACEHOLDERS:
        raise error(f"{field} must name a person or role of record, not {value!r}")
    return cleaned


class ScenarioService:
    def __init__(
        self,
        store,
        model: ModelPort,
        forecasts: ForecastService,
        events: EventService,
        sentiment_provider: Callable[[str, date], SentimentInput | None] | None = None,
        pack: ScenarioPack | None = None,
        event_pack: EventPack | None = None,
    ):
        self.store = store
        self.model = model
        self.forecasts = forecasts
        self.events = events
        self.sentiment_provider = sentiment_provider
        self.pack = pack or load_scenario_pack()
        self.event_pack = event_pack or load_event_pack()

    # -- lever validation (the pack's gate, shared by both intakes) ------
    def validate_levers(self, levers: list[LeverApplication]) -> None:
        seen_drivers: dict[str, str] = {}
        seen_events: set[str] = set()
        for lever in levers:
            if lever.lever not in self.pack.levers:
                raise ScenarioValidationError(
                    f"unknown lever {lever.lever!r}; the scenario "
                    f"pack's catalogue states "
                    f"{sorted(self.pack.levers)}"
                )
            spec = self.pack.levers[lever.lever]
            if lever.lever in _NUMERIC_LEVERS:
                if lever.value is None:
                    raise ScenarioValidationError(
                        f"lever {lever.lever} carries no value"
                    )
                if not (spec.min_value <= lever.value <= spec.max_value):
                    raise ScenarioValidationError(
                        f"{lever.lever} value {lever.value:g} is "
                        f"outside the scenario pack's bound "
                        f"[{spec.min_value:g}, {spec.max_value:g}] "
                        f"({spec.unit})"
                    )
                driver = LEVER_DRIVERS[lever.lever]
                if driver in seen_drivers:
                    raise ScenarioValidationError(
                        f"the {driver} driver is moved by both "
                        f"{seen_drivers[driver]!r} and "
                        f"{lever.lever!r} — each driver moves once"
                    )
                seen_drivers[driver] = lever.lever
            elif lever.lever == "event":
                if not lever.event_id:
                    raise ScenarioValidationError(
                        "the event lever names no registry event id"
                    )
                if lever.event_id in seen_events:
                    raise ScenarioValidationError(
                        f"event {lever.event_id} is named twice"
                    )
                seen_events.add(lever.event_id)
            elif lever.lever == "event_extension":
                if not lever.event_id or lever.extra_days is None:
                    raise ScenarioValidationError(
                        "the event_extension lever needs an event id "
                        "and extra_days"
                    )
                if not (spec.min_value <= lever.extra_days <= spec.max_value):
                    raise ScenarioValidationError(
                        f"event_extension of {lever.extra_days} days "
                        f"is outside the scenario pack's bound "
                        f"[{spec.min_value:g}, {spec.max_value:g}] "
                        f"({spec.unit})"
                    )
                if lever.event_id in seen_events:
                    raise ScenarioValidationError(
                        f"event {lever.event_id} is named twice"
                    )
                seen_events.add(lever.event_id)
            elif lever.lever == "hypothetical_event":
                if lever.value is None or lever.event_class is None:
                    raise ScenarioValidationError(
                        "the hypothetical_event lever needs a peak "
                        "percent and an event class"
                    )
                if lever.event_class not in self.event_pack.classes:
                    raise ScenarioValidationError(
                        f"unknown event class {lever.event_class!r}; "
                        f"the event pack states "
                        f"{sorted(self.event_pack.classes)}"
                    )
                if not (spec.min_value <= lever.value <= spec.max_value):
                    raise ScenarioValidationError(
                        f"hypothetical_event peak {lever.value:g}% "
                        f"is outside the scenario pack's bound "
                        f"[{spec.min_value:g}, {spec.max_value:g}] "
                        f"({spec.unit})"
                    )
                duration = lever.duration_days
                if duration is None or not (
                    1 <= duration <= self.pack.hypothetical_duration_max_days
                ):
                    raise ScenarioValidationError(
                        f"a hypothetical event's window of "
                        f"{duration} days is outside the scenario "
                        f"pack's bound "
                        f"[1, {self.pack.hypothetical_duration_max_days}] days"
                    )
                offset = lever.start_offset_days or 0
                if not (0 <= offset <= self.pack.hypothetical_start_offset_max_days):
                    raise ScenarioValidationError(
                        f"a hypothetical event's start offset of "
                        f"{offset} days is outside the scenario "
                        f"pack's bound "
                        f"[0, {self.pack.hypothetical_start_offset_max_days}] days"
                    )
                decay = lever.decay_days
                if decay is not None and decay < 1:
                    raise ScenarioValidationError("decay_days must be at least 1")

    # -- intake -----------------------------------------------------------
    def parse_request(
        self,
        commodity: str,
        market: str,
        text: str,
        base_forecast_id: str | None = None,
    ) -> ScenarioRequest:
        """Type a what-if; get back the request artefact (or a refusal).

        The resolution context for event references is the base
        forecast's applied events when a base is named, else the
        commodity's registry.
        """
        if base_forecast_id is not None:
            base = self.forecasts.get_forecast(base_forecast_id)
            if (base.commodity, base.market) != (commodity, market):
                raise ScenarioValidationError(
                    f"base forecast {base_forecast_id} is for "
                    f"{base.commodity}/{base.market}, not "
                    f"{commodity}/{market}"
                )
            context = []
            for event_id in base.method.events_applied:
                try:
                    event = self.events.get_event(event_id)
                except EventNotFoundError:
                    # A base run made with explicit adjustments can
                    # carry an event the registry does not hold;
                    # keyword resolution simply cannot see it.
                    continue
                context.append(
                    {"event_id": event.event_id, "event_class": event.event_class}
                )
        else:
            context = [
                {"event_id": e.event_id, "event_class": e.event_class}
                for e in self.events.list_events(commodity)
            ]
        result = self.model.parse_scenario(text=text, events=context)
        if result.get("status") != "parsed":
            raise ScenarioParseError(
                str(result.get("clause", "")),
                str(result.get("reason", "the parse was refused")),
            )
        levers = [LeverApplication(**raw) for raw in result["levers"]]
        self.validate_levers(levers)
        request = ScenarioRequest(
            request_id="SCRQ-pending",
            commodity=commodity,
            market=market,
            source_text=text,
            intake="text",
            model_profile=self.model.profile_name,
            levers=levers,
            pack_version=self.pack.version,
        )
        request.request_id = request_content_id(request)
        existing = self.store.get_scenario_request(request.request_id)
        if existing is not None:
            return existing
        self.store.insert_scenario_request(request)
        return request

    def create_request(
        self,
        commodity: str,
        market: str,
        levers: list[LeverApplication],
    ) -> ScenarioRequest:
        """Post a structured lever set directly (no text parse)."""
        self.validate_levers(levers)
        request = ScenarioRequest(
            request_id="SCRQ-pending",
            commodity=commodity,
            market=market,
            source_text=None,
            intake="structured",
            model_profile=self.model.profile_name,
            levers=levers,
            pack_version=self.pack.version,
        )
        request.request_id = request_content_id(request)
        existing = self.store.get_scenario_request(request.request_id)
        if existing is not None:
            return existing
        self.store.insert_scenario_request(request)
        return request

    def get_request(self, request_id: str) -> ScenarioRequest:
        request = self.store.get_scenario_request(request_id)
        if request is None:
            raise ScenarioNotFoundError(f"unknown scenario request {request_id}")
        return request

    def list_requests(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[ScenarioRequest]:
        return self.store.list_scenario_requests(commodity, market)

    # -- runs ---------------------------------------------------------------
    def _registry_event(self, event_id: str) -> MarketEvent:
        try:
            return self.events.get_event(event_id)
        except EventNotFoundError as exc:
            raise ScenarioValidationError(
                f"lever names event {event_id}, which is not in "
                "the registry"
            ) from exc

    def _extension_event(
        self,
        source: MarketEvent,
        lever: LeverApplication,
        author: str,
        created_on: date,
    ) -> MarketEvent:
        if source.window_end is None:
            raise ScenarioValidationError(
                f"event {source.event_id} is open-ended — it "
                "already stays in force, so there is no window "
                "to prolong"
            )
        new_end = source.window_end + timedelta(days=lever.extra_days or 0)
        extended = source.model_copy(
            update={
                "window_end": new_end,
                "origin": "scenario",
                "declared_by": author,
                "declared_on": created_on,
                "description": (
                    f"{source.description} — scenario extension: "
                    f"the window is prolonged by "
                    f"{lever.extra_days} days, from "
                    f"{source.window_end.isoformat()} to "
                    f"{new_end.isoformat()}, on the source event's "
                    "stated transmission"
                ),
                "source_record_id": source.event_id,
            }
        )
        extended.event_id = event_content_id(extended)
        return extended

    def _hypothetical_event(
        self,
        lever: LeverApplication,
        commodity: str,
        as_of: date,
        author: str,
        created_on: date,
    ) -> MarketEvent:
        peak = round(math.log(1.0 + (lever.value or 0.0) / 100.0), 6)
        if peak == 0.0:
            raise ScenarioValidationError(
                "a hypothetical event with a zero peak moves "
                "nothing — it is not an event"
            )
        window_start = as_of + timedelta(days=(lever.start_offset_days or 0) + 1)
        window_end = window_start + timedelta(days=(lever.duration_days or 1) - 1)
        event = MarketEvent(
            event_id="EVT-pending",
            event_class=lever.event_class,  # type: ignore[arg-type]
            commodity=commodity,
            window_start=window_start,
            window_end=window_end,
            direction=1 if peak > 0 else -1,
            transmission=EventTransmission(
                channel="modal_price",
                driver_effect=None,
                peak_log_price_effect=peak,
                basis="desk_estimate",
                basis_detail=(
                    f"Scenario hypothesis stated by {author}: a "
                    f"{lever.event_class} moving prices by "
                    f"{lever.value:+g}% at its peak "
                    f"(ln(1 + p/100) = {peak:+.4f} log), over "
                    f"{lever.duration_days} days from "
                    f"{window_start.isoformat()}"
                ),
            ),
            decay_days=lever.decay_days or self.pack.hypothetical_decay_days,
            description=(
                f"Hypothetical {lever.event_class} posed by the "
                "scenario — not a declared registry event"
            ),
            declared_by=author,
            declared_on=created_on,
            pack_version=self.event_pack.version,
            origin="scenario",
            source_record_id=None,
        )
        event.event_id = event_content_id(event)
        return event

    def run_scenario(
        self,
        request_id: str,
        base_forecast_id: str,
        author: str,
        created_on: date,
    ) -> ScenarioRun:
        request = self.get_request(request_id)
        base = self.forecasts.get_forecast(base_forecast_id)
        if (request.commodity, request.market) != (base.commodity, base.market):
            raise ScenarioValidationError(
                f"request {request_id} is for "
                f"{request.commodity}/{request.market}; the base "
                f"forecast is {base.commodity}/{base.market} — a "
                "scenario forks a forecast of its own series"
            )
        author = _require_named(author, "author")
        self.validate_levers(request.levers)
        manifest = self.store.get_manifest()
        if manifest is None:
            raise ScenarioValidationError(
                "dataset not loaded; run the ingest workflow first"
            )

        base_lines = {line.driver: line for line in base.lines}
        shifts: list[AppliedShift] = []
        engine_shifts: list[DriverShift] = []
        sentiment_override: float | None = None
        scenario_events: list[MarketEvent] = []
        # Event adjustments, in telescoping order: the base's own
        # events first (an extension replaces its source in
        # place), then the scenario's added events in lever order.
        extended_sources: dict[str, MarketEvent] = {}
        appended_events: list[MarketEvent] = []

        for lever in request.levers:
            if lever.lever in _NUMERIC_LEVERS and lever.lever != "sentiment_override":
                driver = LEVER_DRIVERS[lever.lever]
                if driver not in base_lines:
                    raise ScenarioValidationError(
                        f"lever {lever.lever} moves the {driver} "
                        f"driver, but {base.commodity} does not "
                        f"report it — the base forecast carries no "
                        f"{driver} line (a named gap, Law 7), and a "
                        "scenario cannot move a line that does not "
                        "exist"
                    )
                try:
                    shift = compute_shift(
                        self.store,
                        base.commodity,
                        base.market,
                        base.as_of,
                        lever,
                        self.pack,
                    )
                except ShiftError as exc:
                    raise ScenarioValidationError(str(exc)) from exc
                shifts.append(shift)
                engine_shifts.append(
                    DriverShift(
                        driver=shift.driver,
                        mode=shift.mode,  # type: ignore[arg-type]
                        value=shift.value,
                        clip_min=shift.clip_min,
                        clip_max=shift.clip_max,
                    )
                )
            elif lever.lever == "sentiment_override":
                line = base_lines.get("sentiment")
                state = (
                    line.input_summary.get("state") if line is not None else None
                )
                if line is None or state != "estimated":
                    raise ScenarioValidationError(
                        "the sentiment_override lever needs an "
                        "estimated sentiment line on the base "
                        f"forecast; this base's sentiment state is "
                        f"{state or 'absent'} — a thin corpus stays "
                        "not-estimable under a scenario too"
                    )
                shifts.append(
                    compute_shift(
                        self.store,
                        base.commodity,
                        base.market,
                        base.as_of,
                        lever,
                        self.pack,
                    )
                )
                sentiment_override = lever.value
            elif lever.lever == "event":
                event = self._registry_event(lever.event_id or "")
                if event.commodity != base.commodity:
                    raise ScenarioValidationError(
                        f"event {event.event_id} is scoped to "
                        f"{event.commodity}, not {base.commodity}"
                    )
                if event.event_id in base.method.events_applied:
                    raise ScenarioValidationError(
                        f"event {event.event_id} is already in the "
                        "base forecast — prolong it with the "
                        "event_extension lever instead of adding "
                        "it twice"
                    )
                appended_events.append(event)
            elif lever.lever == "event_extension":
                source = self._registry_event(lever.event_id or "")
                if source.event_id not in base.method.events_applied:
                    raise ScenarioValidationError(
                        f"event {source.event_id} is not in the "
                        "base forecast, so there is nothing to "
                        "prolong — add it with the event lever "
                        "instead"
                    )
                extended = self._extension_event(source, lever, author, created_on)
                extended_sources[source.event_id] = extended
                scenario_events.append(extended)
            elif lever.lever == "hypothetical_event":
                event = self._hypothetical_event(
                    lever, base.commodity, base.as_of, author, created_on
                )
                scenario_events.append(event)
                appended_events.append(event)

        # The base's event adjustments, re-derived from the
        # insert-only registry in the base's own order (the path
        # rule is a pure function of the declaration, so this
        # reproduces the base run's slot exactly). An id the
        # provider no longer returns — a base run made with
        # explicit adjustments — falls back to the path recorded
        # on the base artefact itself.
        first_day = base.as_of + timedelta(days=1)
        provider = {
            adj.event_id: adj
            for adj in self.events.forecast_adjustments(base.commodity, base.as_of)
        }
        base_events_line = base_lines.get("events")
        recorded_paths = (
            (base_events_line.input_summary.get("per_event") or {})
            if base_events_line is not None
            else {}
        )
        adjustments: list[EventAdjustment] = []
        for event_id in base.method.events_applied:
            if event_id in extended_sources:
                extended = extended_sources[event_id]
                adjustments.append(
                    EventAdjustment(
                        event_id=extended.event_id,
                        path=build_event_path(
                            extended, first_day, FORECAST_DAYS, self.event_pack
                        ),
                        interval_widening=self.event_pack.interval_widening_factor,
                    )
                )
            elif event_id in provider:
                adjustments.append(provider[event_id])
            elif event_id in recorded_paths:
                entry = recorded_paths[event_id]
                adjustments.append(
                    EventAdjustment(
                        event_id=event_id,
                        path=[float(v) for v in entry["input_path"]],
                        interval_widening=float(
                            entry.get(
                                "interval_widening",
                                self.event_pack.interval_widening_factor,
                            )
                        ),
                    )
                )
            else:
                raise ScenarioValidationError(
                    f"the base forecast applied event {event_id}, "
                    "which is neither in the registry nor recorded "
                    "on the base artefact — its path cannot be "
                    "reproduced, so the fork cannot be pinned"
                )
        for event in appended_events:
            path = build_event_path(event, first_day, FORECAST_DAYS, self.event_pack)
            if not path_touches(path):
                raise ScenarioValidationError(
                    f"event {event.event_id} does not touch the "
                    "fork's horizon — adding it would change nothing"
                )
            adjustments.append(
                EventAdjustment(
                    event_id=event.event_id,
                    path=path,
                    interval_widening=self.event_pack.interval_widening_factor,
                )
            )

        sentiment_input = None
        if "sentiment" in base_lines and self.sentiment_provider is not None:
            sentiment_input = self.sentiment_provider(base.commodity, base.as_of)

        try:
            fork = run_engine(
                self.store,
                manifest,
                base.commodity,
                base.market,
                base.as_of,
                event_adjustments=adjustments,
                sentiment_input=sentiment_input,
                driver_shifts=engine_shifts,
                sentiment_start_override=sentiment_override,
            )
        except ForecastError as exc:
            raise ScenarioValidationError(str(exc)) from exc
        # The fork carries its accuracy like any desk run: the
        # ledger's current snapshot for the series, attached by
        # the forecast service's own discipline.
        fork = self.forecasts._attach_accuracy(fork)

        run = ScenarioRun(
            scenario_id="SCN-pending",
            request_id=request.request_id,
            base_forecast_id=base.forecast_id,
            fork_forecast_id=fork.forecast_id,
            commodity=base.commodity,
            market=base.market,
            as_of=base.as_of,
            author=author,
            created_on=created_on,
            pack_version=self.pack.version,
            status="draft",
            shifts=shifts,
            scenario_events=scenario_events,
            fork=fork,
        )
        run.scenario_id = scenario_content_id(run)
        existing = self.store.get_scenario(run.scenario_id)
        if existing is not None:
            return existing
        self.store.insert_scenario(run)
        return run

    # -- reads ---------------------------------------------------------------
    def get_scenario(self, scenario_id: str) -> ScenarioRun:
        run = self.store.get_scenario(scenario_id)
        if run is None:
            raise ScenarioNotFoundError(f"unknown scenario {scenario_id}")
        return run

    def list_scenarios(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[ScenarioRun]:
        return self.store.list_scenarios(commodity, market)

    def diff(self, scenario_id: str) -> ScenarioDiff:
        run = self.get_scenario(scenario_id)
        base = self.forecasts.get_forecast(run.base_forecast_id)
        diff, problems = compute_diff(scenario_id, base, run.fork)
        if problems:
            raise ScenarioValidationError(
                "the stored fork does not diff cleanly against "
                "its base: " + "; ".join(problems)
            )
        return diff

    def verify_stored(self, scenario_id: str) -> list[str]:
        run = self.get_scenario(scenario_id)
        request = self.get_request(run.request_id)
        base = self.forecasts.get_forecast(run.base_forecast_id)
        return verify_scenario(
            self.store, run, request, base, self.pack, self.event_pack
        )

    _VIEW_KINDS = {
        "draft": "scenario_draft",
        "adopted": "adopted_scenario",
        "superseded": "superseded_scenario",
    }

    def scenario_view(self, scenario_id: str) -> dict:
        """One scenario, labelled for what it is on every read."""
        run = self.get_scenario(scenario_id)
        base = self.forecasts.get_forecast(run.base_forecast_id)
        adoption = self.store.get_scenario_adoption(scenario_id)
        diff, _ = compute_diff(scenario_id, base, run.fork)
        view = run.model_dump(mode="json")
        view["view_kind"] = self._VIEW_KINDS[run.status]
        view["base"] = {
            "forecast_id": base.forecast_id,
            "status": base.status,
            "view_kind": "official_forecast" if base.status == "official" else "draft_forecast",
        }
        view["adoption"] = (
            adoption.model_dump(mode="json") if adoption is not None else None
        )
        view["diff_summary"] = {
            "driver_totals": diff.driver_totals,
            "events_total": diff.events_total,
            "p50_total": diff.p50_total,
            "at_horizons": diff.at_horizons,
        }
        return view

    # -- the adoption gate ------------------------------------------------------
    def adopt(
        self,
        scenario_id: str,
        adopter: str,
        role: str,
        decided_on: date,
    ) -> ScenarioAdoption:
        run = self.get_scenario(scenario_id)
        if run.status == "adopted":
            raise AdoptionStateError(
                f"scenario {scenario_id} is already the desk's "
                "adopted view; adopting it again would rewrite the "
                "record of the act"
            )
        if run.status == "superseded":
            raise AdoptionStateError(
                f"scenario {scenario_id} was superseded by a later "
                "adoption; a superseded scenario stays superseded — "
                "run a fresh fork to revisit the question"
            )
        adopter = _require_named(adopter, "adopter", AdoptionValidationError)
        role = _require_named(role, "role", AdoptionValidationError)
        current = next(
            (
                s
                for s in self.store.list_scenarios(run.commodity, run.market)
                if s.status == "adopted"
            ),
            None,
        )
        adoption_id = "ADPT-" + hashlib.sha256(
            f"{scenario_id}|{adopter}|{decided_on.isoformat()}".encode()
        ).hexdigest()[:12]
        adoption = ScenarioAdoption(
            adoption_id=adoption_id,
            scenario_id=scenario_id,
            adopter=adopter,
            role=role,
            decided_on=decided_on,
            supersedes_scenario_id=current.scenario_id if current else None,
        )
        self.store.insert_scenario_adoption(adoption)
        if current is not None:
            self.store.set_scenario_status(current.scenario_id, "superseded")
        self.store.set_scenario_status(scenario_id, "adopted")
        return adoption

    def get_adoption(self, scenario_id: str) -> ScenarioAdoption | None:
        self.get_scenario(scenario_id)
        return self.store.get_scenario_adoption(scenario_id)

    def adopted_view(self, commodity: str, market: str) -> dict:
        """The desk's adopted view for a series, labelled as such.

        ``state`` is ``adopted`` with the scenario view, or
        ``none`` — no scenario has been adopted for the series,
        and no draft is dressed up as one.
        """
        adopted = next(
            (
                s
                for s in self.store.list_scenarios(commodity, market)
                if s.status == "adopted"
            ),
            None,
        )
        if adopted is None:
            return {
                "state": "none",
                "commodity": commodity,
                "market": market,
                "note": "no scenario has been adopted for this "
                "series — drafts exist only as scenario_draft "
                "reads, never as the desk's view",
                "scenario": None,
            }
        return {
            "state": "adopted",
            "commodity": commodity,
            "market": market,
            "scenario": self.scenario_view(adopted.scenario_id),
        }
