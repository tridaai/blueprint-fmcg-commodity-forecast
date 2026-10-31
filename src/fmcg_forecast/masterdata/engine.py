"""The master data engine — the genesis state, calendar
arithmetic, state diffs and coverage re-derivation.

The genesis state is the catalogue's own facts restated
as data: each market's calendar follows the reporting
pattern of the commodity it trades under, displays are
the catalogue's display names, units are the pack's
statements. From there, everything is a fold or a
recomputation:

- **A day's status** is computed from a calendar:
  pattern, minus holidays, plus extra operating days.
- **A diff** is field-by-field over the state's
  flattened paths, computed from the two states alone
  — the same function strikes it and re-derives it.
- **Coverage re-derivation** counts a thin-pack
  window's expected days under a stated calendar and
  its observed days from the stored series, exactly
  the thin engine's arithmetic with the calendar in
  place of the pattern — and names every date in the
  window whose operating status the two calendars
  disagree on, so a moved verdict is explained date
  by date, never just flagged.
"""

from __future__ import annotations

from datetime import date, timedelta

from fmcg_forecast.catalogue import BY_NAME, CommoditySpec
from fmcg_forecast.masterdata.models import (
    MarketCalendar,
    MasterDataDiffEntry,
    MasterDataState,
    UnitStatements,
)
from fmcg_forecast.masterdata.pack import load_masterdata_pack
from fmcg_forecast.store import Store
from fmcg_forecast.thin.pack import load_thin_data_pack as load_thin_pack


class MasterDataError(Exception):
    """A master data computation the record refuses."""


def genesis_state() -> MasterDataState:
    """The catalogue's facts as the genesis state."""
    patterns: dict[str, str] = {}
    displays: dict[str, str] = {}
    for spec in BY_NAME.values():
        for market in spec.markets:
            if market.market in patterns and patterns[market.market] != spec.reporting:
                raise MasterDataError(
                    f"market {market.market!r} trades under "
                    "two reporting patterns — the catalogue "
                    "must settle one before it can be genesis"
                )
            patterns[market.market] = spec.reporting
            displays[market.market] = market.display
    pack = load_masterdata_pack()
    return MasterDataState(
        calendars=[
            MarketCalendar(market=market, weekly_pattern=patterns[market])
            for market in sorted(patterns)
        ],
        commodity_displays={
            name: spec.display for name, spec in BY_NAME.items()
        },
        market_displays=displays,
        units=UnitStatements(
            price_unit=pack.price_unit,
            quantity_unit=pack.quantity_unit,
            quintals_per_tonne=pack.quintals_per_tonne,
        ),
    )


def pattern_operating(pattern: str, day: date) -> bool:
    """Whether the weekly pattern alone opens the day —
    the thin engine's rule, restated for a pattern."""
    if pattern == "tue_fri":
        return day.weekday() in (1, 4)
    return day.weekday() != 6  # mon_sat: closed Sundays


def calendar_operating(calendar: MarketCalendar, day: date) -> bool:
    if day in calendar.holidays:
        return False
    if day in calendar.extra_operating_days:
        return True
    return pattern_operating(calendar.weekly_pattern, day)


def calendar_operating_days(
    calendar: MarketCalendar, start: date, end: date
) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        if calendar_operating(calendar, current):
            days.append(current)
        current += timedelta(days=1)
    return days


def changed_operating_dates(
    before: MarketCalendar, after: MarketCalendar,
    start: date, end: date,
) -> list[dict]:
    """Every date in range whose status the two
    calendars disagree on, with both verdicts."""
    changed: list[dict] = []
    current = start
    while current <= end:
        was = calendar_operating(before, current)
        is_now = calendar_operating(after, current)
        if was != is_now:
            changed.append(
                {
                    "date": current,
                    "before": "operating" if was else "closed",
                    "after": "operating" if is_now else "closed",
                }
            )
        current += timedelta(days=1)
    return changed


def flatten_state(state: MasterDataState) -> dict[str, object]:
    """The state as flattened field paths — the diff's
    vocabulary, and the verifier's."""
    flat: dict[str, object] = {}
    for calendar in state.calendars:
        prefix = f"calendars.{calendar.market}"
        flat[f"{prefix}.weekly_pattern"] = calendar.weekly_pattern
        flat[f"{prefix}.holidays"] = [
            d.isoformat() for d in calendar.holidays
        ]
        flat[f"{prefix}.extra_operating_days"] = [
            d.isoformat() for d in calendar.extra_operating_days
        ]
    for commodity, display in state.commodity_displays.items():
        flat[f"displays.commodity.{commodity}"] = display
    for market, display in state.market_displays.items():
        flat[f"displays.market.{market}"] = display
    flat["units.price_unit"] = state.units.price_unit
    flat["units.quantity_unit"] = state.units.quantity_unit
    flat["units.quintals_per_tonne"] = state.units.quintals_per_tonne
    return flat


def diff_states(
    before: MasterDataState, after: MasterDataState
) -> list[MasterDataDiffEntry]:
    """Field-by-field, over sorted paths — the same
    list at strike time and at verification time."""
    flat_before = flatten_state(before)
    flat_after = flatten_state(after)
    return [
        MasterDataDiffEntry(
            field=field,
            before=flat_before[field],
            after=flat_after[field],
        )
        for field in sorted(flat_before)
        if flat_before[field] != flat_after[field]
    ]


def window_coverage_under(
    store: Store,
    spec: CommoditySpec,
    market: str,
    window_days: int,
    as_of: date,
    state: MasterDataState,
) -> dict:
    """One thin-pack window's verdict under a stated
    calendar — the thin engine's arithmetic with the
    calendar's operating days in place of the pattern's."""
    start = as_of - timedelta(days=window_days - 1)
    expected = calendar_operating_days(state.calendar(market), start, as_of)
    observed_dates = {
        row.obs_date
        for row in store.series(spec.commodity, market, "modal_price", None, as_of)
    }
    present = [d for d in expected if d in observed_dates]
    missing = [d for d in expected if d not in observed_dates]
    return {
        "window_days": window_days,
        "operating_days": len(expected),
        "observed": len(present),
        "coverage": (
            round(len(present) / len(expected), 4) if expected else 1.0
        ),
        "missing_operating_dates": missing,
    }


def coverage_report(
    store: Store,
    commodity: str,
    market: str,
    as_of: date,
    before: MasterDataState,
    after: MasterDataState,
) -> dict:
    """Every thin-pack window's verdict under two
    states, with the changed dates named per window.

    The acceptance shape of F20-AD1: a calendar change
    re-derives verdicts for the windows containing a
    changed date and moves nothing else — this report
    is where that is read, and the verifier re-performs
    it whole.
    """
    spec = BY_NAME.get(commodity)
    if spec is None:
        raise MasterDataError(f"unknown commodity {commodity!r}")
    if all(m.market != market for m in spec.markets):
        raise MasterDataError(
            f"market {market!r} does not trade {commodity!r}"
        )
    windows_days = load_thin_pack().windows_days
    widest = max(windows_days)
    range_start = as_of - timedelta(days=widest - 1)
    changed = changed_operating_dates(
        before.calendar(market), after.calendar(market),
        range_start, as_of,
    )
    windows = []
    for window_days in windows_days:
        window_start = as_of - timedelta(days=window_days - 1)
        verdict_before = window_coverage_under(
            store, spec, market, window_days, as_of, before
        )
        verdict_after = window_coverage_under(
            store, spec, market, window_days, as_of, after
        )
        windows.append(
            {
                "window_days": window_days,
                "before": verdict_before,
                "after": verdict_after,
                "changed_operating_dates": [
                    c for c in changed if c["date"] >= window_start
                ],
                "verdict_changed": verdict_before != verdict_after,
            }
        )
    return {
        "commodity": commodity,
        "market": market,
        "as_of": as_of,
        "windows": windows,
    }
