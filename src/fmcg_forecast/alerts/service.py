"""The alerting workflow every surface shares.

Entering a subscription is a named desk act: a named subscriber
(placeholder names refused, as at every gate in this repo), a
stated role, catalogue scope, kinds from the pack's vocabulary
and a severity floor. Entry is idempotent — the subscription is
content-addressed — and a changed statement supersedes the
subscriber's previous subscription by link.

The sweep derives alerts from the record and stores the ones
that do not exist yet. It never authors: every alert it stores
is the content address of (subscription, kind, trigger), and
the accuracy kinds additionally respect the open-episode rule.
Signals that match no head subscription raise nothing and are
counted in the sweep's summary — absence is a reported outcome.

Acts are attributed and insert-only. An alert's state is never
written anywhere: reads fold the acts and the escalation clock.
"""

from __future__ import annotations

from datetime import date, datetime

from fmcg_forecast.alerts.engine import (
    candidate_to_alert,
    compute_crossings,
    derive_candidates,
    episode_open_alert,
    fold_state,
    head_subscriptions,
    trigger_superseded,
)
from fmcg_forecast.alerts.models import (
    AlertAct,
    AlertDigest,
    AlertInstance,
    AlertSubscription,
    act_content_id,
    digest_content_id,
    subscription_content_id,
)
from fmcg_forecast.alerts.pack import (
    ACCURACY_KINDS,
    ALERT_SCOPE_NOTE,
    SEVERITY_RANK,
    AlertPack,
    load_alert_pack,
)
from fmcg_forecast.alerts.verify import (
    verify_alert,
    verify_alert_set,
    verify_digest,
    verify_subscription,
)
from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.store import Store

_PLACEHOLDER_NAMES = {"", "tbd", "test", "user", "admin", "someone", "n/a", "na"}


def _require_named(value: str, field: str) -> str:
    cleaned = (value or "").strip()
    if cleaned.lower() in _PLACEHOLDER_NAMES or len(cleaned) < 2:
        raise AlertValidationError(
            f"{field} must be a named human — an act by {value!r} "
            "cannot be attributed, so it is refused"
        )
    return cleaned


class AlertValidationError(ValueError):
    """An entry or act breaks the stated rules."""


class AlertNotFoundError(LookupError):
    """A named subscription, alert or digest does not exist."""


class AlertStateError(RuntimeError):
    """The alert's folded state does not admit the requested act."""


class AlertService:
    def __init__(self, store: Store, pack: AlertPack | None = None):
        self.store = store
        self.pack = pack or load_alert_pack()

    # -- subscriptions ---------------------------------------------------

    def enter_subscription(
        self,
        subscriber: str,
        role: str,
        entered_on: date,
        commodities: list[str],
        markets: list[str],
        kinds: list[str],
        min_severity: str = "minor",
        note: str = "",
    ) -> AlertSubscription:
        subscriber = _require_named(subscriber, "subscriber")
        role = _require_named(role, "role")
        for commodity in commodities:
            if commodity not in BY_NAME:
                raise AlertValidationError(
                    f"unknown commodity {commodity!r} — the "
                    "catalogue names seven"
                )
        known_markets = {
            m.market
            for spec in BY_NAME.values()
            for m in spec.markets
            if not commodities or spec.commodity in commodities
        }
        for market in markets:
            if market not in known_markets:
                raise AlertValidationError(
                    f"market {market!r} is not a market of the "
                    "watched commodities in the catalogue"
                )
        for kind in kinds:
            if kind not in self.pack.kinds:
                raise AlertValidationError(
                    f"unknown alert kind {kind!r} — the pack "
                    f"names {', '.join(self.pack.kinds)}"
                )
        if not kinds:
            raise AlertValidationError(
                "a subscription that watches no kind watches "
                "nothing — name at least one kind"
            )
        if min_severity not in SEVERITY_RANK:
            raise AlertValidationError(
                f"unknown severity {min_severity!r} — the ladder "
                f"is {', '.join(self.pack.severities)}"
            )
        previous = self.head_subscription(subscriber)
        subscription = AlertSubscription(
            subscription_id="SUB-pending",
            subscriber=subscriber,
            role=role,
            entered_on=entered_on,
            commodities=sorted(commodities),
            markets=sorted(markets),
            kinds=sorted(kinds),
            min_severity=min_severity,
            supersedes_subscription_id=(
                previous.subscription_id if previous is not None else None
            ),
            note=note,
            pack_version=self.pack.version,
        )
        subscription = subscription.model_copy(
            update={
                "subscription_id": subscription_content_id(subscription)
            }
        )
        if (
            self.store.get_alert_subscription(subscription.subscription_id)
            is None
        ):
            self.store.insert_alert_subscription(subscription)
        return subscription

    def head_subscription(
        self, subscriber: str
    ) -> AlertSubscription | None:
        mine = [
            s
            for s in self.store.list_alert_subscriptions()
            if s.subscriber == subscriber
        ]
        heads = head_subscriptions(mine)
        return heads[0] if heads else None

    def get_subscription(self, subscription_id: str) -> AlertSubscription:
        subscription = self.store.get_alert_subscription(subscription_id)
        if subscription is None:
            raise AlertNotFoundError(f"no subscription {subscription_id}")
        return subscription

    def list_subscriptions(
        self, subscriber: str | None = None
    ) -> list[AlertSubscription]:
        return self.store.list_alert_subscriptions(subscriber)

    def subscription_view(self, subscription_id: str) -> dict:
        subscription = self.get_subscription(subscription_id)
        view = subscription.model_dump(mode="json")
        view["origin_label"] = (
            "desk-entered — the desk's own stated watch, not "
            "market data"
        )
        heads = {
            s.subscription_id
            for s in head_subscriptions(
                self.store.list_alert_subscriptions()
            )
        }
        view["is_head"] = subscription_id in heads
        view["problems"] = verify_subscription(subscription)
        return view

    # -- the sweep ---------------------------------------------------------

    def sweep(self, at: datetime) -> dict:
        """Derive alerts from the record and store the new ones.

        Returns the sweep's account of itself: crossings computed
        and newly stored, alerts raised, alerts already standing,
        and the struck signals that matched no head subscription.
        """
        crossings = compute_crossings(self.store, self.pack)
        crossings_new = 0
        for crossing in crossings:
            if self.store.get_price_crossing(crossing.crossing_id) is None:
                self.store.insert_price_crossing(crossing)
                crossings_new += 1
        candidates = derive_candidates(self.store, self.pack, crossings)
        raised: list[AlertInstance] = []
        standing = 0
        episode_held = 0
        for candidate in candidates:
            if self.store.get_alert(candidate.alert_id) is not None:
                standing += 1
                continue
            if candidate.kind in ACCURACY_KINDS:
                open_alert = episode_open_alert(
                    self.store,
                    self.pack,
                    candidate.subscription.subscription_id,
                    candidate.kind,
                    candidate.commodity,
                    candidate.market,
                    candidate.trigger_summary["horizon_days"],
                )
                if open_alert is not None:
                    episode_held += 1
                    continue
            alert = candidate_to_alert(candidate, at)
            self.store.insert_alert(alert)
            raised.append(alert)
        head_ids = {
            s.subscription_id
            for s in head_subscriptions(
                self.store.list_alert_subscriptions()
            )
        }
        matched_signal_ids = {
            c.trigger_id for c in candidates if c.kind == "buy_signal"
        }
        unmatched = [
            signal
            for signal in self.store.list_buy_signals()
            if signal.signal_id not in matched_signal_ids
        ]
        return {
            "swept_at": at.isoformat(),
            "crossings_computed": len(crossings),
            "crossings_new": crossings_new,
            "alerts_raised": [a.alert_id for a in raised],
            "alerts_raised_count": len(raised),
            "alerts_already_standing": standing,
            "alerts_episode_held": episode_held,
            "subscriptions_active": len(head_ids),
            "unmatched_signals": len(unmatched),
            "unmatched_signal_ids": [s.signal_id for s in unmatched],
        }

    # -- acts ----------------------------------------------------------------

    def _record_act(
        self,
        alert_id: str,
        act: str,
        actor: str,
        role: str,
        acted_at: datetime,
        reason: str | None,
        note: str,
    ) -> AlertAct:
        alert = self.get_alert(alert_id)
        actor = _require_named(actor, "actor")
        role = _require_named(role, "role")
        state = fold_state(
            alert, self.store.list_alert_acts(alert_id), acted_at, self.pack
        )
        if state["state"] == "closed":
            raise AlertStateError(
                f"alert {alert_id} is already closed — its fold "
                "admits no further act"
            )
        record = AlertAct(
            act_id="ALA-pending",
            alert_id=alert_id,
            act=act,  # type: ignore[arg-type]
            actor=actor,
            role=role,
            acted_at=acted_at,
            reason=reason,
            note=note,
        )
        record = record.model_copy(
            update={"act_id": act_content_id(record)}
        )
        if self.store.get_alert_act(record.act_id) is None:
            self.store.insert_alert_act(record)
        return record

    def acknowledge(
        self,
        alert_id: str,
        actor: str,
        role: str,
        acted_at: datetime,
        note: str = "",
    ) -> AlertAct:
        return self._record_act(
            alert_id, "acknowledge", actor, role, acted_at, None, note
        )

    def close(
        self,
        alert_id: str,
        actor: str,
        role: str,
        acted_at: datetime,
        reason: str,
        note: str = "",
    ) -> AlertAct:
        if reason not in self.pack.close_reasons:
            raise AlertValidationError(
                f"unknown close reason {reason!r} — the pack's "
                f"vocabulary is {', '.join(self.pack.close_reasons)}"
            )
        return self._record_act(
            alert_id, "close", actor, role, acted_at, reason, note
        )

    # -- reads -----------------------------------------------------------------

    def get_alert(self, alert_id: str) -> AlertInstance:
        alert = self.store.get_alert(alert_id)
        if alert is None:
            raise AlertNotFoundError(f"no alert {alert_id}")
        return alert

    def list_alerts(
        self,
        commodity: str | None = None,
        market: str | None = None,
        subscription_id: str | None = None,
    ) -> list[AlertInstance]:
        return self.store.list_alerts(commodity, market, subscription_id)

    def alert_view(self, alert_id: str, now: datetime) -> dict:
        alert = self.get_alert(alert_id)
        acts = self.store.list_alert_acts(alert_id)
        view = alert.model_dump(mode="json")
        view["raised_on"] = str(alert.raised_on)
        view["acts"] = [a.model_dump(mode="json") for a in acts]
        view["state"] = fold_state(alert, acts, now, self.pack)
        view["trigger_superseded"] = trigger_superseded(self.store, alert)
        view["problems"] = verify_alert(self.store, alert)
        return view

    def verify_stored(self, alert_id: str) -> list[str]:
        return verify_alert(self.store, self.get_alert(alert_id))

    def verify_all(self) -> list[str]:
        return verify_alert_set(self.store, self.pack)

    # -- digests -----------------------------------------------------------------

    def build_digest(
        self, subscription_id: str, digest_date: date
    ) -> AlertDigest:
        subscription = self.get_subscription(subscription_id)
        alerts = [
            a
            for a in self.store.list_alerts(subscription_id=subscription_id)
            if a.raised_on == digest_date
        ]
        by_kind: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for alert in alerts:
            by_kind[alert.kind] = by_kind.get(alert.kind, 0) + 1
            by_severity[alert.severity] = (
                by_severity.get(alert.severity, 0) + 1
            )
        digest = AlertDigest(
            digest_id="DIG-pending",
            subscription_id=subscription_id,
            subscriber=subscription.subscriber,
            digest_date=digest_date,
            alert_ids=sorted(a.alert_id for a in alerts),
            by_kind=by_kind,
            by_severity=by_severity,
            pack_version=self.pack.version,
            scope_note=ALERT_SCOPE_NOTE,
        )
        digest = digest.model_copy(
            update={"digest_id": digest_content_id(digest)}
        )
        if self.store.get_alert_digest(digest.digest_id) is None:
            self.store.insert_alert_digest(digest)
        return digest

    def get_digest(self, digest_id: str) -> AlertDigest:
        digest = self.store.get_alert_digest(digest_id)
        if digest is None:
            raise AlertNotFoundError(f"no digest {digest_id}")
        return digest

    def list_digests(
        self, subscription_id: str | None = None
    ) -> list[AlertDigest]:
        return self.store.list_alert_digests(subscription_id)

    def digest_view(self, digest_id: str) -> dict:
        digest = self.get_digest(digest_id)
        view = digest.model_dump(mode="json")
        view["problems"] = verify_digest(self.store, digest)
        return view


__all__ = [
    "AlertNotFoundError",
    "AlertService",
    "AlertStateError",
    "AlertValidationError",
]
