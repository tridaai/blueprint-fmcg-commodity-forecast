"""Re-performance verification for registry artefacts.

The verifier trusts nothing stored: it recomputes the content
address and re-checks the declaration's internal consistency —
direction against claimed sign, window order, channel against the
pack's allowed channels for the class, basis against the pack's
vocabulary. A declaration altered after registration fails here
even if it still parses. (The transmission's agreement with
history is a separate judgement — see measure.py.)
"""

from __future__ import annotations

from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.events.models import MarketEvent, event_content_id
from fmcg_forecast.events.pack import EventPack


def verify_market_event(event: MarketEvent, pack: EventPack) -> list[str]:
    """Return the list of problems with a stored market event."""
    problems: list[str] = []
    if event_content_id(event) != event.event_id:
        problems.append(
            f"content id mismatch: stored {event.event_id}, recomputed "
            f"{event_content_id(event)} — the declaration was altered "
            "after registration"
        )
    if event.pack_version != pack.version:
        problems.append(
            f"event was declared under pack {event.pack_version}, "
            f"cannot re-perform under {pack.version}"
        )
        return problems
    if event.commodity not in BY_NAME:
        problems.append(f"unknown commodity {event.commodity!r}")
    claimed = event.transmission.peak_log_price_effect
    if claimed == 0.0:
        problems.append("claimed peak log-price effect is zero — an event must move the price")
    elif event.direction != (1 if claimed > 0 else -1):
        problems.append(
            f"direction {event.direction} disagrees with the claimed "
            f"peak's sign ({claimed:+.4f})"
        )
    if event.window_end is not None and event.window_end < event.window_start:
        problems.append("window end precedes window start")
    allowed = pack.classes.get(event.event_class, [])
    if event.transmission.channel not in allowed:
        problems.append(
            f"channel {event.transmission.channel!r} is not one of the "
            f"pack's channels for {event.event_class}: {allowed}"
        )
    if event.transmission.basis not in pack.bases:
        problems.append(
            f"basis {event.transmission.basis!r} is not in the pack's "
            f"vocabulary: {pack.bases}"
        )
    if event.decay_days < 1:
        problems.append("decay_days must be at least 1")
    return problems
