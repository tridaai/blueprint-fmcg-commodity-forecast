"""Assisted-intake artefacts: entries and check acts.

An *intake entry* is a phoned-in figure as a desk assistant
recorded it — a stated observation (commodity, market, date,
driver, value), the named enterer, when they entered it, and
the source note that says where the figure came from. It is
content-addressed over the whole statement and insert-only:
an entry is never edited, and it is **not** a fact. Engines
read the observations table, and a pending entry is not in
it — an unconfirmed entry is invisible to every engine read
by construction, not by a filter someone must remember.

A *check act* is the second person's decision, attributed and
insert-only: confirm or reject, by a named checker whose name
must differ from the enterer's. An entry's state is the fold
of its check acts — pending with none, confirmed or rejected
with its one act (a second act is a chain violation the
verifier grades). On confirmation the stated figure becomes
an Observation through the store's ordinary insert path, and
the confirmed fact's lineage is the entry plus both names:
the entry, the enterer, and this act's checker.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# The drivers a phoned-in figure may state: a price or an
# arrivals figure, as the desk receives them by phone. Other
# drivers are instrumented series, not phone reports — an
# entry naming one is refused, not quietly stored.
INTAKE_DRIVERS: tuple[str, ...] = ("modal_price", "arrivals")


def _content_id(prefix: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return prefix + hashlib.sha256(canonical.encode()).hexdigest()[:16]


class IntakeEntry(BaseModel):
    entry_id: str = Field(description="Content address: ENT-<sha256[:16]>")
    commodity: str
    market: str
    obs_date: date = Field(description="The day the figure is about")
    driver: str = Field(description="modal_price | arrivals — the phone-reportable drivers")
    value: float = Field(description="The figure as phoned in, in the driver's stated unit")
    entered_by: str = Field(description="The named assistant who took the call (the maker)")
    entered_by_role: str
    entered_at: datetime = Field(description="When the entry was recorded")
    source_note: str = Field(
        description="Where the figure came from, stated — a "
        "market contact, a phone call, a message; never blank"
    )


def entry_content_id(entry: IntakeEntry) -> str:
    payload = entry.model_dump(mode="json", exclude={"entry_id"})
    return _content_id("ENT-", payload)


class IntakeCheckAct(BaseModel):
    act_id: str = Field(description="Content address: INA-<sha256[:16]>")
    entry_id: str
    act: Literal["confirm", "reject"]
    checker: str = Field(
        description="The named second person (the checker) — "
        "must differ from the entry's enterer"
    )
    checker_role: str
    acted_at: datetime
    note: str = ""


def check_act_content_id(act: IntakeCheckAct) -> str:
    payload = act.model_dump(mode="json", exclude={"act_id"})
    return _content_id("INA-", payload)
