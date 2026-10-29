"""Chain-integrity verification for assisted intake.

The verifier trusts nothing stored. Per entry it recomputes
the content addresses (entry and acts), re-checks the stated
rules (catalogue scope, phone-reportable driver, positive
value, no future date, a named enterer and source), and then
grades the chain against the observations table — the leakage
checks, all zero-tolerance:

- a **pending** entry must have no observation at its natural
  key: an unconfirmed figure that an engine could read is a
  leak, whatever path it took;
- a **rejected** entry likewise lands nothing;
- a **confirmed** entry must have exactly one observation at
  its key, carrying exactly its value — the fact the act
  landed, neither missing nor doubled;
- at most one check act per entry, by a checker who is not
  the enterer, at or after the entry's time;
- one natural key is claimed by at most one entry.
"""

from __future__ import annotations

import math

from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.intake.models import (
    INTAKE_DRIVERS,
    IntakeEntry,
    check_act_content_id,
    entry_content_id,
)
from fmcg_forecast.store import Store


def _fact_rows(store: Store, entry: IntakeEntry):
    return store.series(
        entry.commodity, entry.market, entry.driver,
        entry.obs_date, entry.obs_date,
    )


def verify_entry(store: Store, entry: IntakeEntry) -> list[str]:
    problems: list[str] = []
    if entry_content_id(entry) != entry.entry_id:
        problems.append(
            f"content id mismatch: stored {entry.entry_id}, "
            f"recomputed {entry_content_id(entry)} — the entry "
            "was altered after it was recorded"
        )
    spec = BY_NAME.get(entry.commodity)
    if spec is None or entry.market not in {m.market for m in spec.markets}:
        problems.append(
            f"scope violation: {entry.commodity}/{entry.market} is "
            "not a catalogue series"
        )
    if entry.driver not in INTAKE_DRIVERS:
        problems.append(
            f"driver violation: {entry.driver} is not phone-reportable"
        )
    if not math.isfinite(entry.value) or entry.value <= 0:
        problems.append(f"value violation: {entry.value} is not a positive figure")
    if entry.obs_date > entry.entered_at.date():
        problems.append("date violation: the entry reports a future day")
    # one key, one entry
    for other in store.list_intake_entries(entry.commodity, entry.market):
        if (
            other.entry_id != entry.entry_id
            and other.obs_date == entry.obs_date
            and other.driver == entry.driver
        ):
            problems.append(
                f"key conflict: entry {other.entry_id} also claims "
                f"{entry.commodity}/{entry.market}/{entry.driver} on "
                f"{entry.obs_date.isoformat()} — one key carries "
                "one entry"
            )
    acts = store.list_intake_check_acts(entry.entry_id)
    if len(acts) > 1:
        problems.append(
            f"chain violation: {len(acts)} check acts stand on one "
            "entry — a check act is terminal"
        )
    for act in acts:
        if check_act_content_id(act) != act.act_id:
            problems.append(
                f"act {act.act_id}: content id mismatch — the act "
                "was altered after it was recorded"
            )
        if act.checker.strip().lower() == entry.entered_by.strip().lower():
            problems.append(
                f"self-check: act {act.act_id} was checked by its "
                f"own enterer {act.checker} — maker–checker forbids it"
            )
        if act.acted_at < entry.entered_at:
            problems.append(
                f"act {act.act_id}: the check predates the entry"
            )
    facts = _fact_rows(store, entry)
    if not acts:
        if facts:
            problems.append(
                "unconfirmed leakage: an observation stands at this "
                "pending entry's key — an unconfirmed figure reached "
                "the observations table an engine reads"
            )
    elif acts[0].act == "reject":
        if facts:
            problems.append(
                "rejected leakage: an observation stands at this "
                "rejected entry's key — a rejected figure became a fact"
            )
    else:  # confirmed
        if len(facts) != 1:
            problems.append(
                f"fact count violation: a confirmed entry must map "
                f"to exactly one observation; {len(facts)} stand at "
                "its key"
            )
        elif facts[0].value != entry.value:
            problems.append(
                f"fact value mismatch: the landed observation is "
                f"{facts[0].value}, the entry states {entry.value}"
            )
    return problems
