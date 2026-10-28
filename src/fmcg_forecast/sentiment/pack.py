"""The sentiment pack — the lexicon and the formulas, as data.

Law 3's mechanics are stated here, versioned, never buried in
code: which phrases carry a signal (and for which aspect, with
what polarity and weight), when a headline's signal is strong
enough to classify, how direction and strength derive from the
raw score, how the weekly index decays and windows, and how much
index history the forecast engine needs before a sentiment
contribution is estimable at all. A change to any of it is a new
pack version, and every extraction and index names the version it
was built under.

Direction convention: sentiment is read from the buying desk's
side of the price — a *bullish* item is one pointing at HIGHER
prices (an export ban points down: it traps supply at home; a
support-price hike points up: it puts a floor under the market).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LexiconEntry(BaseModel):
    phrase: str = Field(description="Matched on word boundaries, case-insensitive")
    aspect: str = Field(description="policy | supply | demand | weather | trade")
    polarity: int = Field(description="+1 points at higher prices, -1 at lower")
    weight: int = Field(description="Stated strength of the signal, 1 or 2")


class SentimentPack(BaseModel):
    version: str
    lexicon: list[LexiconEntry]
    strong_score: int = Field(
        description="|score| at or above this earns the full direction "
        "step (+/-1.0); below it a classified item reads +/-0.5"
    )
    strength_divisor: float = Field(
        description="strength = min(1, |score| / strength_divisor)"
    )
    index_window_days: int = Field(
        description="The index for a week aggregates classified items "
        "in the trailing window of this many days ending at the "
        "week's Sunday"
    )
    index_half_life_days: float = Field(
        description="Item weight decays as 0.5 ** (age_days / half_life) "
        "with age measured back from the week's Sunday"
    )
    min_aligned_days: int = Field(
        description="Forecast estimation floor: the sentiment driver "
        "is estimable only when at least this many price days carry "
        "an index value inside the estimation window"
    )
    min_span_days: int = Field(
        description="... spanning at least this many calendar days"
    )
    recency_days: int = Field(
        description="... and the newest index-covered day is no older "
        "than this, relative to the forecast's as_of"
    )
    claim_positive_words: list[str] = Field(
        description="Words a commentary sentence may use for a "
        "positive sentiment claim"
    )
    claim_negative_words: list[str]
    claim_mixed_words: list[str]
    claim_mixed_tolerance: float = Field(
        description="A 'mixed' claim verifies when the cited items' "
        "weighted mean direction sits within +/- this of zero"
    )
    extraction_rule: str = Field(description="The extraction algorithm, stated")
    index_rule: str = Field(description="The index formula, stated")


_LEXICON: tuple[tuple[str, str, int, int], ...] = (
    # policy
    ("support price hike", "policy", +1, 2),
    ("support price raised", "policy", +1, 2),
    ("import duty raised", "policy", +1, 2),
    ("import duty cut", "policy", -1, 2),
    ("export ban imposed", "policy", -1, 2),
    ("export restrictions imposed", "policy", -1, 2),
    ("export curbs eased", "policy", +1, 1),
    # supply
    ("arrivals surge", "supply", -1, 2),
    ("arrivals thin", "supply", +1, 1),
    ("bumper harvest expected", "supply", -1, 2),
    ("harvest shortfall feared", "supply", +1, 2),
    ("crop damage reported", "supply", +1, 2),
    ("ample stocks reported", "supply", -1, 1),
    ("short supply reported", "supply", +1, 2),
    # demand
    ("export demand strong", "demand", +1, 2),
    ("buyer demand weak", "demand", -1, 2),
    ("festival demand picks up", "demand", +1, 1),
    ("offtake slow", "demand", -1, 1),
    ("miller demand firm", "demand", +1, 1),
    # weather
    ("monsoon deficit widens", "weather", +1, 2),
    ("drought conditions persist", "weather", +1, 2),
    ("good rains reported", "weather", -1, 1),
    ("unseasonal rain damage", "weather", +1, 1),
    # trade
    ("global prices rally", "trade", +1, 1),
    ("global prices slide", "trade", -1, 1),
    ("imports surge at ports", "trade", -1, 1),
    ("export enquiries rise", "trade", +1, 1),
)

SENTIMENT_PACK_V1 = SentimentPack(
    version="2026.10.1",
    lexicon=[
        LexiconEntry(phrase=p, aspect=a, polarity=pol, weight=w)
        for p, a, pol, w in _LEXICON
    ],
    strong_score=3,
    strength_divisor=4.0,
    index_window_days=14,
    index_half_life_days=7.0,
    min_aligned_days=200,
    min_span_days=500,
    recency_days=28,
    claim_positive_words=["supportive", "bullish", "favourable", "favorable"],
    claim_negative_words=["headwind", "bearish", "adverse"],
    claim_mixed_words=["mixed", "neutral"],
    claim_mixed_tolerance=0.2,
    extraction_rule=(
        "match lexicon phrases on word boundaries, longest phrase "
        "first, non-overlapping; score = sum of polarity x weight "
        "over matches; no matches -> unclassified (no signal); "
        "score == 0 -> unclassified (signals cancel); otherwise "
        "direction = sign(score) x (1.0 if |score| >= strong_score "
        "else 0.5), strength = min(1, |score| / strength_divisor), "
        "aspects = the per-aspect signed sums that are non-zero"
    ),
    index_rule=(
        "for one commodity x ISO week: take classified extractions "
        "whose item date falls in the trailing index_window_days "
        "ending at the week's Sunday; weight each by strength x "
        "0.5 ** (age_days / half_life) with age measured back from "
        "that Sunday; value = sum(direction x weight) / sum(weight); "
        "aspect sub-indices are the same mean restricted to "
        "extractions carrying the aspect; a window with no "
        "classified item yields NO index for the week (absent, "
        "never zero)"
    ),
)


def load_sentiment_pack(version: str | None = None) -> SentimentPack:
    """Fail-closed loader: only the shipped pack exists in R4.

    An unknown version is an error, never a silent fallback — an
    extraction must name the pack it was actually read under.
    """
    if version is None or version == SENTIMENT_PACK_V1.version:
        return SENTIMENT_PACK_V1
    raise ValueError(f"unknown sentiment pack version: {version!r}")
