"""From a declared event to a per-day log-price path.

The pack states the rule; this module performs it. One event's
effect on one calendar day:

- before the window opens: zero;
- inside the window: the peak, ramped linearly over the pack's
  ``ramp_days`` from the window's first day;
- after the window closes: a linear decay to zero over the
  event's own stated ``decay_days``;
- an open-ended window (still in force) never decays.

The path is what the forecast engine's events slot consumes: the
registry translates declarations into paths, the engine telescopes
them into the decomposition as each event's own line.
"""

from __future__ import annotations

from datetime import date, timedelta

from fmcg_forecast.events.models import MarketEvent
from fmcg_forecast.events.pack import EventPack


def event_log_effect(event: MarketEvent, day: date, pack: EventPack) -> float:
    """The event's stated log-price effect on one calendar day."""
    if day < event.window_start:
        return 0.0
    peak = event.transmission.peak_log_price_effect
    age = (day - event.window_start).days
    ramp = min(1.0, (age + 1) / pack.ramp_days)
    if event.window_end is None or day <= event.window_end:
        return peak * ramp
    since_end = (day - event.window_end).days
    if since_end >= event.decay_days:
        return 0.0
    # Past the ramp the in-window effect stands at the peak, so
    # the decay runs from the peak, not from a ramped value.
    return peak * max(0.0, 1.0 - since_end / event.decay_days)


def build_event_path(
    event: MarketEvent, first_day: date, days: int, pack: EventPack
) -> list[float]:
    """The per-day log-price path starting at ``first_day``."""
    return [
        event_log_effect(event, first_day + timedelta(days=i), pack)
        for i in range(days)
    ]


def path_touches(path: list[float]) -> bool:
    """True when any day of the path carries a non-zero effect."""
    return any(v != 0.0 for v in path)
