"""Sentiment artefacts (R4, Law 3).

An *item* is data: a planted news/policy headline with provenance
(source label, date, commodity). An *extraction* is the structured
reading the model port produced for one item — direction in stated
steps, strength, the aspects it speaks to, and the exact lexicon
phrases that fired — pinned to the item and the pack version. An
*index* is the weekly number computed in code from the stored
extractions over a trailing window; it is the only sentiment
quantity the forecast engine ever sees.

Extractions and indices are content-addressed like every other
artefact in this blueprint: any later edit to a direction, a
weight or a window breaks the id and is detectable. The planted
intent behind the corpus is NOT modelled here — it is grading-side
data (see corpus.py) and the scoring path never reads it.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

ASPECTS: tuple[str, ...] = ("policy", "supply", "demand", "weather", "trade")

# Direction lives on a stated ladder: sign x intensity. There is no
# classified zero — a headline with no net direction is unclassified,
# never a neutral reading.
DIRECTION_STEPS: tuple[float, ...] = (-1.0, -0.5, 0.5, 1.0)


class SentimentItem(BaseModel):
    """One news/policy item, as data with provenance."""

    item_id: str = Field(description="NEWS-<year>-<seq>, assigned at planting in date order")
    commodity: str
    item_date: date
    source: str = Field(
        description="Generic source label (ministry release, trade wire, "
        "market report, weather desk, industry bulletin) — provenance, "
        "never a real publication or company name"
    )
    headline: str = Field(description="The planted headline text the extractor reads")


class SentimentExtraction(BaseModel):
    """The model port's structured reading of one item.

    ``status`` is classified only when the headline carries a net
    signed signal at or above the pack's stated margin. Anything
    else — no signal, or signals that cancel — is ``unclassified``
    with the reason named; the extractor never forces a direction.
    """

    extraction_id: str
    item_id: str
    commodity: str
    item_date: date
    model_profile: str
    pack_version: str
    status: Literal["classified", "unclassified"]
    score: int = Field(
        description="The raw signed lexicon score (sum of polarity x "
        "weight over matched phrases), recorded either way — it is "
        "the diagnostic a re-performance recomputes"
    )
    direction: float | None = Field(
        description="One of the stated steps (-1, -0.5, +0.5, +1); "
        "None when unclassified"
    )
    strength: float | None = Field(
        description="min(1, |score| / 4) — in quarter steps for "
        "integer scores; None when unclassified"
    )
    aspects: dict[str, int] = Field(
        description="Signed lexicon score per aspect that fired "
        "(zero-sum aspects are omitted)"
    )
    matched_phrases: list[str] = Field(
        description="The lexicon phrases found in the headline, in "
        "match order — the extraction's evidence"
    )
    reason: str | None = Field(
        description="Why the item is unclassified, when it is"
    )


class SentimentIndex(BaseModel):
    """One commodity x ISO week of computed sentiment.

    The value is the strength-weighted, age-decayed mean direction
    over the classified extractions in the trailing window (the
    pack states the window and the half-life), so every index value
    re-performs from the stored extractions alone.
    """

    index_id: str
    commodity: str
    week_start: date = Field(description="Monday of the ISO week")
    week_end: date = Field(description="Sunday of the ISO week")
    value: float = Field(description="Weighted mean direction in [-1, 1], 4dp")
    n_items: int = Field(description="Classified extractions inside the window")
    extraction_ids: list[str] = Field(
        description="The extractions the value was computed from, sorted"
    )
    aspect_values: dict[str, float] = Field(
        description="Per-aspect sub-index: the same weighted mean "
        "restricted to extractions carrying that aspect"
    )
    pack_version: str
    window_days: int
    half_life_days: float


class SentimentCorpusManifest(BaseModel):
    """The corpus as a dataset artefact — counts and a digest.

    Deliberately carries NO planted intent: the manifest is product
    data (what the corpus is), while the intent (what each item was
    planted to mean) is grading-side and lives behind the grading
    store.
    """

    corpus_version: str
    seed: int
    item_count: int
    per_commodity: dict[str, int]
    first_date: date
    last_date: date
    digest: str = Field(description="SHA-256 over the canonical item rows")
