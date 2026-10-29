"""The alerting artefacts.

A *subscription* is the desk's own stated watch, desk-entered
like a requirement plan and labelled so on every surface: who
watches, in what role, which commodities, markets, kinds and
severity floor. It is content-addressed over the whole statement
— change any term and a new artefact supersedes the old by link.

A *price crossing* is computed, not declared: the pinned pair of
observations whose stated-window move crossed the pack's bar,
content-addressed over the pair and the pack version.

An *alert* is derived, never authored. Its content address is
over (subscription, kind, triggering artefact) alone — the same
trigger under the same subscription can only ever raise one
alert, however many times the sweep runs. The facts that decided
its severity ride on its face, copied from the trigger, so a
reader never has to chase the trigger to know why it fired.

An *alert act* is an attributed, insert-only record —
acknowledge or close (with a reason from the pack's vocabulary).
An alert's state is never stored: it is the fold of its acts
plus the pack's escalation clock, derived at read.

A *digest* is one subscriber's alerts for one day, content-
addressed over the exact alert set it carries.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


def _content_id(prefix: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return prefix + hashlib.sha256(canonical.encode()).hexdigest()[:16]


class AlertSubscription(BaseModel):
    subscription_id: str = Field(
        description="Content address: SUB-<sha256[:16]>"
    )
    subscriber: str = Field(description="The named watcher")
    role: str = Field(description="The watcher's stated role")
    entered_on: date = Field(
        description="The day the watch was entered — triggers "
        "dated before it never raise for this subscription"
    )
    commodities: list[str] = Field(
        description="Catalogue commodities watched; empty = all"
    )
    markets: list[str] = Field(
        description="Markets watched; empty = all markets of the "
        "watched commodities"
    )
    kinds: list[str] = Field(
        description="Alert kinds watched, from the pack's kinds"
    )
    min_severity: str = Field(
        description="The severity floor: triggers judged below "
        "it do not raise"
    )
    supersedes_subscription_id: str | None = Field(
        description="The subscriber's previous subscription, "
        "superseded by this one; None for their first"
    )
    note: str = ""
    pack_version: str


def subscription_content_id(subscription: AlertSubscription) -> str:
    payload = subscription.model_dump(mode="json", exclude={"subscription_id"})
    return _content_id("SUB-", payload)


class PriceCrossing(BaseModel):
    crossing_id: str = Field(description="Content address: CRS-<sha256[:16]>")
    commodity: str
    market: str
    window_days: int = Field(description="The pack's judged window")
    from_date: date
    from_price: float = Field(description="Modal price at from_date")
    to_date: date
    to_price: float = Field(description="Modal price at to_date")
    move_pct: float = Field(
        description="(to - from) / from * 100, 4dp"
    )
    direction: Literal["up", "down"]
    pack_version: str


def crossing_content_id(crossing: PriceCrossing) -> str:
    payload = crossing.model_dump(mode="json", exclude={"crossing_id"})
    return _content_id("CRS-", payload)


class AlertInstance(BaseModel):
    alert_id: str = Field(description="Content address: ALT-<sha256[:16]>")
    subscription_id: str
    subscriber: str
    kind: str
    commodity: str
    market: str = Field(
        description="The trigger's market; 'all_markets' for a "
        "commodity-scoped event window"
    )
    severity: str
    trigger_id: str = Field(
        description="The triggering artefact's id — a signal, an "
        "event, a crossing, or an accuracy record"
    )
    trigger_summary: dict = Field(
        description="The trigger facts that decided the alert, "
        "on its face: the signal's value and drift, the event's "
        "class and claimed peak, the crossing's move, the "
        "record's MAPE against its bar or its coverage against "
        "the floor"
    )
    raised_at: datetime = Field(
        description="When the sweep that raised it ran — the "
        "escalation clock counts from here"
    )
    pack_version: str
    scope_note: str

    @property
    def raised_on(self) -> date:
        return self.raised_at.date()


def alert_content_id(
    subscription_id: str, kind: str, trigger_id: str
) -> str:
    """An alert's address: (subscription, kind, trigger) — the
    dedup key. The same trigger under the same subscription can
    only ever raise one alert."""
    return _content_id(
        "ALT-",
        {
            "subscription_id": subscription_id,
            "kind": kind,
            "trigger_id": trigger_id,
        },
    )


class AlertAct(BaseModel):
    act_id: str = Field(description="Content address: ALA-<sha256[:16]>")
    alert_id: str
    act: Literal["acknowledge", "close"]
    actor: str = Field(description="The named human who acted")
    role: str
    acted_at: datetime
    reason: str | None = Field(
        description="Closures only: one of the pack's stated "
        "close reasons"
    )
    note: str = ""


def act_content_id(act: AlertAct) -> str:
    payload = act.model_dump(mode="json", exclude={"act_id"})
    return _content_id("ALA-", payload)


class AlertDigest(BaseModel):
    digest_id: str = Field(description="Content address: DIG-<sha256[:16]>")
    subscription_id: str
    subscriber: str
    digest_date: date
    alert_ids: list[str] = Field(
        description="Exactly the subscription's alerts raised on "
        "digest_date, sorted"
    )
    by_kind: dict[str, int]
    by_severity: dict[str, int]
    pack_version: str
    scope_note: str


def digest_content_id(digest: AlertDigest) -> str:
    payload = digest.model_dump(mode="json", exclude={"digest_id"})
    return _content_id("DIG-", payload)
