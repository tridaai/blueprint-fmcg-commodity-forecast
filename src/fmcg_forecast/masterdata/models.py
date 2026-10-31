"""The master data artefacts: the data state itself and
its versions.

The state is whole: every market's calendar, every
commodity's and market's display name, the unit
statements. A version wraps a state with its author,
its date, the access pack it was judged under, its
link to the version it supersedes, and the diff the
engine computed — field by field, over flattened paths
(`calendars.<market>.holidays`, `displays.commodity.
chili`, `units.quintals_per_tonne`), so a reader sees
exactly what an edit moved and the verifier re-derives
the same lines from the two states alone.

Validators hold the state's shape against the
catalogue: a state that drops a market or invents one
is not a state this desk can stand on, and a calendar
that names the same date twice is refused at the
model, not discovered at coverage time.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from pydantic import BaseModel, Field, model_validator

from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.masterdata.pack import WEEKLY_PATTERNS

ALL_COMMODITIES = sorted(BY_NAME)
ALL_MARKETS = sorted({m.market for spec in BY_NAME.values() for m in spec.markets})


class MarketCalendar(BaseModel):
    """One market's operating calendar."""

    market: str
    weekly_pattern: str = Field(
        description="mon_sat or tue_fri — the market's "
        "ordinary week, from its commodity's reporting "
        "pattern at genesis"
    )
    holidays: list[date] = Field(
        default_factory=list,
        description="Stated closures: pattern days the "
        "market did not sit",
    )
    extra_operating_days: list[date] = Field(
        default_factory=list,
        description="Stated special sessions: days outside "
        "the pattern the market did sit",
    )

    @model_validator(mode="after")
    def _calendar_is_well_formed(self) -> "MarketCalendar":
        if self.weekly_pattern not in WEEKLY_PATTERNS:
            raise ValueError(
                f"weekly pattern {self.weekly_pattern!r} is "
                f"not one the pack states {WEEKLY_PATTERNS}"
            )
        for field_name in ("holidays", "extra_operating_days"):
            values = getattr(self, field_name)
            if len(set(values)) != len(values):
                raise ValueError(
                    f"calendar for {self.market!r} names a "
                    f"date twice in {field_name}"
                )
            if values != sorted(values):
                raise ValueError(
                    f"calendar for {self.market!r} lists "
                    f"{field_name} out of order — dates are "
                    "kept sorted so two equal states are "
                    "byte-equal"
                )
        overlap = set(self.holidays) & set(self.extra_operating_days)
        if overlap:
            raise ValueError(
                f"calendar for {self.market!r} names "
                f"{sorted(overlap)} as both a holiday and "
                "an extra operating day — the pack states "
                "the holiday wins, so the strike must say "
                "which one it means by naming it once"
            )
        return self


class UnitStatements(BaseModel):
    """The units the desk's figures are stated in."""

    price_unit: str
    quantity_unit: str
    quintals_per_tonne: int


class MasterDataState(BaseModel):
    """The whole reference-data state, as one value."""

    calendars: list[MarketCalendar] = Field(
        description="One calendar per catalogue market"
    )
    commodity_displays: dict[str, str] = Field(
        description="Display name per commodity"
    )
    market_displays: dict[str, str] = Field(
        description="Display name per market"
    )
    units: UnitStatements

    @model_validator(mode="after")
    def _state_covers_the_catalogue(self) -> "MasterDataState":
        markets = [c.market for c in self.calendars]
        if sorted(markets) != ALL_MARKETS:
            raise ValueError(
                "a master data state carries exactly one "
                f"calendar per catalogue market {ALL_MARKETS}, "
                f"got {sorted(markets)}"
            )
        if markets != sorted(markets):
            raise ValueError(
                "calendars are kept in market order so two "
                "equal states are byte-equal"
            )
        if sorted(self.commodity_displays) != ALL_COMMODITIES:
            raise ValueError(
                "a master data state names a display for "
                f"exactly the catalogue commodities "
                f"{ALL_COMMODITIES}, got "
                f"{sorted(self.commodity_displays)}"
            )
        if sorted(self.market_displays) != ALL_MARKETS:
            raise ValueError(
                "a master data state names a display for "
                f"exactly the catalogue markets {ALL_MARKETS}, "
                f"got {sorted(self.market_displays)}"
            )
        for name, display in {
            **self.commodity_displays,
            **self.market_displays,
        }.items():
            if not display or not display.strip():
                raise ValueError(
                    f"the display name for {name!r} is empty"
                )
        if self.units.quintals_per_tonne <= 0:
            raise ValueError("quintals per tonne must be positive")
        return self

    def calendar(self, market: str) -> MarketCalendar:
        for calendar in self.calendars:
            if calendar.market == market:
                return calendar
        raise ValueError(f"no calendar for market {market!r}")


class MasterDataDiffEntry(BaseModel):
    """One field's movement between two states."""

    field: str = Field(
        description="The flattened field path, e.g. "
        "calendars.kanpur.holidays"
    )
    before: object = Field(
        description="The superseded value, as JSON; None "
        "only against genesis for fields genesis states "
        "implicitly — genesis states every field, so a "
        "first version's diff is against real values"
    )
    after: object = Field(description="The struck value, as JSON")


class MasterDataVersion(BaseModel):
    """One struck state, with its author and its diff."""

    version_id: str = Field(
        description="Content address: MDV-<sha256[:16]>"
    )
    seq: int = Field(
        description="Strike order among versions, 1-based "
        "and gapless"
    )
    label: str = Field(
        description="The editor's name for this version, "
        "unique across the chain"
    )
    state: MasterDataState
    diff: list[MasterDataDiffEntry] = Field(
        description="Field-by-field against the version "
        "superseded (or genesis), re-derived by the "
        "verifier from the two states alone"
    )
    supersedes_version_id: str | None = Field(
        description="The standing version this one "
        "supersedes; None supersedes genesis"
    )
    edited_by: str = Field(description="The named editor")
    edited_on: date
    access_pack_version: str = Field(
        description="The access pack under which the "
        "editor's right was judged, on its face"
    )
    pack_version: str = Field(
        description="The master data pack the strike was "
        "judged under"
    )


def _content_id(prefix: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return prefix + hashlib.sha256(canonical.encode()).hexdigest()[:16]


def master_data_version_content_id(version: MasterDataVersion) -> str:
    return _content_id(
        "MDV-", version.model_dump(mode="json", exclude={"version_id"})
    )
