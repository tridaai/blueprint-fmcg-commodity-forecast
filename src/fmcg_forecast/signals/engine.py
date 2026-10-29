"""The signal engine — the pack's decision table, performed.

Pure computation over the pinned forecast artefact and the store:
spot is the last observed modal price on or before the forecast's
``as_of``; the path figures are the forecast's own horizon
summaries; the accuracy state is the forecast's pinned attachment,
never re-derived; the events are the registry's declarations for
the commodity whose windows (plus their stated decay) reach into
the horizon. Nothing here narrates — the reasoning lines are
formatted from the numbers, thresholds and verdicts themselves,
so the verifier's re-performance reproduces them exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from fmcg_forecast.events.models import MarketEvent
from fmcg_forecast.forecast.models import Forecast
from fmcg_forecast.signals.models import BuySignal, SignalEventRef, signal_content_id
from fmcg_forecast.signals.pack import SCOPE_NOTE, SignalPack
from fmcg_forecast.store import Store


class SignalError(ValueError):
    """A signal cannot be computed from the pinned inputs."""


@dataclass
class SignalInputs:
    """Everything the decision table reads, gathered once."""

    spot_inr: float
    spot_date: date
    p10_inr: float
    p50_inr: float
    p90_inr: float
    drift_pct: float
    band_width_pct: float
    accuracy_state: str
    accuracy_record_ids: list[str]
    degraded_horizons: list[int]
    active_events: list[SignalEventRef] = field(default_factory=list)


def _event_ref(
    event: MarketEvent, as_of: date, horizon_end: date
) -> SignalEventRef | None:
    """The event's overlap with the horizon, or None if it misses."""
    if event.window_start > horizon_end:
        return None
    if event.window_end is None:
        reach_end = horizon_end
    else:
        reach_end = event.window_end + timedelta(days=event.decay_days)
    if reach_end < as_of + timedelta(days=1):
        return None
    return SignalEventRef(
        event_id=event.event_id,
        event_class=event.event_class,
        window_start=event.window_start,
        window_end=event.window_end,
        overlap_end=min(reach_end, horizon_end),
        claimed_peak_log_effect=event.transmission.peak_log_price_effect,
    )


def gather_inputs(
    store: Store, forecast: Forecast, pack: SignalPack
) -> SignalInputs:
    """Read every input the decision table needs, from the store."""
    rows = store.series(
        forecast.commodity, forecast.market, "modal_price", end=forecast.as_of
    )
    if not rows:
        raise SignalError(
            f"no modal_price observations for {forecast.commodity} at "
            f"{forecast.market} on or before {forecast.as_of} — a "
            "signal needs a spot price to judge the path against"
        )
    spot = rows[-1]
    summary = next(
        (s for s in forecast.horizons_summary if s.horizon_days == pack.horizon_days),
        None,
    )
    if summary is None:
        raise SignalError(
            f"forecast {forecast.forecast_id} carries no "
            f"{pack.horizon_days}-day horizon summary — the signal "
            "pack judges at that horizon"
        )
    drift_pct = round((summary.p50 - spot.value) / spot.value * 100, 4)
    band_width_pct = round((summary.p90 - summary.p10) / summary.p50 * 100, 4)

    attachment = forecast.accuracy
    if attachment is None:
        accuracy_state = "unmeasured"
        record_ids: list[str] = []
        degraded_horizons: list[int] = []
    else:
        accuracy_state = attachment.state
        record_ids = [
            s.record_id for s in attachment.per_horizon if s.record_id is not None
        ]
        degraded_horizons = [
            s.horizon_days for s in attachment.per_horizon if s.state == "degraded"
        ]

    horizon_end = forecast.as_of + timedelta(days=pack.horizon_days)
    active = []
    for event in store.list_market_events(forecast.commodity):
        ref = _event_ref(event, forecast.as_of, horizon_end)
        if ref is not None:
            active.append(ref)
    active.sort(key=lambda r: (r.window_start, r.event_id))

    return SignalInputs(
        spot_inr=spot.value,
        spot_date=spot.obs_date,
        p10_inr=summary.p10,
        p50_inr=summary.p50,
        p90_inr=summary.p90,
        drift_pct=drift_pct,
        band_width_pct=band_width_pct,
        accuracy_state=accuracy_state,
        accuracy_record_ids=record_ids,
        degraded_horizons=degraded_horizons,
        active_events=active,
    )


def decide(inputs: SignalInputs, pack: SignalPack) -> tuple[str, str, list[str], list[str]]:
    """The pack's table, in order. Returns (base, value, caps, reasoning)."""
    reasoning: list[str] = []
    reasoning.append(
        f"path: {pack.horizon_days}-day P50 INR {inputs.p50_inr:,.2f} "
        f"against spot INR {inputs.spot_inr:,.2f} "
        f"({inputs.spot_date.isoformat()}) — drift "
        f"{inputs.drift_pct:+.2f}% (pack rise bar "
        f"{pack.rise_threshold_pct:+.2f}%, fall bar "
        f"{pack.fall_threshold_pct:+.2f}%)"
    )
    reasoning.append(
        f"band: {pack.horizon_days}-day interval INR "
        f"{inputs.p10_inr:,.2f}..{inputs.p90_inr:,.2f} is "
        f"{inputs.band_width_pct:.2f}% of P50 (pack wide-band bar "
        f"{pack.wide_band_threshold_pct:.2f}%)"
    )
    if inputs.accuracy_state == "degraded":
        reasoning.append(
            f"accuracy: degraded at horizons {inputs.degraded_horizons} "
            f"(ledger records {inputs.accuracy_record_ids}) — the pack "
            "caps a strong buy for this series"
        )
    elif inputs.accuracy_state == "unmeasured":
        reasoning.append(
            "accuracy: unmeasured — no backtest record stands behind "
            "this series, and the pack caps a strong buy until one does"
        )
    else:
        reasoning.append(
            f"accuracy: measured (ledger records "
            f"{inputs.accuracy_record_ids}) — no cap applies"
        )
    for ref in inputs.active_events:
        reasoning.append(
            f"event window: {ref.event_id} ({ref.event_class}) declared "
            f"{ref.window_start.isoformat()}.."
            f"{ref.window_end.isoformat() if ref.window_end else 'open'}, "
            f"decay reaching {ref.overlap_end.isoformat()}, overlaps the "
            f"horizon; claimed peak {ref.claimed_peak_log_effect:+.3f} "
            "log — named on the signal"
        )

    drift = inputs.drift_pct
    band = inputs.band_width_pct
    upward = next(
        (r for r in inputs.active_events if r.claimed_peak_log_effect > 0), None
    )
    if drift >= pack.rise_threshold_pct and band < pack.wide_band_threshold_pct:
        base = "buy_now"
        reasoning.append(
            "base call buy_now: the path clears the rise bar and the "
            "band is under the wide-band bar"
        )
    elif drift >= pack.rise_threshold_pct:
        base = "phased"
        reasoning.append(
            "base call phased: the path clears the rise bar but the "
            "band is at or over the wide-band bar — one commitment "
            "is too exposed, buy in tranches"
        )
    elif drift <= pack.fall_threshold_pct:
        base = "wait"
        reasoning.append(
            "base call wait: the path is at or under the fall bar — "
            "buy later, not now"
        )
    elif upward is not None:
        base = "phased"
        reasoning.append(
            f"base call phased: declared event {upward.event_id} "
            "claims a positive peak inside the horizon — phase in "
            "ahead of it rather than chase it"
        )
    elif band >= pack.wide_band_threshold_pct:
        base = "phased"
        reasoning.append(
            "base call phased: a flat path under a band at or over "
            "the wide-band bar — accumulate in tranches, not one "
            "commitment"
        )
    else:
        base = "wait"
        reasoning.append(
            "base call wait: a flat path in a narrow band gives no "
            "reason to buy ahead"
        )

    value = base
    caps: list[str] = []
    if value == "buy_now" and inputs.accuracy_state == "degraded":
        value = pack.degraded_cap
        caps.append("degraded_accuracy")
        reasoning.append(
            f"cap applied: degraded_accuracy — buy_now reduced to "
            f"{pack.degraded_cap}; a degraded series never produces "
            "a strong buy"
        )
    if value == "buy_now" and inputs.accuracy_state == "unmeasured":
        value = pack.unmeasured_cap
        caps.append("unmeasured_accuracy")
        reasoning.append(
            f"cap applied: unmeasured_accuracy — buy_now reduced to "
            f"{pack.unmeasured_cap} until the series is measured"
        )
    return base, value, caps, reasoning


def compute_signal(
    store: Store, forecast: Forecast, pack: SignalPack
) -> BuySignal:
    """Compute the signal artefact for one pinned forecast."""
    inputs = gather_inputs(store, forecast, pack)
    base, value, caps, reasoning = decide(inputs, pack)
    if forecast.missing_drivers:
        reasoning.append(
            f"named gaps: the pinned forecast carries missing "
            f"drivers {forecast.missing_drivers} — the call is made "
            "with them named, not hidden"
        )
    reasoning.append(SCOPE_NOTE)
    signal = BuySignal(
        signal_id="SIG-pending",
        commodity=forecast.commodity,
        market=forecast.market,
        forecast_id=forecast.forecast_id,
        forecast_status=forecast.status,
        as_of=forecast.as_of,
        horizon_days=pack.horizon_days,
        spot_inr=inputs.spot_inr,
        spot_date=inputs.spot_date,
        p10_horizon_inr=inputs.p10_inr,
        p50_horizon_inr=inputs.p50_inr,
        p90_horizon_inr=inputs.p90_inr,
        drift_pct=inputs.drift_pct,
        band_width_pct=inputs.band_width_pct,
        accuracy_state=inputs.accuracy_state,
        accuracy_record_ids=inputs.accuracy_record_ids,
        degraded_horizons=inputs.degraded_horizons,
        base_value=base,  # type: ignore[arg-type]
        value=value,  # type: ignore[arg-type]
        caps_applied=caps,
        active_events=inputs.active_events,
        missing_drivers=list(forecast.missing_drivers),
        reasoning=reasoning,
        pack_version=pack.version,
        scope_note=SCOPE_NOTE,
    )
    return signal.model_copy(update={"signal_id": signal_content_id(signal)})
