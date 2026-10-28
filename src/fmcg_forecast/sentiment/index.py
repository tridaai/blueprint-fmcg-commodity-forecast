"""The weekly sentiment index — computed in code (Law 3).

For one commodity x ISO week, the index aggregates the classified
extractions whose item dates fall in the trailing window the pack
states (14 days ending at the week's Sunday). Each item weighs
``strength x 0.5 ** (age_days / half_life)`` with age measured
back from that Sunday; the value is the weighted mean direction.
Aspect sub-indices are the same mean restricted to extractions
carrying the aspect. A window with no classified item produces
NO index for the week — absence, never a fabricated zero — so a
thin corpus shows up as missing weeks, and the forecast engine's
estimation floors judge it honestly.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

from fmcg_forecast.sentiment.models import SentimentExtraction, SentimentIndex
from fmcg_forecast.sentiment.pack import SentimentPack


def week_bounds(day: date) -> tuple[date, date]:
    """(Monday, Sunday) of the ISO week containing ``day``."""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def compute_index(
    commodity: str,
    week_start: date,
    extractions: list[SentimentExtraction],
    pack: SentimentPack,
) -> SentimentIndex | None:
    """Compute one week's index from stored extractions.

    ``extractions`` are the commodity's extractions (any dates);
    the window selects from them. Returns None when the window
    holds no classified item.
    """
    week_end = week_start + timedelta(days=6)
    window_start = week_end - timedelta(days=pack.index_window_days - 1)
    selected = [
        e
        for e in extractions
        if e.status == "classified"
        and e.direction is not None
        and e.strength is not None
        and window_start <= e.item_date <= week_end
    ]
    if not selected:
        return None

    def weight(e: SentimentExtraction) -> float:
        age = (week_end - e.item_date).days
        return float(e.strength) * 0.5 ** (age / pack.index_half_life_days)

    total_weight = sum(weight(e) for e in selected)
    value = sum(float(e.direction) * weight(e) for e in selected) / total_weight

    aspect_values: dict[str, float] = {}
    for aspect in sorted({a for e in selected for a in e.aspects}):
        carriers = [e for e in selected if aspect in e.aspects]
        w = sum(weight(e) for e in carriers)
        aspect_values[aspect] = round(
            sum(float(e.direction) * weight(e) for e in carriers) / w, 4
        )

    index = SentimentIndex(
        index_id="SIDX-pending",
        commodity=commodity,
        week_start=week_start,
        week_end=week_end,
        value=round(value, 4),
        n_items=len(selected),
        extraction_ids=sorted(e.extraction_id for e in selected),
        aspect_values=aspect_values,
        pack_version=pack.version,
        window_days=pack.index_window_days,
        half_life_days=pack.index_half_life_days,
    )
    index.index_id = index_content_id(index)
    return index


def index_content_id(index: SentimentIndex) -> str:
    payload = index.model_dump(mode="json", exclude={"index_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "SIDX-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]
