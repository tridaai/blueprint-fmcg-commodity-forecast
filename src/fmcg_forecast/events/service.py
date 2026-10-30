"""The event service: declare, seed, measure, feed the engine.

One workflow every surface shares:

- ``register_event`` is the analyst act. It validates the
  declaration against the pack (class, channel, basis vocabulary,
  window order, a non-zero claimed peak, a named declarer —
  placeholder names are refused, as at the approval gate) and
  stores it under its content address. Re-declaring the identical
  event returns the record; declarations are never edited.
- ``seed_historical`` registers the dataset's planted shocks from
  the generator manifest — the tariff, the export ban, the chili
  drought — as historical entries whose claimed transmissions the
  verifier then checks against measured history.
- ``forecast_adjustments`` is the forecast engine's provider: it
  turns the registry into EventAdjustments (the pack's path rule,
  the pack's interval widening) for the events whose effect
  touches a run's forecast window. Events outside the window
  contribute nothing and are not attached. When the console's
  triage hook is wired (R13), events triage has retired or
  superseded are excluded as well — a withdrawn declaration
  feeds no new run, and an amended event's replacement is the
  declaration the registry feeds.
- ``verify_event`` runs the measurement layer: the claimed
  transmission against the seasonally-matched measured effect.
  An event whose claim disagrees is flagged ``unverified`` on its
  face — the flag is part of every read, computed from history,
  never stored away where it could be edited off.
"""

from __future__ import annotations

from datetime import date, timedelta

from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.events.measure import event_impact, measure_event_effect
from fmcg_forecast.events.models import (
    EventImpact,
    EventTransmission,
    MarketEvent,
    TransmissionVerification,
    event_content_id,
)
from fmcg_forecast.events.pack import EventPack, load_event_pack
from fmcg_forecast.events.paths import build_event_path, path_touches
from fmcg_forecast.events.verify import verify_market_event
from fmcg_forecast.forecast.engine import EventAdjustment
from fmcg_forecast.forecast.models import FORECAST_DAYS
from fmcg_forecast.models import Manifest

_PLACEHOLDERS = {"", "unknown", "n/a", "na", "tbd", "none", "-", "null", "anon", "anonymous"}

# The dataset generator's stated weather channel: log price moves
# -0.06 per weather-index point (generator.py). The drought's
# claimed price effect is its planted index deviation through
# that channel — stated on the entry's basis_detail.
_GENERATOR_WEATHER_COEF = -0.06


class EventError(RuntimeError):
    """Base for event registry refusals."""


class EventValidationError(EventError):
    """The declaration itself is malformed."""


class EventNotFoundError(EventError):
    """No market event with that id."""


def _require_named(value: str, field: str) -> str:
    cleaned = value.strip()
    if cleaned.lower() in _PLACEHOLDERS:
        raise EventValidationError(
            f"{field} must name a person or record of record, not {value!r}"
        )
    return cleaned


class EventService:
    def __init__(self, store, pack: EventPack | None = None):
        self.store = store
        self.pack = pack or load_event_pack()
        # Wired by the API composition (R13): a callable returning
        # the event ids triage has retired or superseded, excluded
        # from new runs. Unwired, the registry feeds every declared
        # event exactly as before.
        self.triage_exclusions = None

    # -- the analyst act ------------------------------------------------
    def register_event(
        self,
        *,
        event_class: str,
        commodity: str,
        window_start: date,
        window_end: date | None,
        channel: str,
        peak_log_price_effect: float,
        basis: str,
        basis_detail: str,
        decay_days: int,
        description: str,
        declared_by: str,
        declared_on: date,
        driver_effect: float | None = None,
        origin: str = "declared",
        source_record_id: str | None = None,
    ) -> MarketEvent:
        if event_class not in self.pack.classes:
            raise EventValidationError(
                f"unknown event class {event_class!r}; the pack states "
                f"{sorted(self.pack.classes)}"
            )
        if commodity not in BY_NAME:
            raise EventValidationError(f"unknown commodity {commodity!r}")
        allowed = self.pack.classes[event_class]
        if channel not in allowed:
            raise EventValidationError(
                f"channel {channel!r} is not one of the pack's channels "
                f"for {event_class}: {allowed}"
            )
        if basis not in self.pack.bases:
            raise EventValidationError(
                f"basis {basis!r} is not in the pack's vocabulary: "
                f"{self.pack.bases}"
            )
        if not basis_detail.strip():
            raise EventValidationError(
                "basis_detail must state the basis concretely — the "
                "announced measure and its size, the measured analogue, "
                "or the judgement"
            )
        if peak_log_price_effect == 0.0:
            raise EventValidationError(
                "peak_log_price_effect must be non-zero — an event that "
                "moves nothing is not an event"
            )
        if window_end is not None and window_end < window_start:
            raise EventValidationError("window_end precedes window_start")
        if decay_days < 1:
            raise EventValidationError("decay_days must be at least 1")
        if not description.strip():
            raise EventValidationError("description must state what happened")
        declared_by = _require_named(declared_by, "declared_by")
        event = MarketEvent(
            event_id="EVT-pending",
            event_class=event_class,  # type: ignore[arg-type]
            commodity=commodity,
            window_start=window_start,
            window_end=window_end,
            direction=1 if peak_log_price_effect > 0 else -1,
            transmission=EventTransmission(
                channel=channel,
                driver_effect=driver_effect,
                peak_log_price_effect=peak_log_price_effect,
                basis=basis,  # type: ignore[arg-type]
                basis_detail=basis_detail.strip(),
            ),
            decay_days=decay_days,
            description=description.strip(),
            declared_by=declared_by,
            declared_on=declared_on,
            pack_version=self.pack.version,
            origin=origin,  # type: ignore[arg-type]
            source_record_id=source_record_id,
        )
        event.event_id = event_content_id(event)
        existing = self.store.get_market_event(event.event_id)
        if existing is not None:
            return existing
        self.store.insert_market_event(event)
        return event

    # -- historical seeding ------------------------------------------------
    def seed_historical(self, manifest: Manifest) -> dict:
        """Register the manifest's planted shocks as historical events.

        Idempotent: entries already on record are counted, not
        rewritten. The claimed magnitudes are the manifest's own
        planted values — the verifier's job is to check them
        against measured history, not to fit them to it.
        """
        seeded: list[str] = []
        on_record: list[str] = []
        declared_by = "dataset manifest (planted)"

        def record(event: MarketEvent) -> None:
            if self.store.get_market_event(event.event_id) is not None:
                on_record.append(event.event_id)
            else:
                self.store.insert_market_event(event)
                seeded.append(event.event_id)

        for planted in manifest.events:
            if planted.kind == "tariff_shock":
                event_class, channel, driver_effect = (
                    "tariff_change",
                    "import_flow",
                    None,
                )
                basis_detail = (
                    "Peak magnitude as planted in the dataset manifest "
                    "for the oilseed import tariff; the transmission "
                    "verifier checks it against the seasonally-matched "
                    "measurement in observed history"
                )
            else:  # export_ban
                event_class, channel, driver_effect = (
                    "export_restriction",
                    "export_flow",
                    0.05,
                )
                basis_detail = (
                    "Peak magnitude as planted in the dataset manifest "
                    "for the basmati export ban (export flow falls to "
                    "5% of normal inside the window); the transmission "
                    "verifier checks it against the seasonally-matched "
                    "measurement in observed history"
                )
            event = MarketEvent(
                event_id="EVT-pending",
                event_class=event_class,  # type: ignore[arg-type]
                commodity=planted.commodity,
                window_start=planted.start_date,
                window_end=planted.end_date,
                direction=1 if planted.magnitude > 0 else -1,
                transmission=EventTransmission(
                    channel=channel,
                    driver_effect=driver_effect,
                    peak_log_price_effect=planted.magnitude,
                    basis="measured_analogue",
                    basis_detail=basis_detail,
                ),
                decay_days=planted.decay_days,
                description=planted.description,
                declared_by=declared_by,
                declared_on=planted.start_date,
                pack_version=self.pack.version,
                origin="historical",
                source_record_id=planted.event_id,
            )
            event.event_id = event_content_id(event)
            record(event)

        for anomaly in manifest.weather_anomalies:
            # The generator's price term is coef x weather deviation:
            # (-0.06) x (-0.6) = +0.036 — a drought firms prices.
            peak = round(_GENERATOR_WEATHER_COEF * anomaly.depth, 4)
            event = MarketEvent(
                event_id="EVT-pending",
                event_class="weather_shock",
                commodity=anomaly.commodity,
                window_start=anomaly.start_date,
                window_end=anomaly.end_date,
                direction=1 if peak > 0 else -1,
                transmission=EventTransmission(
                    channel="weather_index",
                    driver_effect=anomaly.depth,
                    peak_log_price_effect=peak,
                    basis="measured_analogue",
                    basis_detail=(
                        f"Weather-index deviation of {anomaly.depth:+.1f} "
                        "planted in the window, carried through the "
                        "dataset's weather channel (-0.06 log price per "
                        f"index point) gives the {peak:+.3f} peak; the "
                        "transmission verifier checks it against the "
                        "seasonally-matched measurement in observed history"
                    ),
                ),
                decay_days=10,
                description=(
                    "Drought window in the chili belt; the weather "
                    "index deviates for the season and prices firm "
                    "through the weather channel"
                ),
                declared_by=declared_by,
                declared_on=anomaly.start_date,
                pack_version=self.pack.version,
                origin="historical",
                source_record_id=(
                    f"ANOMALY-{anomaly.commodity.upper()}-"
                    f"{anomaly.start_date.year}"
                ),
            )
            event.event_id = event_content_id(event)
            record(event)

        return {
            "pack_version": self.pack.version,
            "seeded": seeded,
            "already_on_record": on_record,
            "total_on_record": len(self.store.list_market_events()),
        }

    # -- reads ---------------------------------------------------------------
    def get_event(self, event_id: str) -> MarketEvent:
        event = self.store.get_market_event(event_id)
        if event is None:
            raise EventNotFoundError(f"unknown market event {event_id}")
        return event

    def list_events(self, commodity: str | None = None) -> list[MarketEvent]:
        return self.store.list_market_events(commodity)

    def event_view(self, event_id: str) -> dict:
        """One event with its transmission verdict on its face."""
        event = self.get_event(event_id)
        view = event.model_dump(mode="json")
        view["verification"] = self.verify_event(event_id).model_dump(mode="json")
        return view

    # -- measurement -----------------------------------------------------------
    def verify_event(self, event_id: str) -> TransmissionVerification:
        return measure_event_effect(self.store, self.get_event(event_id), self.pack)

    def verify_registry(self) -> dict:
        """Artefact integrity across every stored declaration."""
        problems: list[str] = []
        for event in self.store.list_market_events():
            problems.extend(verify_market_event(event, self.pack))
        return {"problems": problems}

    def impact(self, event_id: str, market: str | None = None) -> EventImpact:
        event = self.get_event(event_id)
        spec = BY_NAME[event.commodity]
        chosen = market or spec.markets[0].market
        if chosen not in {m.market for m in spec.markets}:
            raise EventValidationError(
                f"{chosen!r} is not a market of {event.commodity}"
            )
        return event_impact(self.store, event, chosen, self.pack)

    # -- the forecast engine's provider -----------------------------------------
    def forecast_adjustments(
        self, commodity: str, as_of: date
    ) -> list[EventAdjustment]:
        """Adjustments for the events touching (as_of, as_of + 90d].

        Deterministic order (window start, then id) — the engine
        telescopes events in the order given, and the order is
        part of the run's record.
        """
        first_day = as_of + timedelta(days=1)
        excluded = (
            self.triage_exclusions() if self.triage_exclusions is not None else set()
        )
        adjustments: list[EventAdjustment] = []
        for event in self.store.list_market_events(commodity):
            if event.event_id in excluded:
                continue
            path = build_event_path(event, first_day, FORECAST_DAYS, self.pack)
            if path_touches(path):
                adjustments.append(
                    EventAdjustment(
                        event_id=event.event_id,
                        path=path,
                        interval_widening=self.pack.interval_widening_factor,
                    )
                )
        return adjustments
