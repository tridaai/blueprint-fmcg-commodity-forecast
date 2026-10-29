"""Re-performance verification for alerting artefacts.

The verifier trusts nothing stored. Per alert it recomputes the
content address, resolves the pinned trigger, re-judges the
severity from the trigger's own facts under the alert's pack
version, and checks the facts on the alert's face against the
trigger of record. Across the set it re-runs derivation and
compares: for the non-accuracy kinds the stored alerts must be
exactly the derived set (artefacts are insert-only, so a
subscription's candidates can only grow); for the accuracy
kinds it grades the episode discipline — one open alert per
episode, and a currently-degraded or collapsed record is never
left without its open alert. Digests re-derive their alert set
from the stored alerts alone.
"""

from __future__ import annotations

from fmcg_forecast.alerts.engine import (
    crossing_severity,
    derive_candidates,
    event_severity,
    signal_severity,
)
from fmcg_forecast.alerts.models import (
    AlertDigest,
    AlertInstance,
    act_content_id,
    alert_content_id,
    crossing_content_id,
    digest_content_id,
    subscription_content_id,
)
from fmcg_forecast.alerts.pack import ACCURACY_KINDS, load_alert_pack
from fmcg_forecast.store import Store


def verify_subscription(subscription) -> list[str]:
    problems: list[str] = []
    if subscription_content_id(subscription) != subscription.subscription_id:
        problems.append(
            f"content id mismatch: stored {subscription.subscription_id}, "
            f"recomputed {subscription_content_id(subscription)} — the "
            "artefact was altered after entry"
        )
    return problems


def verify_crossing(crossing) -> list[str]:
    problems: list[str] = []
    if crossing_content_id(crossing) != crossing.crossing_id:
        problems.append(
            f"content id mismatch: stored {crossing.crossing_id}, "
            f"recomputed {crossing_content_id(crossing)} — the "
            "artefact was altered after computation"
        )
    move = round(
        (crossing.to_price - crossing.from_price) / crossing.from_price * 100,
        4,
    )
    if move != crossing.move_pct:
        problems.append(
            f"move mismatch: stored {crossing.move_pct}, recomputed "
            f"{move} from the pinned pair"
        )
    return problems


def verify_alert(store: Store, alert: AlertInstance) -> list[str]:
    """Return the list of problems with one stored alert."""
    problems: list[str] = []
    expected_id = alert_content_id(
        alert.subscription_id, alert.kind, alert.trigger_id
    )
    if expected_id != alert.alert_id:
        problems.append(
            f"content id mismatch: stored {alert.alert_id}, recomputed "
            f"{expected_id} — the alert was altered after it was raised"
        )
    try:
        pack = load_alert_pack(alert.pack_version)
    except ValueError as exc:
        problems.append(str(exc))
        return problems
    subscription = store.get_alert_subscription(alert.subscription_id)
    if subscription is None:
        problems.append(
            f"orphan alert: subscription {alert.subscription_id} is "
            "not in the store — an alert without its subscription "
            "cannot exist"
        )
        return problems
    if alert.subscriber != subscription.subscriber:
        problems.append(
            f"subscriber mismatch: alert names {alert.subscriber!r}, "
            f"its subscription names {subscription.subscriber!r}"
        )
    summary = alert.trigger_summary
    if alert.kind == "buy_signal":
        signal = store.get_buy_signal(alert.trigger_id)
        if signal is None:
            problems.append(
                f"orphan alert: triggering signal {alert.trigger_id} "
                "is not in the store"
            )
            return problems
        if alert.severity != signal_severity(signal, pack):
            problems.append(
                f"severity mismatch: stored {alert.severity}, "
                f"re-judged {signal_severity(signal, pack)} from the "
                "pinned signal under the pack"
            )
        for key, value in (
            ("signal_value", signal.value),
            ("drift_pct", signal.drift_pct),
            ("forecast_id", signal.forecast_id),
        ):
            if summary.get(key) != value:
                problems.append(
                    f"trigger summary {key} mismatch: alert carries "
                    f"{summary.get(key)!r}, the pinned signal carries "
                    f"{value!r}"
                )
    elif alert.kind == "event_window":
        event = store.get_market_event(alert.trigger_id)
        if event is None:
            problems.append(
                f"orphan alert: triggering event {alert.trigger_id} "
                "is not in the registry"
            )
            return problems
        if alert.severity != event_severity(event, pack):
            problems.append(
                f"severity mismatch: stored {alert.severity}, "
                f"re-judged {event_severity(event, pack)} from the "
                "pinned event under the pack"
            )
        if summary.get("claimed_peak_log_effect") != (
            event.transmission.peak_log_price_effect
        ):
            problems.append(
                "trigger summary claimed peak mismatch: the alert "
                "does not carry the pinned event's claimed peak"
            )
    elif alert.kind == "price_move":
        crossing = store.get_price_crossing(alert.trigger_id)
        if crossing is None:
            problems.append(
                f"orphan alert: triggering crossing {alert.trigger_id} "
                "is not in the store"
            )
            return problems
        problems.extend(
            f"pinned crossing: {p}" for p in verify_crossing(crossing)
        )
        if alert.severity != crossing_severity(crossing, pack):
            problems.append(
                f"severity mismatch: stored {alert.severity}, "
                f"re-judged {crossing_severity(crossing, pack)} from "
                "the pinned crossing under the pack"
            )
        if summary.get("move_pct") != crossing.move_pct:
            problems.append(
                "trigger summary move mismatch: the alert does not "
                "carry the pinned crossing's move"
            )
    elif alert.kind in ACCURACY_KINDS:
        record = store.get_accuracy_record(
            alert.commodity, alert.market, summary.get("horizon_days", -1)
        )
        if summary.get("record_id") is None:
            problems.append("accuracy alert pins no record id")
        if alert.kind == "accuracy_degraded":
            mape = summary.get("mape")
            bar = summary.get("degraded_threshold_mape_pct")
            if mape is None or bar is None or not mape > bar:
                problems.append(
                    "degraded alert's face does not show a MAPE over "
                    "its bar — it cannot have been raised by one"
                )
            if alert.severity != "major":
                problems.append(
                    f"severity mismatch: a degraded alert is major "
                    f"under the pack, stored {alert.severity}"
                )
        else:
            coverage = summary.get("coverage")
            floor = summary.get("coverage_floor")
            if coverage is None or floor is None or not coverage < floor:
                problems.append(
                    "coverage alert's face does not show coverage "
                    "below its floor — it cannot have been raised "
                    "by one"
                )
            if alert.severity != "critical":
                problems.append(
                    f"severity mismatch: a coverage alert is critical "
                    f"under the pack, stored {alert.severity}"
                )
        if record is not None and record.record_id == summary.get("record_id"):
            if alert.kind == "accuracy_degraded" and not record.degraded:
                problems.append(
                    "the pinned record is current and not degraded — "
                    "the alert's episode has no standing"
                )
            if (
                alert.kind == "coverage_collapse"
                and record.coverage >= pack.coverage_floor
            ):
                problems.append(
                    "the pinned record is current and its coverage "
                    "is at or above the floor — the alert's episode "
                    "has no standing"
                )
    else:
        problems.append(f"unknown alert kind {alert.kind!r}")
    from fmcg_forecast.alerts.pack import ALERT_SCOPE_NOTE

    if alert.scope_note != ALERT_SCOPE_NOTE:
        problems.append(
            "scope note missing or altered: every alert carries "
            "the signal-only scope note on its face"
        )
    return problems


def verify_alert_set(store: Store, pack=None) -> list[str]:
    """The stored alert set against a fresh derivation."""
    from fmcg_forecast.alerts.pack import load_alert_pack as _load

    pack = pack or _load()
    problems: list[str] = []
    stored = store.list_alerts()
    for alert in stored:
        problems.extend(
            f"alert {alert.alert_id}: {p}"
            for p in verify_alert(store, alert)
        )
    candidates = derive_candidates(store, pack)
    derived_ids = {c.alert_id for c in candidates}
    stored_ids = {a.alert_id for a in stored}

    # Non-accuracy kinds: stored must equal derived, exactly.
    derived_plain = {
        c.alert_id for c in candidates if c.kind not in ACCURACY_KINDS
    }
    stored_plain = {
        a.alert_id for a in stored if a.kind not in ACCURACY_KINDS
    }
    for missing in sorted(derived_plain - stored_plain):
        problems.append(
            f"derived alert {missing} was never raised — derivation "
            "and the stored set disagree"
        )
    for extra in sorted(stored_plain - derived_plain):
        problems.append(
            f"stored alert {extra} does not derive from the record — "
            "it matches no subscription and trigger"
        )

    # Accuracy kinds: the episode discipline. One open alert per
    # (subscription, kind, series, horizon); a currently degraded
    # or collapsed record is never left without an open alert
    # (or an alert pinned to the current record).
    acts_by_alert: dict[str, list] = {}
    for act in store.list_alert_acts():
        if act_content_id(act) != act.act_id:
            problems.append(
                f"act {act.act_id}: content id mismatch — the act "
                "was altered after it was recorded"
            )
        acts_by_alert.setdefault(act.alert_id, []).append(act)

    def is_open(alert: AlertInstance) -> bool:
        acts = acts_by_alert.get(alert.alert_id, [])
        closes = sorted(
            (a for a in acts if a.act == "close"),
            key=lambda a: (a.acted_at, a.act_id),
        )
        if not closes:
            return True
        return closes[0].reason != "resolved"

    def recovered(alert: AlertInstance) -> bool:
        record = store.get_accuracy_record(
            alert.commodity,
            alert.market,
            alert.trigger_summary.get("horizon_days", -1),
        )
        if record is None:
            return False
        if alert.kind == "accuracy_degraded":
            return not record.degraded
        return record.coverage >= pack.coverage_floor

    episodes: dict[tuple, list[AlertInstance]] = {}
    for alert in stored:
        if alert.kind not in ACCURACY_KINDS:
            continue
        key = (
            alert.subscription_id,
            alert.kind,
            alert.commodity,
            alert.market,
            alert.trigger_summary.get("horizon_days"),
        )
        episodes.setdefault(key, []).append(alert)
    for key, group in episodes.items():
        open_group = [
            a for a in group if is_open(a) and not recovered(a)
        ]
        if len(open_group) > 1:
            problems.append(
                f"episode {key}: {len(open_group)} open alerts — a "
                "crossing fires exactly once per episode"
            )
    for candidate in candidates:
        if candidate.kind not in ACCURACY_KINDS:
            continue
        key = (
            candidate.subscription.subscription_id,
            candidate.kind,
            candidate.commodity,
            candidate.market,
            candidate.trigger_summary.get("horizon_days"),
        )
        group = episodes.get(key, [])
        covered = any(
            is_open(a) and not recovered(a) for a in group
        ) or any(
            a.trigger_id == candidate.trigger_id for a in group
        )
        if not covered:
            problems.append(
                f"episode {key}: the current record "
                f"({candidate.trigger_id}) is degraded or collapsed "
                "and no open alert covers it"
            )
    _ = derived_ids, stored_ids
    return problems


def verify_digest(store: Store, digest: AlertDigest) -> list[str]:
    """A digest's alert set re-derived from the stored alerts."""
    problems: list[str] = []
    if digest_content_id(digest) != digest.digest_id:
        problems.append(
            f"content id mismatch: stored {digest.digest_id}, "
            f"recomputed {digest_content_id(digest)} — the digest "
            "was altered after it was built"
        )
    expected = sorted(
        a.alert_id
        for a in store.list_alerts(subscription_id=digest.subscription_id)
        if a.raised_on == digest.digest_date
    )
    if digest.alert_ids != expected:
        problems.append(
            f"digest contents mismatch: stored {digest.alert_ids}, "
            f"re-derived {expected} — a digest carries exactly its "
            "subscriber's alerts for its date"
        )
    return problems
