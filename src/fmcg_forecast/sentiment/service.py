"""The sentiment service: extract, index, feed the engine, verify.

One workflow every surface shares:

- ``run_pipeline`` reads every stored item through the model port
  into a content-addressed extraction (idempotent: an item whose
  stored extraction already carries the computed content address
  is left alone), then computes the weekly index for every
  commodity that has items. An existing artefact whose content
  address DISAGREES with a fresh computation under the same pack
  is a conflict, raised loudly — artefacts are never overwritten.
- ``forecast_input`` is the forecast engine's provider: it turns
  the stored indices into the daily series the engine aligns
  (index value carried across its week), with the estimation
  floors from the pack riding along for the engine to judge. A
  commodity with no items at all returns None — sentiment is
  simply not in play for it, and the engine behaves exactly as it
  did before R4.
- ``verify_claims`` is the forecast service's commentary gate for
  sentiment: every sentiment sentence in a draft must cite items
  whose extractions support it (see verify.py).
"""

from __future__ import annotations

from datetime import date, timedelta

from fmcg_forecast.forecast.engine import SentimentInput
from fmcg_forecast.forecast.models import Forecast
from fmcg_forecast.modelport import ModelPort
from fmcg_forecast.sentiment.extract import build_extraction
from fmcg_forecast.sentiment.index import compute_index, week_bounds
from fmcg_forecast.sentiment.models import (
    SentimentExtraction,
    SentimentIndex,
    SentimentItem,
)
from fmcg_forecast.sentiment.pack import SentimentPack, load_sentiment_pack
from fmcg_forecast.sentiment.verify import (
    verify_extraction,
    verify_index,
    verify_sentiment_claims,
)


class SentimentConflictError(RuntimeError):
    """A stored artefact disagrees with a fresh computation under
    the same pack — the record was altered, or the pack changed
    without a version bump. Raised, never overwritten."""


class SentimentService:
    def __init__(self, store, model: ModelPort, pack: SentimentPack | None = None):
        self.store = store
        self.model = model
        self.pack = pack or load_sentiment_pack()

    # -- the pipeline ---------------------------------------------------
    def run_pipeline(self) -> dict:
        items = self.store.list_sentiment_items()
        extracted_new = 0
        already = 0
        unclassified = 0
        for item in items:
            reading = self.model.extract_sentiment(headline=item.headline)
            extraction = build_extraction(item, reading, self.pack, self.model.profile_name)
            existing = self.store.get_extraction(item.item_id)
            if existing is not None:
                if existing.extraction_id != extraction.extraction_id:
                    raise SentimentConflictError(
                        f"item {item.item_id} already carries extraction "
                        f"{existing.extraction_id} (pack {existing.pack_version}, "
                        f"profile {existing.model_profile}); a fresh computation "
                        f"gives {extraction.extraction_id} — refusing to overwrite"
                    )
                already += 1
            else:
                self.store.insert_extraction(extraction)
                extracted_new += 1
            if extraction.status == "unclassified":
                unclassified += 1

        indices_new = 0
        indices_on_record = 0
        commodities = sorted({i.commodity for i in items})
        for commodity in commodities:
            extractions = self.store.list_extractions(commodity)
            commodity_items = [i for i in items if i.commodity == commodity]
            if not commodity_items:
                continue
            first_monday, _ = week_bounds(commodity_items[0].item_date)
            last_monday, _ = week_bounds(commodity_items[-1].item_date)
            monday = first_monday
            while monday <= last_monday:
                index = compute_index(commodity, monday, extractions, self.pack)
                if index is not None:
                    existing_index = self.store.get_index(commodity, monday)
                    if existing_index is not None:
                        if existing_index.index_id != index.index_id:
                            raise SentimentConflictError(
                                f"index for {commodity} week {monday} already "
                                f"carries {existing_index.index_id}; a fresh "
                                f"computation gives {index.index_id} — "
                                "refusing to overwrite"
                            )
                        indices_on_record += 1
                    else:
                        self.store.insert_index(index)
                        indices_new += 1
                monday += timedelta(days=7)
        return {
            "pack_version": self.pack.version,
            "model_profile": self.model.profile_name,
            "items": len(items),
            "extractions_new": extracted_new,
            "extractions_on_record": already,
            "unclassified": unclassified,
            "indices_new": indices_new,
            "indices_on_record": indices_on_record,
        }

    # -- reads ------------------------------------------------------------
    def list_items(self, commodity: str | None = None) -> list[SentimentItem]:
        return self.store.list_sentiment_items(commodity)

    def get_item(self, item_id: str) -> SentimentItem | None:
        return self.store.get_sentiment_item(item_id)

    def get_extraction(self, item_id: str) -> SentimentExtraction | None:
        return self.store.get_extraction(item_id)

    def list_extractions(
        self, commodity: str | None = None
    ) -> list[SentimentExtraction]:
        return self.store.list_extractions(commodity)

    def list_indices(self, commodity: str) -> list[SentimentIndex]:
        return self.store.list_indices(commodity)

    def get_index(self, commodity: str, week_start: date) -> SentimentIndex | None:
        return self.store.get_index(commodity, week_start)

    # -- verification -------------------------------------------------------
    def verify_stored(self) -> dict:
        """Re-perform every stored extraction and index."""
        problems: list[str] = []
        items = {i.item_id: i for i in self.store.list_sentiment_items()}
        for extraction in self.store.list_extractions():
            item = items.get(extraction.item_id)
            if item is None:
                problems.append(
                    f"extraction {extraction.extraction_id} names item "
                    f"{extraction.item_id}, which is not on record"
                )
                continue
            problems.extend(verify_extraction(extraction, item, self.pack))
        for commodity in sorted({i.commodity for i in items.values()}):
            extractions = self.store.list_extractions(commodity)
            for index in self.store.list_indices(commodity):
                problems.extend(verify_index(index, extractions, self.pack))
        return {"problems": problems}

    # -- the forecast engine's provider --------------------------------------
    def daily_series(self, commodity: str, as_of: date) -> dict[date, float]:
        """Index values carried daily, using only fully-ended weeks.

        A week joins the series only once its Sunday is on or
        before ``as_of`` — the engine never sees a partial week,
        so an index value can never carry items dated after the
        forecast's own as_of.
        """
        daily: dict[date, float] = {}
        for index in self.store.list_indices(commodity):
            if index.week_end > as_of:
                continue
            day = index.week_start
            while day <= index.week_end:
                daily[day] = index.value
                day += timedelta(days=1)
        return daily

    def forecast_input(
        self, commodity: str, as_of: date
    ) -> SentimentInput | None:
        """The engine input for one commodity at one as_of.

        None when the commodity has no items at all (sentiment not
        in play). Otherwise the daily series plus the citation
        meta: the most recent fully-ended index, and up to three
        of its items whose readings agree with its sign, strongest
        first — the items commentary may cite.
        """
        items = self.store.list_sentiment_items(commodity)
        if not items:
            return None
        daily = self.daily_series(commodity, as_of)
        usable = [
            idx for idx in self.store.list_indices(commodity) if idx.week_end <= as_of
        ]
        cited: list[str] = []
        latest_value: float | None = None
        latest_week: date | None = None
        if usable:
            latest = usable[-1]
            latest_value = latest.value
            latest_week = latest.week_start
            if abs(latest.value) >= 0.05:
                sign = 1 if latest.value > 0 else -1
                by_id = {e.extraction_id: e for e in self.store.list_extractions(commodity)}
                agreeing = []
                for extraction_id in latest.extraction_ids:
                    extraction = by_id.get(extraction_id)
                    if (
                        extraction is not None
                        and extraction.direction is not None
                        and (1 if extraction.direction > 0 else -1) == sign
                    ):
                        agreeing.append(extraction)
                agreeing.sort(
                    key=lambda e: (-(e.strength or 0.0), e.item_date, e.item_id)
                )
                cited = [e.item_id for e in agreeing[:3]]
        return SentimentInput(
            daily={d.isoformat(): v for d, v in sorted(daily.items())},
            cited_item_ids=cited,
            latest_index_value=latest_value,
            latest_week_start=latest_week,
            pack_version=self.pack.version,
            min_aligned_days=self.pack.min_aligned_days,
            min_span_days=self.pack.min_span_days,
            recency_days=self.pack.recency_days,
        )

    # -- the commentary gate ---------------------------------------------------
    def verify_claims(self, text: str, forecast: Forecast) -> list[str]:
        items = {
            i.item_id: i
            for i in self.store.list_sentiment_items(forecast.commodity)
        }
        # A claim may also miscite another commodity's item; those
        # must be resolvable to be judged wrong-commodity rather
        # than merely unknown, so the lookup covers the whole corpus.
        for item in self.store.list_sentiment_items():
            items.setdefault(item.item_id, item)
        extractions = {
            e.item_id: e for e in self.store.list_extractions()
        }
        return verify_sentiment_claims(
            text, forecast.commodity, items, extractions, self.pack
        )
