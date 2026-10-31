"""The screening service: judge an item, record the verdict.

The pipeline's choke point. Every sentiment item passes
here before any model port sees its headline:

- an item the pack's rules do not touch passes — the
  service returns None and the pipeline hands the port
  the item's headline byte-identical, exactly as stored;
- an item any rule touches is quarantined: this service
  stores its record (insert-only, content-addressed)
  and the pipeline skips it — no extraction, no index,
  no citation, no model call. The record is the item's
  whole footprint, left for a human to review.

Recording is idempotent: re-screening an item whose
record already stands returns the standing record. A
stored record whose content address DISAGREES with a
fresh judgement under the same pack is a conflict,
raised loudly — artefacts are never overwritten.
"""

from __future__ import annotations

from fmcg_forecast.screening.engine import judge_item
from fmcg_forecast.screening.models import ScreeningRecord
from fmcg_forecast.screening.pack import ScreeningPack, load_screening_pack
from fmcg_forecast.sentiment.models import SentimentItem
from fmcg_forecast.store import Store


class ScreeningConflictError(RuntimeError):
    """A stored screening record disagrees with a fresh
    judgement under the same pack — the record was
    altered, or the pack changed without a version bump.
    Raised, never overwritten."""


class ScreeningService:
    def __init__(self, store: Store, pack: ScreeningPack | None = None):
        self.store = store
        self.pack = pack or load_screening_pack()

    def screen_item(self, item: SentimentItem) -> ScreeningRecord | None:
        """Judge one item; store and return its record if flagged.

        Returns None for a passing item. An already-standing
        record is returned as-is when a fresh judgement agrees
        with it, and a conflict is raised when it does not.
        """
        fresh = judge_item(item, self.pack)
        existing = self.store.get_screening_record(item.item_id)
        if fresh is None:
            if existing is not None:
                raise ScreeningConflictError(
                    f"item {item.item_id} carries quarantine record "
                    f"{existing.record_id} (pack {existing.pack_version}) "
                    "but a fresh judgement under pack "
                    f"{self.pack.version} passes it — refusing to "
                    "let the record stand unjudged"
                )
            return None
        if existing is not None:
            if existing.record_id != fresh.record_id:
                raise ScreeningConflictError(
                    f"item {item.item_id} already carries quarantine "
                    f"record {existing.record_id} (pack "
                    f"{existing.pack_version}); a fresh judgement gives "
                    f"{fresh.record_id} — refusing to overwrite"
                )
            return existing
        self.store.insert_screening_record(fresh)
        return fresh

    def get_record(self, item_id: str) -> ScreeningRecord | None:
        return self.store.get_screening_record(item_id)

    def list_records(
        self, commodity: str | None = None
    ) -> list[ScreeningRecord]:
        return self.store.list_screening_records(commodity)

    def quarantined_item_ids(self) -> set[str]:
        return {r.item_id for r in self.store.list_screening_records()}
