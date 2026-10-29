"""Alert derivation and the state fold — pure functions of the
record.

Derivation reads only artefacts: struck signals, declared
events, the observation series (for computed crossings) and the
current accuracy records, matched against the subscriptions of
record. Nothing here writes; the service stores what derivation
returns, and the verifier re-runs derivation to check the stored
set. Because artefacts are insert-only, a subscription's
candidate set can only grow — which is what makes an exact
stored-vs-derived comparison sound for the non-accuracy kinds.

Crossing rule, stated once and performed exactly: for every
observation date ``d`` in a series with an observation exactly
``window_days`` earlier at ``f``, the window move is
``(p(d) - p(f)) / p(f) * 100`` (4dp). A crossing is recorded
where the move clears the pack's bar and the preceding
computable window's move did not — one crossing per excursion.
A window that cannot be computed (no observation at ``f``)
judges nothing and leaves the excursion state untouched.

The state fold: an alert's state is derived, never stored.
Closures fold first (the earliest close ends the alert), then
acknowledgements (the earliest ack stops the escalation clock
at the rung it had reached), then the clock itself: each fully
elapsed pack window for the alert's severity, counted from its
raised time, moves it one rung up the ladder.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fmcg_forecast.alerts.models import (
    AlertAct,
    AlertInstance,
    AlertSubscription,
    PriceCrossing,
    alert_content_id,
    crossing_content_id,
)
from fmcg_forecast.alerts.pack import (
    ACCURACY_KINDS,
    ALERT_SCOPE_NOTE,
    SEVERITY_RANK,
    AlertPack,
)
from fmcg_forecast.catalogue import COMMODITIES
from fmcg_forecast.dashboards.assemble import head_forecast
from fmcg_forecast.store import Store


class AlertError(RuntimeError):
    """Derivation cannot proceed on the record as it stands."""


# -- series enumeration ---------------------------------------------------


def known_series(store: Store) -> list[tuple[str, str]]:
    """Every (commodity, market) the store knows: the catalogue,
    plus any series named by a stored forecast, signal or
    accuracy record."""
    keys: set[tuple[str, str]] = set()
    for spec in COMMODITIES:
        for market in spec.markets:
            keys.add((spec.commodity, market.market))
    for forecast in store.list_forecasts():
        keys.add((forecast.commodity, forecast.market))
    for signal in store.list_buy_signals():
        keys.add((signal.commodity, signal.market))
    for record in store.list_accuracy_records():
        keys.add((record.commodity, record.market))
    return sorted(keys)


# -- crossings --------------------------------------------------------------


def compute_crossings(
    store: Store, pack: AlertPack
) -> list[PriceCrossing]:
    """Every price crossing on the record, per the stated rule."""
    crossings: list[PriceCrossing] = []
    window = timedelta(days=pack.price_window_days)
    for commodity, market in known_series(store):
        rows = store.series(commodity, market, "modal_price")
        by_date = {row.obs_date: row.value for row in rows}
        prev_abs_move: float | None = None
        for day in sorted(by_date):
            start = day - window
            if start not in by_date:
                continue
            move = round(
                (by_date[day] - by_date[start]) / by_date[start] * 100, 4
            )
            if abs(move) >= pack.price_move_bar_pct and (
                prev_abs_move is None
                or prev_abs_move < pack.price_move_bar_pct
            ):
                crossing = PriceCrossing(
                    crossing_id="CRS-pending",
                    commodity=commodity,
                    market=market,
                    window_days=pack.price_window_days,
                    from_date=start,
                    from_price=by_date[start],
                    to_date=day,
                    to_price=by_date[day],
                    move_pct=move,
                    direction="up" if move > 0 else "down",
                    pack_version=pack.version,
                )
                crossing = crossing.model_copy(
                    update={"crossing_id": crossing_content_id(crossing)}
                )
                crossings.append(crossing)
            prev_abs_move = abs(move)
    return crossings


# -- severity judgements ----------------------------------------------------


def signal_severity(signal, pack: AlertPack) -> str:
    severity = pack.signal_severity[signal.value]
    if (
        signal.value == "buy_now"
        and abs(signal.drift_pct) >= pack.critical_drift_pct
    ):
        severity = "critical"
    return severity


def event_severity(event, pack: AlertPack) -> str:
    peak = abs(event.transmission.peak_log_price_effect)
    if peak >= pack.event_critical_peak:
        return "critical"
    if peak >= pack.event_major_peak:
        return "major"
    return "minor"


def crossing_severity(crossing: PriceCrossing, pack: AlertPack) -> str:
    if abs(crossing.move_pct) >= (
        pack.price_move_bar_pct * pack.price_critical_multiple
    ):
        return "critical"
    return "major"


# -- subscription matching ---------------------------------------------------


def _scope_matches(
    subscription: AlertSubscription, commodity: str, market: str | None
) -> bool:
    if subscription.commodities and commodity not in subscription.commodities:
        return False
    if market is not None and subscription.markets:
        return market in subscription.markets
    return True


def head_subscriptions(
    subscriptions: list[AlertSubscription],
) -> list[AlertSubscription]:
    """The subscriptions not superseded by another of record."""
    superseded = {
        s.supersedes_subscription_id
        for s in subscriptions
        if s.supersedes_subscription_id is not None
    }
    return [s for s in subscriptions if s.subscription_id not in superseded]


@dataclass
class Candidate:
    """One alert that should exist, before it is stored."""

    subscription: AlertSubscription
    kind: str
    commodity: str
    market: str
    severity: str
    trigger_id: str
    trigger_summary: dict

    @property
    def alert_id(self) -> str:
        return alert_content_id(
            self.subscription.subscription_id, self.kind, self.trigger_id
        )


def derive_candidates(
    store: Store,
    pack: AlertPack,
    crossings: list[PriceCrossing] | None = None,
) -> list[Candidate]:
    """The full candidate set over every subscription of record
    that is a current head or already has alerts — the exact set
    the verifier grades the stored non-accuracy alerts against.
    """
    if crossings is None:
        crossings = compute_crossings(store, pack)
    subscriptions = store.list_alert_subscriptions()
    with_alerts = {a.subscription_id for a in store.list_alerts()}
    heads = {s.subscription_id for s in head_subscriptions(subscriptions)}
    active = [
        s
        for s in subscriptions
        if s.subscription_id in heads or s.subscription_id in with_alerts
    ]
    candidates: list[Candidate] = []
    signals = store.list_buy_signals()
    events = [
        e for e in store.list_market_events() if e.origin != "scenario"
    ]
    records = store.list_accuracy_records()
    for sub in active:
        floor = SEVERITY_RANK[sub.min_severity]

        def keep(kind: str, severity: str) -> bool:
            return kind in sub.kinds and SEVERITY_RANK[severity] >= floor

        if "buy_signal" in sub.kinds:
            for signal in signals:
                if signal.as_of < sub.entered_on:
                    continue
                if not _scope_matches(sub, signal.commodity, signal.market):
                    continue
                severity = signal_severity(signal, pack)
                if not keep("buy_signal", severity):
                    continue
                candidates.append(
                    Candidate(
                        subscription=sub,
                        kind="buy_signal",
                        commodity=signal.commodity,
                        market=signal.market,
                        severity=severity,
                        trigger_id=signal.signal_id,
                        trigger_summary={
                            "signal_value": signal.value,
                            "base_value": signal.base_value,
                            "drift_pct": signal.drift_pct,
                            "band_width_pct": signal.band_width_pct,
                            "spot_inr": signal.spot_inr,
                            "spot_date": str(signal.spot_date),
                            "forecast_id": signal.forecast_id,
                            "as_of": str(signal.as_of),
                            "accuracy_state": signal.accuracy_state,
                            "caps_applied": list(signal.caps_applied),
                        },
                    )
                )
        if "event_window" in sub.kinds:
            for event in events:
                if event.declared_on < sub.entered_on:
                    continue
                if not _scope_matches(sub, event.commodity, None):
                    continue
                severity = event_severity(event, pack)
                if not keep("event_window", severity):
                    continue
                candidates.append(
                    Candidate(
                        subscription=sub,
                        kind="event_window",
                        commodity=event.commodity,
                        market="all_markets",
                        severity=severity,
                        trigger_id=event.event_id,
                        trigger_summary={
                            "event_class": event.event_class,
                            "window_start": str(event.window_start),
                            "window_end": (
                                str(event.window_end)
                                if event.window_end is not None
                                else None
                            ),
                            "claimed_peak_log_effect": (
                                event.transmission.peak_log_price_effect
                            ),
                            "declared_on": str(event.declared_on),
                            "origin": event.origin,
                        },
                    )
                )
        if "price_move" in sub.kinds:
            for crossing in crossings:
                if crossing.to_date < sub.entered_on:
                    continue
                if not _scope_matches(
                    sub, crossing.commodity, crossing.market
                ):
                    continue
                severity = crossing_severity(crossing, pack)
                if not keep("price_move", severity):
                    continue
                candidates.append(
                    Candidate(
                        subscription=sub,
                        kind="price_move",
                        commodity=crossing.commodity,
                        market=crossing.market,
                        severity=severity,
                        trigger_id=crossing.crossing_id,
                        trigger_summary={
                            "window_days": crossing.window_days,
                            "from_date": str(crossing.from_date),
                            "from_price": crossing.from_price,
                            "to_date": str(crossing.to_date),
                            "to_price": crossing.to_price,
                            "move_pct": crossing.move_pct,
                            "direction": crossing.direction,
                        },
                    )
                )
        if any(kind in sub.kinds for kind in ACCURACY_KINDS):
            for record in records:
                if not _scope_matches(sub, record.commodity, record.market):
                    continue
                if record.degraded and "accuracy_degraded" in sub.kinds:
                    severity = "major"
                    if keep("accuracy_degraded", severity):
                        candidates.append(
                            Candidate(
                                subscription=sub,
                                kind="accuracy_degraded",
                                commodity=record.commodity,
                                market=record.market,
                                severity=severity,
                                trigger_id=record.record_id,
                                trigger_summary={
                                    "record_id": record.record_id,
                                    "horizon_days": record.horizon_days,
                                    "mape": record.mape,
                                    "degraded_threshold_mape_pct": (
                                        record.degraded_threshold_mape_pct
                                    ),
                                    "coverage": record.coverage,
                                    "n_results": record.n_results,
                                },
                            )
                        )
                if (
                    record.coverage < pack.coverage_floor
                    and "coverage_collapse" in sub.kinds
                ):
                    severity = "critical"
                    if keep("coverage_collapse", severity):
                        candidates.append(
                            Candidate(
                                subscription=sub,
                                kind="coverage_collapse",
                                commodity=record.commodity,
                                market=record.market,
                                severity=severity,
                                trigger_id=record.record_id,
                                trigger_summary={
                                    "record_id": record.record_id,
                                    "horizon_days": record.horizon_days,
                                    "coverage": record.coverage,
                                    "coverage_floor": pack.coverage_floor,
                                    "mape": record.mape,
                                    "degraded": record.degraded,
                                    "n_results": record.n_results,
                                },
                            )
                        )
    return candidates


def candidate_to_alert(candidate: Candidate, raised_at: datetime) -> AlertInstance:
    sub = candidate.subscription
    return AlertInstance(
        alert_id=candidate.alert_id,
        subscription_id=sub.subscription_id,
        subscriber=sub.subscriber,
        kind=candidate.kind,
        commodity=candidate.commodity,
        market=candidate.market,
        severity=candidate.severity,
        trigger_id=candidate.trigger_id,
        trigger_summary=candidate.trigger_summary,
        raised_at=raised_at,
        pack_version=sub.pack_version,
        scope_note=ALERT_SCOPE_NOTE,
    )


# -- the state fold ----------------------------------------------------------


def _level_at(alert: AlertInstance, pack: AlertPack, moment: datetime) -> int:
    """Escalation rungs fully elapsed between raising and moment."""
    windows = pack.escalation_windows_hours[alert.severity]
    elapsed = (moment - alert.raised_at).total_seconds() / 3600.0
    level = 0
    acc = 0.0
    for window in windows:
        acc += window
        if elapsed >= acc:
            level += 1
        else:
            break
    return level


def _holder(pack: AlertPack, level: int) -> str:
    if level <= 0:
        return "subscriber"
    return pack.escalation_ladder[min(level, len(pack.escalation_ladder)) - 1]


def _next_escalation_at(
    alert: AlertInstance, pack: AlertPack, level: int
) -> datetime | None:
    windows = pack.escalation_windows_hours[alert.severity]
    if level >= len(windows):
        return None
    acc = sum(windows[: level + 1])
    return alert.raised_at + timedelta(hours=acc)


def fold_state(
    alert: AlertInstance,
    acts: list[AlertAct],
    now: datetime,
    pack: AlertPack,
) -> dict:
    """The alert's derived state at ``now``: the fold of its acts
    plus the escalation clock. Nothing here is stored."""
    ordered = sorted(acts, key=lambda a: (a.acted_at, a.act_id))
    closes = [a for a in ordered if a.act == "close"]
    acks = [a for a in ordered if a.act == "acknowledge"]
    if closes:
        first = closes[0]
        return {
            "state": "closed",
            "escalation_level": _level_at(alert, pack, first.acted_at),
            "current_holder": None,
            "acknowledged_by": acks[0].actor if acks else None,
            "acknowledged_at": (
                acks[0].acted_at.isoformat() if acks else None
            ),
            "closed_by": first.actor,
            "closed_at": first.acted_at.isoformat(),
            "close_reason": first.reason,
            "next_escalation_at": None,
        }
    if acks:
        first = acks[0]
        level = _level_at(alert, pack, first.acted_at)
        return {
            "state": "acknowledged",
            "escalation_level": level,
            "current_holder": _holder(pack, level),
            "acknowledged_by": first.actor,
            "acknowledged_at": first.acted_at.isoformat(),
            "closed_by": None,
            "closed_at": None,
            "close_reason": None,
            "next_escalation_at": None,
        }
    level = _level_at(alert, pack, now)
    return {
        "state": "raised" if level == 0 else "escalated",
        "escalation_level": level,
        "current_holder": _holder(pack, level),
        "acknowledged_by": None,
        "acknowledged_at": None,
        "closed_by": None,
        "closed_at": None,
        "close_reason": None,
        "next_escalation_at": (
            _next_escalation_at(alert, pack, level).isoformat()
            if _next_escalation_at(alert, pack, level) is not None
            else None
        ),
    }


def episode_open_alert(
    store: Store,
    pack: AlertPack,
    subscription_id: str,
    kind: str,
    commodity: str,
    market: str,
    horizon_days: int,
) -> AlertInstance | None:
    """The open alert for an accuracy episode, if one stands.

    An episode is open while an alert for (subscription, kind,
    series, horizon) exists that has not been closed with the
    reason ``resolved`` and whose series has not recovered on
    the current record. A still-degraded replacement record
    does not open a second episode."""
    record = store.get_accuracy_record(commodity, market, horizon_days)
    for alert in store.list_alerts(
        commodity=commodity, market=market, subscription_id=subscription_id
    ):
        if alert.kind != kind:
            continue
        if alert.trigger_summary.get("horizon_days") != horizon_days:
            continue
        closes = sorted(
            (a for a in store.list_alert_acts(alert.alert_id) if a.act == "close"),
            key=lambda a: (a.acted_at, a.act_id),
        )
        if closes and closes[0].reason == "resolved":
            continue
        if record is not None:
            if kind == "accuracy_degraded" and not record.degraded:
                continue
            if (
                kind == "coverage_collapse"
                and record.coverage >= pack.coverage_floor
            ):
                continue
        return alert
    return None


def trigger_superseded(store: Store, alert: AlertInstance) -> bool:
    """Whether the alert's trigger has been superseded on read.

    A signal alert is superseded when the series' head forecast
    has moved past the forecast the signal was pinned to. Other
    kinds pin artefacts that are never superseded in place."""
    if alert.kind != "buy_signal":
        return False
    signal = store.get_buy_signal(alert.trigger_id)
    if signal is None:
        return True
    head = head_forecast(store, signal.commodity, signal.market)
    if head is None:
        return True
    return head.forecast_id != signal.forecast_id
