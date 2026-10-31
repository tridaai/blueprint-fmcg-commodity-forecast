"""Re-performance verification for sentiment artefacts + claims.

Three checks, all trusting nothing stored:

- an *extraction* re-performs by re-running the pack's stated
  rule over the item's headline (offline readings; a hosted
  profile's artefact is checked for internal consistency against
  the same rule's shape — direction on the ladder, aspects
  summing to the score, content address intact);
- an *index* re-performs by recomputing it from the stored
  extractions it names;
- a *sentiment claim in commentary* — a sentiment sentence
  carrying a direction word from the pack's claim vocabulary, or
  citing items — verifies only when it cites items whose stored
  extractions support the direction the sentence claims. A claim
  citing no items, citing another commodity's items, citing
  unclassified items, or claiming a direction the cited readings
  do not support is a problem — and the forecast service refuses
  the whole commentary over it. (A bare figure statement about
  the index claims no direction and cites nothing; the figure
  verifier disciplines its number.) Mood without provenance
  never reaches the desk.
"""

from __future__ import annotations

import hashlib
import re

from fmcg_forecast.sentiment.extract import (
    build_extraction,
    extract_headline,
    extraction_content_id,
)
from fmcg_forecast.sentiment.index import compute_index, index_content_id
from fmcg_forecast.sentiment.models import (
    DIRECTION_STEPS,
    SentimentExtraction,
    SentimentIndex,
    SentimentItem,
)
from fmcg_forecast.sentiment.pack import SentimentPack

_ITEM_ID_RE = re.compile(r"NEWS-\d{4}-\d{3}")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def verify_corpus_integrity(store) -> list[str]:
    """Re-perform the corpus against its manifest (R17).

    The load path asserts the manifest digest once, at
    load; until this check nothing re-performed it, so a
    corpus edited after load — items planted around the
    load path to swing an index, or items quietly
    dropped — verified clean on the strength of its
    surviving extractions. The digest is recomputed over
    the stored items in the manifest's canonical order
    (item date, then id — the order the generator
    assigns ids in) and compared with the manifest on
    record, count first, then digest. A store with no
    manifest has nothing to re-perform against: the
    planted attack fixtures stand in such stores, and
    this check is silent there by design.
    """
    manifest = store.get_sentiment_manifest()
    if manifest is None:
        return []
    items = store.list_sentiment_items()
    problems: list[str] = []
    if len(items) != manifest.item_count:
        problems.append(
            f"corpus carries {len(items)} items but its manifest "
            f"({manifest.corpus_version}) names {manifest.item_count} — "
            "the corpus on record is not the corpus that was loaded"
        )
    digest = hashlib.sha256()
    for item in sorted(items, key=lambda i: (i.item_date, i.item_id)):
        digest.update(
            f"{item.item_id}|{item.commodity}|{item.item_date.isoformat()}|"
            f"{item.source}|{item.headline}\n".encode()
        )
    if digest.hexdigest() != manifest.digest:
        problems.append(
            "corpus digest mismatch: the stored items do not "
            f"re-perform to manifest {manifest.corpus_version}'s "
            "digest — the corpus was altered after load"
        )
    return problems


def verify_extraction(
    extraction: SentimentExtraction, item: SentimentItem, pack: SentimentPack
) -> list[str]:
    """Return the problems with one stored extraction."""
    problems: list[str] = []
    if extraction.item_id != item.item_id or extraction.commodity != item.commodity:
        problems.append(
            f"extraction {extraction.extraction_id} does not belong to "
            f"item {item.item_id}"
        )
        return problems
    if extraction_content_id(extraction) != extraction.extraction_id:
        problems.append(
            f"content id mismatch on {extraction.extraction_id} — the "
            "artefact was altered after extraction"
        )
    if extraction.pack_version != pack.version:
        problems.append(
            f"extraction was read under pack {extraction.pack_version}, "
            f"cannot re-perform under {pack.version}"
        )
        return problems
    if extraction.status == "classified":
        if extraction.direction not in DIRECTION_STEPS:
            problems.append(
                f"direction {extraction.direction} is not on the stated ladder"
            )
        if sum(extraction.aspects.values()) != extraction.score:
            problems.append("aspect scores do not sum to the recorded score")
    if extraction.model_profile == "offline":
        expected = build_extraction(
            item, extract_headline(item.headline, pack), pack, "offline"
        )
        if expected.extraction_id != extraction.extraction_id:
            problems.append(
                "offline re-performance disagrees: re-extracting the "
                f"headline gives {expected.extraction_id}, the stored "
                f"artefact is {extraction.extraction_id}"
            )
    return problems


def verify_index(
    index: SentimentIndex,
    extractions: list[SentimentExtraction],
    pack: SentimentPack,
) -> list[str]:
    """Recompute one index from the extractions it names."""
    problems: list[str] = []
    if index_content_id(index) != index.index_id:
        problems.append(
            f"content id mismatch on {index.index_id} — the artefact "
            "was altered after computation"
        )
    if index.pack_version != pack.version:
        problems.append(
            f"index was built under pack {index.pack_version}, cannot "
            f"re-perform under {pack.version}"
        )
        return problems
    by_id = {e.extraction_id: e for e in extractions}
    named = [by_id[i] for i in index.extraction_ids if i in by_id]
    if len(named) != len(index.extraction_ids):
        problems.append("index names extractions that are not on record")
        return problems
    expected = compute_index(index.commodity, index.week_start, named, pack)
    if expected is None:
        problems.append("re-performance finds no classified items in the window")
    elif expected.index_id != index.index_id:
        problems.append(
            f"index does not re-perform: recomputed {expected.index_id} "
            f"(value {expected.value}), stored {index.index_id} "
            f"(value {index.value})"
        )
    return problems


def verify_sentiment_claims(
    text: str,
    commodity: str,
    items: dict[str, SentimentItem],
    extractions: dict[str, SentimentExtraction],
    pack: SentimentPack,
) -> list[str]:
    """Check every sentiment claim in ``text`` against the record.

    ``items`` / ``extractions`` are keyed by item id. A sentiment
    claim is a sentence that mentions sentiment and carries a
    direction word or an item citation; claims are verified as
    stated in the module docstring. Sentences that never mention
    sentiment are not this verifier's business (the figure
    verifier disciplines their numbers separately).
    """
    problems: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(text.strip()):
        if "sentiment" not in sentence.lower():
            continue
        lowered = sentence.lower()
        cited = _ITEM_ID_RE.findall(sentence)
        claimed: int | None = None
        if any(re.search(rf"\b{w}\b", lowered) for w in pack.claim_positive_words):
            claimed = 1
        elif any(re.search(rf"\b{w}\b", lowered) for w in pack.claim_negative_words):
            claimed = -1
        elif any(re.search(rf"\b{w}\b", lowered) for w in pack.claim_mixed_words):
            claimed = 0
        if claimed is None and not cited:
            # A bare figure statement ("Sentiment index (latest
            # week): -0.5000.") claims no direction and cites
            # nothing — the figure verifier disciplines its number;
            # it is not a claim. A citation without a direction, or
            # a direction without a citation, IS a claim and fails
            # below.
            continue
        if claimed is None:
            problems.append(
                f"sentiment claim states no direction the pack recognises: "
                f"{sentence.strip()!r}"
            )
            continue
        if not cited:
            problems.append(
                f"sentiment claim cites no items: {sentence.strip()!r}"
            )
            continue
        weighted = 0.0
        total = 0.0
        usable = True
        for item_id in cited:
            item = items.get(item_id)
            extraction = extractions.get(item_id)
            if item is None or extraction is None:
                problems.append(
                    f"sentiment claim cites {item_id}, which is not on record"
                )
                usable = False
                continue
            if item.commodity != commodity:
                problems.append(
                    f"sentiment claim cites {item_id} — an item about "
                    f"{item.commodity} — in {commodity} commentary"
                )
                usable = False
                continue
            if extraction.status != "classified" or extraction.direction is None:
                problems.append(
                    f"sentiment claim cites {item_id}, whose extraction "
                    "is unclassified — it supports no direction"
                )
                usable = False
                continue
            weighted += extraction.direction * float(extraction.strength)
            total += float(extraction.strength)
        if not usable or total == 0.0:
            continue
        aggregate = weighted / total
        if claimed == 1 and not aggregate > 0:
            problems.append(
                f"sentiment claim says positive but the cited items "
                f"aggregate to {aggregate:.4f}: {sentence.strip()!r}"
            )
        elif claimed == -1 and not aggregate < 0:
            problems.append(
                f"sentiment claim says negative but the cited items "
                f"aggregate to {aggregate:.4f}: {sentence.strip()!r}"
            )
        elif claimed == 0 and abs(aggregate) > pack.claim_mixed_tolerance:
            problems.append(
                f"sentiment claim says mixed but the cited items "
                f"aggregate to {aggregate:.4f}: {sentence.strip()!r}"
            )
    return problems
