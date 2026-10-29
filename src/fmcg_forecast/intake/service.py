"""The assisted-intake workflow: enter, check, land — or not.

The rules are the maker–checker discipline, enforced here and
nowhere else:

- an entry names its enterer and its source; placeholder
  names are refused, as at every gate in this repo;
- one natural key (commodity, market, date, driver) carries
  at most one entry and at most one fact: an entry for a key
  the store already holds, or that another entry already
  claims, is refused — so a pending entry maps to exactly
  one fact when it lands, and two entries can never race
  the same fact into existence;
- the checker must be a second, named person: an enterer
  confirming or rejecting their own entry is refused
  (self-check), whatever the names' capitalisation;
- a check act is terminal — a checked entry admits no
  second act;
- confirmation lands the figure through the store's
  ordinary observation insert path, and only then records
  the act: the fact exists because the act exists, and the
  pair the verifier re-performs is (entry, act, fact).
"""

from __future__ import annotations

import math
from datetime import datetime

from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.intake.models import (
    INTAKE_DRIVERS,
    IntakeCheckAct,
    IntakeEntry,
    check_act_content_id,
    entry_content_id,
)
from fmcg_forecast.models import DRIVER_UNITS, Observation
from fmcg_forecast.store import Store

_PLACEHOLDER_NAMES = {"", "tbd", "test", "user", "admin", "someone", "n/a", "na"}


def _require_named(value: str, field: str) -> str:
    cleaned = (value or "").strip()
    if cleaned.lower() in _PLACEHOLDER_NAMES or len(cleaned) < 2:
        raise IntakeValidationError(
            f"{field} must be a named human — an intake act by "
            f"{value!r} cannot be attributed, so it is refused"
        )
    return cleaned


class IntakeValidationError(ValueError):
    """An entry or act breaks the stated rules."""


class IntakeNotFoundError(LookupError):
    """No intake entry with that id."""


class IntakeStateError(RuntimeError):
    """The entry's folded state does not admit the requested act."""


class IntakeService:
    def __init__(self, store: Store):
        self.store = store

    # -- entries -------------------------------------------------------

    def enter(
        self,
        commodity: str,
        market: str,
        obs_date,
        driver: str,
        value: float,
        entered_by: str,
        entered_by_role: str,
        entered_at: datetime,
        source_note: str,
    ) -> IntakeEntry:
        entered_by = _require_named(entered_by, "entered_by")
        entered_by_role = _require_named(entered_by_role, "entered_by_role")
        spec = BY_NAME.get(commodity)
        if spec is None:
            raise IntakeValidationError(
                f"unknown commodity {commodity!r} — the catalogue "
                "names seven"
            )
        if market not in {m.market for m in spec.markets}:
            raise IntakeValidationError(
                f"market {market!r} is not a market of {commodity} "
                "in the catalogue"
            )
        if driver not in INTAKE_DRIVERS:
            raise IntakeValidationError(
                f"driver {driver!r} is not phone-reportable — an "
                f"assisted entry may state {', '.join(INTAKE_DRIVERS)}; "
                "the other drivers are instrumented series"
            )
        if driver not in spec.drivers:
            raise IntakeValidationError(
                f"{commodity} does not report {driver} — the entry "
                "would state a driver the series does not carry"
            )
        if not math.isfinite(value) or value <= 0:
            raise IntakeValidationError(
                f"value {value!r} cannot be a phoned-in figure — a "
                "price or arrivals figure is a positive number"
            )
        if obs_date > entered_at.date():
            raise IntakeValidationError(
                f"obs_date {obs_date.isoformat()} is after the entry "
                "date — a phoned-in figure reports what was observed, "
                "never a future day"
            )
        if not (source_note or "").strip():
            raise IntakeValidationError(
                "source_note must state where the figure came from — "
                "an unsourced figure does not enter the queue"
            )
        # One natural key, one entry, one fact.
        existing_fact = self.store.series(
            commodity, market, driver, obs_date, obs_date
        )
        if existing_fact:
            raise IntakeValidationError(
                f"an observation for {commodity}/{market}/{driver} on "
                f"{obs_date.isoformat()} already stands in the store — "
                "history is never overwritten by a phone report"
            )
        for other in self.store.list_intake_entries(commodity, market):
            if (
                other.obs_date == obs_date
                and other.driver == driver
            ):
                if (
                    other.value == value
                    and other.entered_by == entered_by
                    and other.entered_at == entered_at
                    and other.source_note == source_note
                ):
                    return other  # the same statement, re-entered
                raise IntakeValidationError(
                    f"entry {other.entry_id} already claims "
                    f"{commodity}/{market}/{driver} on "
                    f"{obs_date.isoformat()} — one key carries one "
                    "entry, so the fact it may land is unambiguous"
                )
        entry = IntakeEntry(
            entry_id="ENT-pending",
            commodity=commodity,
            market=market,
            obs_date=obs_date,
            driver=driver,
            value=value,
            entered_by=entered_by,
            entered_by_role=entered_by_role,
            entered_at=entered_at,
            source_note=source_note.strip(),
        )
        entry = entry.model_copy(
            update={"entry_id": entry_content_id(entry)}
        )
        if self.store.get_intake_entry(entry.entry_id) is None:
            self.store.insert_intake_entry(entry)
        return entry

    def get_entry(self, entry_id: str) -> IntakeEntry:
        entry = self.store.get_intake_entry(entry_id)
        if entry is None:
            raise IntakeNotFoundError(f"no intake entry {entry_id}")
        return entry

    def list_entries(
        self,
        commodity: str | None = None,
        market: str | None = None,
        state: str | None = None,
    ) -> list[IntakeEntry]:
        entries = self.store.list_intake_entries(commodity, market)
        if state is not None:
            entries = [
                e for e in entries if self.entry_state(e.entry_id) == state
            ]
        return entries

    def entry_state(self, entry_id: str) -> str:
        acts = self.store.list_intake_check_acts(entry_id)
        if not acts:
            return "pending"
        return "confirmed" if acts[0].act == "confirm" else "rejected"

    def entry_view(self, entry_id: str) -> dict:
        entry = self.get_entry(entry_id)
        acts = self.store.list_intake_check_acts(entry_id)
        view = entry.model_dump(mode="json")
        view["unit"] = DRIVER_UNITS[entry.driver]
        view["state"] = self.entry_state(entry_id)
        view["check_acts"] = [a.model_dump(mode="json") for a in acts]
        view["fact"] = None
        view["provenance"] = None
        if view["state"] == "confirmed":
            rows = self.store.series(
                entry.commodity, entry.market, entry.driver,
                entry.obs_date, entry.obs_date,
            )
            if rows:
                view["fact"] = rows[0].model_dump(mode="json")
            act = acts[0]
            view["provenance"] = {
                "kind": "assisted_intake",
                "entry_id": entry.entry_id,
                "entered_by": entry.entered_by,
                "confirmed_by": act.checker,
                "source_note": entry.source_note,
            }
        from fmcg_forecast.intake.verify import verify_entry

        view["problems"] = verify_entry(self.store, entry)
        return view

    # -- check acts ------------------------------------------------------

    def _check(
        self,
        entry_id: str,
        act_kind: str,
        checker: str,
        checker_role: str,
        acted_at: datetime,
        note: str,
    ) -> IntakeCheckAct:
        entry = self.get_entry(entry_id)
        checker = _require_named(checker, "checker")
        checker_role = _require_named(checker_role, "checker_role")
        if checker.strip().lower() == entry.entered_by.strip().lower():
            raise IntakeValidationError(
                f"self-check refused: {checker} entered this figure "
                "and cannot check it — maker–checker needs a second "
                "named person"
            )
        if acted_at < entry.entered_at:
            raise IntakeValidationError(
                "the check act predates the entry it checks"
            )
        if self.store.list_intake_check_acts(entry_id):
            raise IntakeStateError(
                f"entry {entry_id} is already "
                f"{self.entry_state(entry_id)} — a check act is "
                "terminal and admits no second act"
            )
        act = IntakeCheckAct(
            act_id="INA-pending",
            entry_id=entry_id,
            act=act_kind,  # type: ignore[arg-type]
            checker=checker,
            checker_role=checker_role,
            acted_at=acted_at,
            note=note,
        )
        act = act.model_copy(update={"act_id": check_act_content_id(act)})
        if act_kind == "confirm":
            # Land the fact first, through the ordinary insert
            # path; the act is recorded once the fact stands.
            self.store.insert_observations(
                [
                    Observation(
                        commodity=entry.commodity,
                        market=entry.market,
                        obs_date=entry.obs_date,
                        driver=entry.driver,  # type: ignore[arg-type]
                        value=entry.value,
                    )
                ]
            )
        self.store.insert_intake_check_act(act)
        return act

    def confirm(
        self,
        entry_id: str,
        checker: str,
        checker_role: str,
        acted_at: datetime,
        note: str = "",
    ) -> IntakeCheckAct:
        return self._check(entry_id, "confirm", checker, checker_role, acted_at, note)

    def reject(
        self,
        entry_id: str,
        checker: str,
        checker_role: str,
        acted_at: datetime,
        note: str = "",
    ) -> IntakeCheckAct:
        return self._check(entry_id, "reject", checker, checker_role, acted_at, note)

    # -- verification ----------------------------------------------------

    def verify_stored(self, entry_id: str) -> list[str]:
        from fmcg_forecast.intake.verify import verify_entry

        return verify_entry(self.store, self.get_entry(entry_id))

    def verify_all(self) -> list[str]:
        from fmcg_forecast.intake.verify import verify_entry

        problems: list[str] = []
        for entry in self.store.list_intake_entries():
            for problem in verify_entry(self.store, entry):
                problems.append(f"{entry.entry_id}: {problem}")
        return problems
