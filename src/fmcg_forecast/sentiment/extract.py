"""Offline extraction: the stated lexicon rule over a headline.

This is the offline model profile's sentiment extraction — a
deterministic implementation of the pack's stated rule, used by
tests, evals and the demo. Hosted profiles perform the same
extraction through structured outputs against the same schema;
the artefact shape and the classification rule (the margin, the
direction ladder, the strength formula) are the pack's, not the
model's, so a reading is reproducible and re-performable offline
no matter which profile produced it.

The rule, exactly as the pack states it: match lexicon phrases on
word boundaries, longest phrase first, non-overlapping; the score
is the sum of polarity x weight; no matches is unclassified (no
signal); a zero score is unclassified (signals cancel — the item
is never forced into a direction); otherwise direction is the
sign at the stated step and strength follows the stated formula.
"""

from __future__ import annotations

import hashlib
import json
import re

from fmcg_forecast.sentiment.models import SentimentExtraction, SentimentItem
from fmcg_forecast.sentiment.pack import SentimentPack


def _match_phrases(headline: str, pack: SentimentPack) -> list:
    """Lexicon matches in headline order, longest-first, non-overlapping."""
    text = headline.lower()
    occupied = [False] * len(text)
    found: list[tuple[int, object]] = []
    entries = sorted(pack.lexicon, key=lambda e: -len(e.phrase))
    for entry in entries:
        pattern = re.compile(r"\b" + re.escape(entry.phrase) + r"\b")
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(occupied[start:end]):
                continue
            for i in range(start, end):
                occupied[i] = True
            found.append((start, entry))
    found.sort(key=lambda pair: pair[0])
    return [entry for _, entry in found]


def extract_headline(headline: str, pack: SentimentPack) -> dict:
    """The raw reading of one headline under the pack's rule."""
    matched = _match_phrases(headline, pack)
    score = sum(e.polarity * e.weight for e in matched)
    aspects: dict[str, int] = {}
    for entry in matched:
        aspects[entry.aspect] = aspects.get(entry.aspect, 0) + entry.polarity * entry.weight
    aspects = {a: s for a, s in aspects.items() if s != 0}
    phrases = [e.phrase for e in matched]
    if not matched:
        return {
            "status": "unclassified",
            "score": 0,
            "direction": None,
            "strength": None,
            "aspects": {},
            "matched_phrases": [],
            "reason": "no lexicon signal in the headline — nothing to read, "
            "and the extractor does not guess",
        }
    if score == 0:
        return {
            "status": "unclassified",
            "score": 0,
            "direction": None,
            "strength": None,
            "aspects": aspects,
            "matched_phrases": phrases,
            "reason": "signals cancel: the headline carries signed phrases "
            "in both directions with no net direction",
        }
    sign = 1 if score > 0 else -1
    return {
        "status": "classified",
        "score": score,
        "direction": sign * (1.0 if abs(score) >= pack.strong_score else 0.5),
        "strength": min(1.0, abs(score) / pack.strength_divisor),
        "aspects": aspects,
        "matched_phrases": phrases,
        "reason": None,
    }


def build_extraction(
    item: SentimentItem, reading: dict, pack: SentimentPack, model_profile: str
) -> SentimentExtraction:
    """Wrap a raw reading in the content-addressed artefact."""
    extraction = SentimentExtraction(
        extraction_id="SXT-pending",
        item_id=item.item_id,
        commodity=item.commodity,
        item_date=item.item_date,
        model_profile=model_profile,
        pack_version=pack.version,
        status=reading["status"],
        score=reading["score"],
        direction=reading["direction"],
        strength=reading["strength"],
        aspects=reading["aspects"],
        matched_phrases=reading["matched_phrases"],
        reason=reading["reason"],
    )
    extraction.extraction_id = extraction_content_id(extraction)
    return extraction


def extraction_content_id(extraction: SentimentExtraction) -> str:
    payload = extraction.model_dump(mode="json", exclude={"extraction_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "SXT-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]
