"""Re-performance verification for the screening layer.

Every check trusts nothing stored:

- a record re-performs: the item it names is on record,
  the headline it carries is that item's headline
  byte-for-byte, the rules it names are exactly the
  engine's fresh judgement over that headline, and its
  content address re-derives;
- completeness runs both ways: every item the engine
  flags has a record (a flagged item with none was
  screened by nobody — the pipeline would either leak
  it to the port or drop it silently), and no record
  stands for an item the engine passes (a quarantine
  without a judgement is a suppression, not a screen);
- the quarantine holds: no extraction exists for a
  flagged item — an extraction on a quarantined item
  means its headline reached the model port, which is
  the one thing this layer exists to prevent.
"""

from __future__ import annotations

from fmcg_forecast.screening.engine import judge_item
from fmcg_forecast.screening.models import screening_content_id
from fmcg_forecast.screening.pack import ScreeningPack, load_screening_pack
from fmcg_forecast.store import Store


def verify_screening(
    store: Store, pack: ScreeningPack | None = None
) -> list[str]:
    pack = pack or load_screening_pack()
    problems: list[str] = []
    items = {i.item_id: i for i in store.list_sentiment_items()}
    records = store.list_screening_records()
    recorded: set[str] = set()
    for record in records:
        recorded.add(record.item_id)
        if screening_content_id(record) != record.record_id:
            problems.append(
                f"content id mismatch on {record.record_id} — the "
                "record was altered after screening"
            )
        if record.pack_version != pack.version:
            problems.append(
                f"record {record.record_id} was judged under pack "
                f"{record.pack_version}, cannot re-perform under "
                f"{pack.version}"
            )
            continue
        item = items.get(record.item_id)
        if item is None:
            problems.append(
                f"record {record.record_id} names item "
                f"{record.item_id}, which is not on record"
            )
            continue
        if record.headline != item.headline:
            problems.append(
                f"record {record.record_id} carries a headline that "
                f"differs from item {item.item_id}'s stored headline "
                "— the screen's evidence must be verbatim"
            )
        fresh = judge_item(item, pack)
        if fresh is None:
            problems.append(
                f"record {record.record_id} quarantines item "
                f"{item.item_id}, which a fresh judgement passes — "
                "a quarantine without a judgement"
            )
        elif fresh.record_id != record.record_id:
            problems.append(
                f"record {record.record_id} does not re-perform: a "
                f"fresh judgement gives {fresh.record_id} "
                f"(rules {fresh.matched_rule_ids})"
            )
    for item in items.values():
        if judge_item(item, pack) is not None and item.item_id not in recorded:
            problems.append(
                f"item {item.item_id} is flagged by the pack but "
                "carries no screening record — it was never "
                "quarantined"
            )
    extracted = {e.item_id for e in store.list_extractions()}
    for item_id in sorted(recorded & extracted):
        problems.append(
            f"item {item_id} is quarantined and extracted — its "
            "headline reached the model port despite the screen"
        )
    return problems
