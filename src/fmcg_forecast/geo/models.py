"""The geo artefacts: desk cost lines, basis readings,
landed comparisons and the market map.

A cost-line entry is the desk's own statement — who entered
it, when, what rate — with ``origin`` ``desk_entered`` on the
artefact and on every surface. It is never market data. A
market's current rate for a line is a fold over its entries:
the latest entry by (entered_on, entry_id) stands, earlier
entries stay on the record.

A basis reading is computed from the stored observation
series alone: for one commodity at one as-of, every market's
spread against the reference market over paired dates, the
spread's own history band, and the classification of the
current spread against that band. A landed comparison prices
each market at its current modal price plus the desk's
entered lines; a market missing a line reads not_computable
and names it. The market map pins one basis reading and
composes each market's cell from artefacts of record — the
reading, the alert fold, the stored weather facts and the
event registry — and carries its rendered page, which the
verifier re-renders byte-for-byte.

All money below is integer paise. All artefacts are
content-addressed and insert-only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

COST_LINE_ORIGIN = "desk_entered"


class CostLineEntry(BaseModel):
    """One desk-entered landed-cost line rate."""

    entry_id: str = Field(description="Content address: COST-<sha256[:16]>")
    commodity: str
    market: str
    line: str = Field(
        description="The pack catalogue line this rate prices"
    )
    rate_paise_per_quintal: int = Field(
        description="The desk's stated rate, integer paise "
        "per quintal — never a float, never negative"
    )
    entered_by: str = Field(description="The named desk user who entered it")
    entered_on: date
    origin: Literal["desk_entered"] = "desk_entered"
    note: str = ""


class BasisMarketRow(BaseModel):
    """One market's basis against the reference market."""

    market: str
    display: str
    paired_days: int = Field(
        description="Dates in the band window on which both "
        "this market and the reference reported a modal price"
    )
    history_start: date | None = Field(
        description="First paired date in the window"
    )
    history_end: date | None = Field(description="Last paired date in the window")
    current_date: date | None = Field(
        description="The last paired date on or before as_of"
    )
    current_age_days: int | None = Field(
        description="Days from the current paired date to as_of"
    )
    freshness: Literal["current", "stale", "none"] = Field(
        description="Whether the current paired date sits "
        "inside the pack's staleness bar"
    )
    current_spread_paise: int | None = Field(
        description="This market's price minus the reference "
        "price on the current paired date, paise"
    )
    band_low_paise: int | None
    band_median_paise: int | None
    band_high_paise: int | None
    classification: Literal[
        "reference", "wide", "within", "narrow",
        "insufficient_history", "no_paired_history",
    ]
    gaps: list[str] = Field(
        description="Every reason this row states less than "
        "a classified spread, as named sentences"
    )


class BasisReading(BaseModel):
    reading_id: str = Field(description="Content address: BASIS-<sha256[:16]>")
    commodity: str
    as_of: date
    pack_version: str
    reference_market: str
    reference_display: str
    rows: list[BasisMarketRow]


class LandedLine(BaseModel):
    """One cost line's state inside a landed row."""

    line: str
    display: str
    state: Literal["entered", "missing"]
    rate_paise_per_quintal: int | None
    entry_id: str | None = Field(
        description="The desk entry standing for this line"
    )
    entered_by: str | None
    entered_on: date | None


class LandedMarketRow(BaseModel):
    """One market's landed cost, or its named refusal."""

    market: str
    display: str
    price_state: Literal["current", "stale", "no_current_price"]
    price_paise: int | None = Field(
        description="The market's last modal price on or "
        "before as_of, in paise"
    )
    price_date: date | None
    lines: list[LandedLine]
    landed_paise: int | None = Field(
        description="Price plus every line's rate, paise; "
        "None whenever the row is not computable"
    )
    state: Literal["computable", "not_computable"]
    missing_lines: list[str] = Field(
        description="The catalogue lines with no standing "
        "desk entry for this market — named, never assumed"
    )
    rank: int | None = Field(
        description="Rank under the pack's rule; None for a "
        "not-computable market, which is never ranked"
    )


class LandedComparison(BaseModel):
    comparison_id: str = Field(
        description="Content address: LAND-<sha256[:16]>"
    )
    commodity: str
    as_of: date
    pack_version: str
    priced_for: str = Field(
        description="The desk receiving point the entered "
        "lines price delivery to, as the desk names it"
    )
    rows: list[LandedMarketRow]
    scope_note: str


class WeatherOverlayRow(BaseModel):
    """One market's weather overlay, from its stored
    weather-index facts alone."""

    market: str
    state: Literal[
        "deviating", "within", "flat",
        "insufficient_history", "no_current_data",
    ]
    latest_date: date | None
    latest_value: float | None
    window_facts: int = Field(
        description="Weather facts inside the overlay window"
    )
    mean: float | None
    std: float | None
    z: float | None = Field(
        description="(latest - mean) / std over the window, "
        "4dp; None when the state cannot state one"
    )


class ActiveEventRef(BaseModel):
    """One registry event whose window covers the map's
    as-of, pinned by reference."""

    event_id: str
    event_class: str
    window_start: date
    window_end: date | None = Field(
        description="The window's last day; None while the "
        "event is open-ended (still in force)"
    )


class MapCell(BaseModel):
    """One market's cell on the map — a composition of
    artefact reads, each field traceable to its source."""

    market: str
    display: str
    region: str
    grid_row: int
    grid_col: int
    data_state: Literal["current", "stale", "no_current_data"]
    price_paise: int | None
    price_date: date | None
    basis_classification: str = Field(
        description="The pinned basis reading's "
        "classification for this market"
    )
    current_spread_paise: int | None
    open_alerts: int = Field(
        description="Alerts for this market whose folded "
        "state at as_of is open or acknowledged"
    )
    top_severity: str | None = Field(
        description="The highest severity among the open "
        "alerts, under the alert pack's severity order"
    )
    weather: WeatherOverlayRow
    series_href: str = Field(
        description="Where the market's series board opens"
    )


class MarketMap(BaseModel):
    map_id: str = Field(description="Content address: MAP-<sha256[:16]>")
    commodity: str
    as_of: date
    pack_version: str
    basis_reading_id: str = Field(
        description="The basis reading this map pins — its "
        "cells' basis figures are that artefact's, verbatim"
    )
    active_events: list[ActiveEventRef] = Field(
        description="Registry events for this commodity "
        "whose windows cover as_of"
    )
    cells: list[MapCell]
    html: str = Field(
        description="The rendered map page — a pure function "
        "of the cells, re-rendered byte-for-byte by the "
        "verifier"
    )


def _content_id(prefix: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return prefix + hashlib.sha256(canonical.encode()).hexdigest()[:16]


def cost_line_content_id(entry: CostLineEntry) -> str:
    return _content_id(
        "COST-", entry.model_dump(mode="json", exclude={"entry_id"})
    )


def basis_content_id(reading: BasisReading) -> str:
    return _content_id(
        "BASIS-", reading.model_dump(mode="json", exclude={"reading_id"})
    )


def landed_content_id(comparison: LandedComparison) -> str:
    return _content_id(
        "LAND-",
        comparison.model_dump(mode="json", exclude={"comparison_id"}),
    )


def map_content_id(market_map: MarketMap) -> str:
    return _content_id(
        "MAP-", market_map.model_dump(mode="json", exclude={"map_id"})
    )
