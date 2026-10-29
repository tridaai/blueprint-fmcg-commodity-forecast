"""The alert pack — what raises an alert, and how fast it
escalates, as data.

Every rule that turns an artefact of record into an alert is
stated here, versioned, never buried in code: which kinds exist,
how a trigger's severity is judged, the price-move window and
bar, the coverage floor, the escalation ladder and its windows,
and the vocabulary a closure must name. A change to any of it
is a new pack version, and every alert names the version it was
derived under — the verifier re-performs under exactly that
pack.

The derivation rules, as the pack states them:

1. **Buy signals.** A struck signal matching a subscription's
   scope raises one alert per (subscription, signal). Severity:
   the pack's value map (buy_now major, phased minor, wait
   minor), raised to critical when a buy_now's drift clears the
   critical drift bar.
2. **Event windows.** A declared event matching a subscription's
   commodity scope raises one alert per (subscription, event) —
   however many signals reference the event, the window fires
   once. Severity from the claimed peak: at or above the
   critical peak bar, critical; at or above the major peak bar,
   major; otherwise minor.
3. **Price moves.** A crossing is computed, not declared: for
   each observation date with an observation exactly one window
   earlier, the window move is judged against the move bar. A
   crossing is recorded where the move clears the bar and the
   preceding window's move did not — one crossing per excursion,
   pinned to the pair of observations that decided it. Severity:
   a move at or beyond twice the bar is critical, else major.
4. **Accuracy.** A series x horizon whose current ledger record
   is degraded raises one alert per open episode; a record whose
   coverage falls below the coverage floor raises one per open
   episode at critical. An episode stays open until a named act
   closes its alert with the reason ``resolved`` or the record
   itself recovers — a still-degraded replacement record does
   not re-fire.
5. **Escalation.** An alert sits with its subscriber. While it
   is unacknowledged and unclosed, each fully elapsed pack
   window for its severity moves it one rung up the ladder
   (desk head, then procurement lead). Acknowledgement stops
   the clock; closure ends the alert. Escalation is derived at
   read from the alert's raised time and the acts of record —
   no background job's say-so is involved.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from fmcg_forecast.signals.pack import SCOPE_NOTE

ALERT_KINDS: tuple[str, ...] = (
    "buy_signal",
    "event_window",
    "price_move",
    "accuracy_degraded",
    "coverage_collapse",
)

ACCURACY_KINDS: tuple[str, ...] = ("accuracy_degraded", "coverage_collapse")

SEVERITIES: tuple[str, ...] = ("minor", "major", "critical")

SEVERITY_RANK: dict[str, int] = {name: i for i, name in enumerate(SEVERITIES)}

CLOSE_REASONS: tuple[str, ...] = (
    "acted_on",
    "resolved",
    "no_action_needed",
    "false_alarm",
    "superseded_by_events",
)

ALERT_SCOPE_NOTE = SCOPE_NOTE


class AlertPack(BaseModel):
    version: str
    kinds: list[str] = Field(description="The alert kinds that exist")
    severities: list[str] = Field(
        description="The severity ladder, ascending"
    )
    signal_severity: dict[str, str] = Field(
        description="Buy-signal value -> severity, before the "
        "critical drift rule"
    )
    critical_drift_pct: float = Field(
        description="A buy_now whose absolute drift reaches this "
        "percent is critical"
    )
    price_window_days: int = Field(
        description="The window a price move is judged over"
    )
    price_move_bar_pct: float = Field(
        description="The absolute window move, in percent, that "
        "records a crossing"
    )
    price_critical_multiple: float = Field(
        description="A move at or beyond this multiple of the bar "
        "is critical"
    )
    event_major_peak: float = Field(
        description="Claimed peak log effect at or above which an "
        "event window alert is major"
    )
    event_critical_peak: float = Field(
        description="Claimed peak log effect at or above which an "
        "event window alert is critical"
    )
    coverage_floor: float = Field(
        description="An accuracy record whose coverage falls below "
        "this fraction has collapsed"
    )
    escalation_ladder: list[str] = Field(
        description="The roles an unacknowledged alert climbs, "
        "after its subscriber, in order"
    )
    escalation_windows_hours: dict[str, list[float]] = Field(
        description="Per severity, the hours of silence that move "
        "an alert one rung up the ladder, one entry per rung"
    )
    close_reasons: list[str] = Field(
        description="The stated vocabulary a closure must name"
    )
    derivation_rule: str = Field(
        description="The derivation rules, stated — the engine "
        "performs exactly these"
    )
    escalation_rule: str = Field(
        description="The escalation rule, stated — the fold "
        "performs exactly this"
    )


ALERT_PACK_V1 = AlertPack(
    version="2026.10.1",
    kinds=list(ALERT_KINDS),
    severities=list(SEVERITIES),
    signal_severity={
        "buy_now": "major",
        "phased": "minor",
        "wait": "minor",
    },
    critical_drift_pct=10.0,
    price_window_days=7,
    price_move_bar_pct=5.0,
    price_critical_multiple=2.0,
    event_major_peak=0.05,
    event_critical_peak=0.10,
    coverage_floor=0.80,
    escalation_ladder=["desk_head", "procurement_lead"],
    escalation_windows_hours={
        "critical": [4.0, 12.0],
        "major": [24.0, 72.0],
        "minor": [72.0, 168.0],
    },
    close_reasons=list(CLOSE_REASONS),
    derivation_rule=(
        "One alert per (subscription, triggering artefact): a "
        "struck signal, a declared event, a computed price "
        "crossing. Accuracy kinds raise one alert per open "
        "episode per series x horizon, pinned to the record that "
        "opened it. A trigger dated before the subscription was "
        "entered never raises. Severity is judged from the "
        "trigger's own facts under this pack, and the subscription "
        "floor filters by it."
    ),
    escalation_rule=(
        "While an alert is unacknowledged and unclosed, each "
        "fully elapsed window for its severity (counted from its "
        "raised time) moves it one rung up the ladder. "
        "Acknowledgement stops the clock at whatever rung it "
        "reached. Closure ends the alert. The fold is derived at "
        "read from the acts of record."
    ),
)


def load_alert_pack(version: str | None = None) -> AlertPack:
    """Load the alert pack, fail-closed.

    An unknown version is an error, never a silent fallback — an
    alert derived under one pack must never be quietly re-read
    under another.
    """
    if version is None or version == ALERT_PACK_V1.version:
        return ALERT_PACK_V1
    raise ValueError(f"unknown alert pack version: {version!r}")
