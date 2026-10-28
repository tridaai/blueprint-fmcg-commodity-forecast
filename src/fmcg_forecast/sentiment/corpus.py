"""The planted sentiment corpus — gold by construction.

DATASET SIDE ONLY. This module generates the news/policy stream
the sentiment pack reads: deterministic, seeded headlines per
commodity across the history window (2023-01 .. 2025-12), each
planted from phrases in the sentiment pack's lexicon so its
intended reading is known exactly. The per-item intent — the
planted lexicon score, the aspects planted, and whether the item
was planted clear, cancelling (ambiguous) or signalless — is the
grading truth for extraction, and it is recorded here, on the
dataset side, exactly like the generator manifest records what
the price generator planted.

The scoring path (pack, extract, index, verify, service) never
imports this module; the load path writes the items through the
store port and the intents through the grading store, and only
tests and the eval gate read the intents back.

What is planted, all of it restated in the corpus manifest:

- the five full-coverage commodities (wheat, basmati rice,
  soybean, chili, cumin) carry items in most weeks — clear items
  (one or two same-sign lexicon phrases), a minority of cancelling
  pairs planted ambiguous, and a minority of signalless items;
- clusters around the dataset's own planted events: duty-raised
  items over the soybean tariff window, ban items over the
  basmati export-ban window, drought items over the chili drought
  — sentiment that agrees with the market's planted story;
- groundnut is sparse on purpose (~a dozen items over three
  years): an index exists for its weeks, but far too thin for the
  engine's estimation floors — the not-estimable case;
- coffee carries exactly four items: the thinnest case of all.

Source labels are generic by design (ministry release, trade
wire, market report, weather desk, industry bulletin) — no real
publication, company or person is named anywhere in the corpus.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.sentiment.models import SentimentCorpusManifest, SentimentItem
from fmcg_forecast.sentiment.pack import SENTIMENT_PACK_V1, LexiconEntry

CORPUS_VERSION = "1.0.0"
CORPUS_START = date(2023, 1, 2)  # a Monday
CORPUS_END = date(2025, 12, 19)

RICH_COMMODITIES: tuple[str, ...] = (
    "wheat",
    "basmati_rice",
    "soybean",
    "chili",
    "cumin",
)

_BY_PHRASE: dict[str, LexiconEntry] = {e.phrase: e for e in SENTIMENT_PACK_V1.lexicon}
_BY_ASPECT_SIGN: dict[tuple[str, int], list[LexiconEntry]] = {}
for _entry in SENTIMENT_PACK_V1.lexicon:
    _BY_ASPECT_SIGN.setdefault((_entry.aspect, _entry.polarity), []).append(_entry)

_SOURCE_BY_ASPECT = {
    "policy": "ministry release",
    "supply": "market report",
    "demand": "trade wire",
    "weather": "weather desk",
    "trade": "trade wire",
}

# Sentence frames. Each frame carries exactly the planted phrase(s)
# and no other lexicon phrase — the filler vocabulary is chosen to
# stay clear of the lexicon (the test suite runs the extractor over
# every planted headline and grades the recovery, so a collision
# would fail loudly rather than silently misgrade).
_SINGLE_FRAMES = (
    "{phrase} — {commodity} desks at {market} are reworking their plans.",
    "From the yards at {market}: {phrase} for {commodity} this week.",
    "{commodity} watch: {phrase}, reporters at {market} say.",
    "Morning wire on {commodity}: {phrase}.",
    "At {market}, {commodity} business stayed selective after word that {phrase}.",
)
_DOUBLE_FRAME = "Two signals for {commodity} this week: {first}; {second}."
_AMBIGUOUS_FRAME = "Mixed signals for {commodity}: {first}; {second}."
_NONE_HEADLINES = (
    "The {commodity} traders association holds its annual meet this week.",
    "Market yard at {market} extends auction hours for the season.",
    "New weighing bridges commissioned at the {market} yard.",
    "{commodity} quality graders at {market} begin their pre-season training.",
    "Cooperative banks revise crop loan paperwork for {commodity} growers.",
    "The {market} yard committee publishes its festival holiday list.",
)


class PlantedIntent(BaseModel):
    """What one item was planted to mean — grading truth.

    The expected extraction is derivable from ``planted_score``
    and ``aspect_scores`` by the pack's stated rule (see
    :func:`expected_reading`); the eval gate grades the stored
    extractions against exactly that derivation.
    """

    item_id: str
    planted_score: int = Field(description="Sum of polarity x weight over planted phrases")
    aspect_scores: dict[str, int] = Field(description="Per-aspect planted sums")
    clarity: Literal["clear", "ambiguous", "none"] = Field(
        description="clear: planted_score != 0; ambiguous: phrases "
        "planted but cancelling; none: no phrase planted"
    )


@dataclass
class GeneratedCorpus:
    items: list[SentimentItem]
    intents: list[PlantedIntent]
    manifest: SentimentCorpusManifest


def expected_reading(intent: PlantedIntent) -> dict:
    """The extraction the pack's stated rule must produce for an item.

    Grading-side derivation: for a clear item, direction and
    strength follow the pack's formula from the planted score and
    the aspects are the non-zero planted aspect sums; for an
    ambiguous or signalless item the only correct reading is
    unclassified.
    """
    pack = SENTIMENT_PACK_V1
    if intent.clarity != "clear":
        return {"status": "unclassified"}
    score = intent.planted_score
    sign = 1 if score > 0 else -1
    return {
        "status": "classified",
        "direction": sign * (1.0 if abs(score) >= pack.strong_score else 0.5),
        "strength": min(1.0, abs(score) / pack.strength_divisor),
        "aspects": {a: s for a, s in intent.aspect_scores.items() if s != 0},
        "score": score,
    }


def _mondays(start: date, end: date) -> list[date]:
    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=7)
    return days


def _digest(items: list[SentimentItem]) -> str:
    h = hashlib.sha256()
    for item in items:
        h.update(
            f"{item.item_id}|{item.commodity}|{item.item_date.isoformat()}|"
            f"{item.source}|{item.headline}\n".encode()
        )
    return h.hexdigest()


def generate_sentiment_corpus(seed: int) -> GeneratedCorpus:
    """Generate the full corpus deterministically from ``seed``."""
    rng = np.random.default_rng(np.random.SeedSequence([seed, 41]))
    aspects = ("policy", "supply", "demand", "weather", "trade")
    pending: list[tuple[date, str, str, str, list[LexiconEntry]]] = []

    def plant(
        when: date,
        commodity: str,
        phrases: list[LexiconEntry],
        frame: str,
        source: str | None = None,
    ) -> None:
        spec = BY_NAME[commodity]
        market = spec.markets[int(rng.integers(0, len(spec.markets)))].display
        if len(phrases) >= 2:
            headline = frame.format(
                first=phrases[0].phrase, second=phrases[1].phrase,
                commodity=spec.display, market=market,
            )
        elif phrases:
            headline = frame.format(
                phrase=phrases[0].phrase, commodity=spec.display, market=market
            )
        else:
            headline = frame.format(commodity=spec.display, market=market)
        if source is None:
            source = (
                _SOURCE_BY_ASPECT[phrases[0].aspect]
                if phrases
                else "industry bulletin"
            )
        pending.append((when, commodity, headline, source, phrases))

    def clear_item(when: date, commodity: str, sign_bias: int | None = None) -> None:
        aspect = aspects[int(rng.integers(0, len(aspects)))]
        sign = sign_bias if sign_bias is not None else (1 if rng.random() < 0.5 else -1)
        pool = _BY_ASPECT_SIGN[(aspect, sign)]
        first = pool[int(rng.integers(0, len(pool)))]
        phrases = [first]
        if rng.random() < 0.30:
            aspect2 = aspects[int(rng.integers(0, len(aspects)))]
            pool2 = _BY_ASPECT_SIGN[(aspect2, sign)]
            phrases.append(pool2[int(rng.integers(0, len(pool2)))])
            plant(when, commodity, phrases, _DOUBLE_FRAME)
            return
        frame = _SINGLE_FRAMES[int(rng.integers(0, len(_SINGLE_FRAMES)))]
        plant(when, commodity, phrases, frame)

    weeks = _mondays(CORPUS_START, CORPUS_END)
    for commodity in RICH_COMMODITIES:
        for monday in weeks:
            when = monday + timedelta(days=int(rng.integers(0, 5)))
            roll = rng.random()
            if roll < 0.58:
                clear_item(when, commodity)
            elif roll < 0.65:
                pos = [e for e in SENTIMENT_PACK_V1.lexicon if e.weight == 2 and e.polarity == 1]
                neg = [e for e in SENTIMENT_PACK_V1.lexicon if e.weight == 2 and e.polarity == -1]
                pair = [
                    pos[int(rng.integers(0, len(pos)))],
                    neg[int(rng.integers(0, len(neg)))],
                ]
                plant(when, commodity, pair, _AMBIGUOUS_FRAME, "industry bulletin")
            elif roll < 0.70:
                frame = _NONE_HEADLINES[int(rng.integers(0, len(_NONE_HEADLINES)))]
                plant(when, commodity, [], frame)

    # Clusters that agree with the dataset's planted events.
    for when, phrase in (
        (date(2025, 6, 18), "import duty raised"),
        (date(2025, 6, 27), "import duty raised"),
        (date(2025, 7, 8), "support price hike"),
        (date(2025, 7, 21), "export demand strong"),
    ):
        pending.append((when, "soybean", _cluster_headline("soybean", phrase), "ministry release", [_BY_PHRASE[phrase]]))
    for when, phrase in (
        (date(2024, 9, 5), "export ban imposed"),
        (date(2024, 9, 19), "export restrictions imposed"),
        (date(2024, 10, 3), "export ban imposed"),
        (date(2024, 10, 17), "buyer demand weak"),
    ):
        pending.append((when, "basmati_rice", _cluster_headline("basmati_rice", phrase), "ministry release", [_BY_PHRASE[phrase]]))
    for when, phrase in (
        (date(2025, 7, 10), "drought conditions persist"),
        (date(2025, 7, 28), "monsoon deficit widens"),
        (date(2025, 8, 14), "drought conditions persist"),
        (date(2025, 9, 2), "crop damage reported"),
    ):
        pending.append((when, "chili", _cluster_headline("chili", phrase), "weather desk", [_BY_PHRASE[phrase]]))

    # Groundnut: sparse on purpose — a dozen clear items over three
    # years. An index exists for their weeks; the estimation floors
    # are nowhere near met.
    groundnut_weeks = [weeks[i] for i in range(6, len(weeks), 13)][:12]
    for monday in groundnut_weeks:
        when = monday + timedelta(days=int(rng.integers(0, 5)))
        clear_item(when, "groundnut")

    # Coffee: exactly four items, weather-flavoured.
    for when, phrase in (
        (date(2025, 3, 11), "good rains reported"),
        (date(2025, 6, 17), "monsoon deficit widens"),
        (date(2025, 9, 9), "unseasonal rain damage"),
        (date(2025, 11, 18), "drought conditions persist"),
    ):
        pending.append((when, "coffee", _cluster_headline("coffee", phrase), "weather desk", [_BY_PHRASE[phrase]]))

    pending.sort(key=lambda row: (row[0], row[1], row[2]))
    items: list[SentimentItem] = []
    intents: list[PlantedIntent] = []
    per_year: dict[int, int] = {}
    for when, commodity, headline, source, phrases in pending:
        per_year[when.year] = per_year.get(when.year, 0) + 1
        item_id = f"NEWS-{when.year}-{per_year[when.year]:03d}"
        items.append(
            SentimentItem(
                item_id=item_id, commodity=commodity, item_date=when,
                source=source, headline=headline,
            )
        )
        aspect_scores: dict[str, int] = {}
        for entry in phrases:
            aspect_scores[entry.aspect] = (
                aspect_scores.get(entry.aspect, 0) + entry.polarity * entry.weight
            )
        planted_score = sum(aspect_scores.values())
        clarity = (
            "clear" if planted_score != 0 else ("ambiguous" if phrases else "none")
        )
        intents.append(
            PlantedIntent(
                item_id=item_id,
                planted_score=planted_score,
                aspect_scores=aspect_scores,
                clarity=clarity,  # type: ignore[arg-type]
            )
        )

    per_commodity: dict[str, int] = {}
    for item in items:
        per_commodity[item.commodity] = per_commodity.get(item.commodity, 0) + 1
    manifest = SentimentCorpusManifest(
        corpus_version=CORPUS_VERSION,
        seed=seed,
        item_count=len(items),
        per_commodity=per_commodity,
        first_date=items[0].item_date,
        last_date=items[-1].item_date,
        digest=_digest(items),
    )
    return GeneratedCorpus(items=items, intents=intents, manifest=manifest)


def _cluster_headline(commodity: str, phrase: str) -> str:
    spec = BY_NAME[commodity]
    market = spec.markets[0].display
    return _SINGLE_FRAMES[0].format(
        phrase=phrase, commodity=spec.display, market=market
    )
