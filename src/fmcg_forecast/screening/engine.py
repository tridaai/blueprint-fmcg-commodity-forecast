"""The screen itself: one pure judgement, shared by all.

Candidate text + the pack → the rules that match, in
pack order. It touches no store, so the pipeline (to
decide a live item) and the verifier (to re-perform a
stored record from the stored headline alone) run the
identical judgement.

The judgement is over the folded shape the pack states:
lower case, zero-width characters removed, every run of
non-alphanumeric characters collapsed to one space,
padded at both ends so a phrase matches at the text's
edges exactly as it matches mid-text. Folding is a
reading discipline, not an edit — the text that travels
onward (or onto the quarantine record) is always the
original, byte for byte.
"""

from __future__ import annotations

import re

from fmcg_forecast.screening.models import ScreeningRecord, screening_content_id
from fmcg_forecast.screening.pack import ScreeningPack
from fmcg_forecast.sentiment.models import SentimentItem

_ZERO_WIDTH = ("\u200b", "\u200c", "\u200d", "\ufeff")
_NON_ALNUM_RUN = re.compile(r"[^a-z0-9]+")


def fold_for_screening(text: str) -> str:
    """The pack's stated folded shape of a text."""
    folded = text.lower()
    for char in _ZERO_WIDTH:
        folded = folded.replace(char, "")
    folded = _NON_ALNUM_RUN.sub(" ", folded)
    return f" {folded.strip()} "


def match_rules(text: str, pack: ScreeningPack) -> list[str]:
    """The ids of the pack rules the text trips, in pack order."""
    folded = fold_for_screening(text)
    matched: list[str] = []
    for rule in pack.rules:
        if any(f" {phrase} " in folded for phrase in rule.phrases):
            matched.append(rule.rule_id)
    return matched


def judge_item(item: SentimentItem, pack: ScreeningPack) -> ScreeningRecord | None:
    """The quarantine record for an item, or None when it passes."""
    matched = match_rules(item.headline, pack)
    if not matched:
        return None
    by_id = {rule.rule_id: rule for rule in pack.rules}
    record = ScreeningRecord(
        record_id="SRN-pending",
        item_id=item.item_id,
        commodity=item.commodity,
        item_date=item.item_date,
        headline=item.headline,
        matched_rule_ids=matched,
        categories=sorted({by_id[rule_id].category for rule_id in matched}),
        pack_version=pack.version,
    )
    record.record_id = screening_content_id(record)
    return record
