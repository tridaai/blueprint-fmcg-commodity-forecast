"""The corpus load path: items to the store, intents to grading.

Loading is idempotent at this level, like the dataset load: if
the store already carries a corpus manifest for the same seed and
digest, the load verifies and stops (the stores themselves are
insert-only and would refuse a duplicate write). This module is
part of the load path, so it may touch the grading store — the
scoring path may not (see the package's isolation law).
"""

from __future__ import annotations

import logging

from fmcg_forecast.sentiment.corpus import generate_sentiment_corpus
from fmcg_forecast.sentiment.grading import SentimentGradingStore
from fmcg_forecast.store import SqlStore

log = logging.getLogger("fmcg.sentiment.load")


def load_sentiment_corpus(
    store: SqlStore, grading_store: SentimentGradingStore, seed: int
) -> dict:
    """Generate and persist the corpus once; return the load state."""
    corpus = generate_sentiment_corpus(seed)
    existing = store.get_sentiment_manifest()
    already = bool(
        existing
        and existing.seed == corpus.manifest.seed
        and existing.digest == corpus.manifest.digest
    )
    if already:
        log.info(
            "sentiment corpus already loaded: %s items, digest %s",
            corpus.manifest.item_count,
            corpus.manifest.digest[:16],
        )
        return {
            "already_loaded": True,
            "items_written": 0,
            "intents_written": 0,
            "item_count": corpus.manifest.item_count,
        }
    items_n = store.insert_sentiment_items(corpus.items)
    intents_n = grading_store.insert_intents(corpus.intents)
    store.save_sentiment_manifest(corpus.manifest)
    stored = store.get_sentiment_manifest()
    assert stored is not None and stored.digest == corpus.manifest.digest, (
        "corpus digest mismatch after load"
    )
    assert grading_store.count() == len(corpus.intents), (
        "intent count mismatch after load"
    )
    log.info(
        "sentiment corpus persisted: items=%s intents=%s", items_n, intents_n
    )
    return {
        "already_loaded": False,
        "items_written": items_n,
        "intents_written": intents_n,
        "item_count": corpus.manifest.item_count,
    }
