"""The screening artefact: a quarantine record.

One record per flagged item, content-addressed and
insert-only like every other artefact in this blueprint.
The record carries the item's headline VERBATIM — the
screen never edits the text it judges, so the record is
the evidence a human reviewer reads — plus the rules
that matched, in pack order, and the categories they
belong to. The outcome has one value: quarantined. A
quarantined item has no extraction, joins no index and
is cited by no commentary; the record is the whole of
its footprint in the system.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class ScreeningRecord(BaseModel):
    """The quarantine record for one flagged item (F20-AS2)."""

    record_id: str = Field(description="Content address: SRN-<sha256[:12]>")
    item_id: str
    commodity: str
    item_date: date
    headline: str = Field(
        description="The item's headline, verbatim — evidence, "
        "never edited by the screen"
    )
    matched_rule_ids: list[str] = Field(
        description="The pack rules that matched, in pack order"
    )
    categories: list[str] = Field(
        description="The matched rules' categories, sorted, deduped"
    )
    pack_version: str
    outcome: Literal["quarantined"] = "quarantined"


def screening_content_id(record: ScreeningRecord) -> str:
    payload = record.model_dump(mode="json", exclude={"record_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "SRN-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]
