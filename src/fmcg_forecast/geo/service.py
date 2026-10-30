"""The geo workflow every surface shares.

Entering a cost line is a desk act: a named desk user, a
catalogue line, an integer-paise rate — stored insert-only,
idempotent on an identical entry. Striking a basis reading,
a landed comparison or a market map is a computation, not
an act: the service recomputes the artefact from the store
and stores it insert-only, so the same inputs always land
on the same content address and a re-strike is a no-op that
returns the stored artefact. A map pins the basis reading
for its commodity and as-of — struck first if none stands —
so a map's basis figures are always one named artefact's,
verbatim. Views carry the artefact and its re-performance
problems: no surface offers a figure without the evidence
that bounds it.
"""

from __future__ import annotations

from datetime import date

from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.geo.engine import (
    GeoError,
    compute_basis_reading,
    compute_landed_comparison,
    compute_market_map,
    head_cost_entries,
)
from fmcg_forecast.geo.models import (
    BasisReading,
    CostLineEntry,
    LandedComparison,
    MarketMap,
    cost_line_content_id,
)
from fmcg_forecast.geo.pack import GeoPack, load_geo_pack
from fmcg_forecast.geo.verify import (
    verify_basis_reading,
    verify_geo,
    verify_landed_comparison,
    verify_market_map,
)
from fmcg_forecast.store import Store


class GeoNotFoundError(LookupError):
    """No geo artefact with that id."""


class GeoValidationError(ValueError):
    """A desk entry the geo pack refuses."""


class GeoService:
    def __init__(self, store: Store, pack: GeoPack | None = None):
        self.store = store
        self.pack = pack or load_geo_pack()

    # -- desk cost lines (F20-PO4) --------------------------------

    def enter_cost_line(
        self,
        commodity: str,
        market: str,
        line: str,
        rate_paise_per_quintal: int,
        entered_by: str,
        entered_on: date,
        note: str = "",
    ) -> CostLineEntry:
        spec = BY_NAME.get(commodity)
        if spec is None:
            raise GeoValidationError(f"unknown commodity {commodity!r}")
        if market not in {m.market for m in spec.markets}:
            raise GeoValidationError(
                f"market {market!r} is not a {commodity} market "
                "in the catalogue"
            )
        if line not in {spec_line.line for spec_line in self.pack.cost_lines}:
            raise GeoValidationError(
                f"line {line!r} is not in the geo pack's "
                "cost-line catalogue"
            )
        if isinstance(rate_paise_per_quintal, bool) or not isinstance(
            rate_paise_per_quintal, int
        ):
            raise GeoValidationError(
                "a cost line rate is integer paise per quintal"
            )
        if rate_paise_per_quintal < 0:
            raise GeoValidationError("a cost line rate cannot be negative")
        if not entered_by or not entered_by.strip():
            raise GeoValidationError(
                "a cost line needs its named desk enterer"
            )
        entry = CostLineEntry(
            entry_id="",
            commodity=commodity,
            market=market,
            line=line,
            rate_paise_per_quintal=rate_paise_per_quintal,
            entered_by=entered_by,
            entered_on=entered_on,
            note=note,
        )
        entry = entry.model_copy(
            update={"entry_id": cost_line_content_id(entry)}
        )
        if self.store.get_cost_line_entry(entry.entry_id) is None:
            self.store.insert_cost_line_entry(entry)
        return entry

    def list_cost_lines(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[CostLineEntry]:
        return self.store.list_cost_line_entries(commodity, market)

    def head_cost_lines(
        self, commodity: str, market: str, as_of: date | None = None
    ) -> dict[str, CostLineEntry]:
        """The standing entry per line for one market — the
        fold the landed comparison prices from, scoped to
        entries entered on or before its as-of."""
        return head_cost_entries(self.store, commodity, market, as_of)

    # -- basis readings (F20-PO4) ----------------------------------

    def strike_basis_reading(
        self, commodity: str, as_of: date
    ) -> BasisReading:
        reading = compute_basis_reading(
            self.store, commodity, as_of, self.pack
        )
        if self.store.get_basis_reading(reading.reading_id) is None:
            self.store.insert_basis_reading(reading)
        return reading

    def get_basis_reading(self, reading_id: str) -> BasisReading:
        reading = self.store.get_basis_reading(reading_id)
        if reading is None:
            raise GeoNotFoundError(f"no basis reading {reading_id}")
        return reading

    def list_basis_readings(
        self, commodity: str | None = None
    ) -> list[BasisReading]:
        return self.store.list_basis_readings(commodity)

    def basis_view(self, reading_id: str) -> dict:
        reading = self.get_basis_reading(reading_id)
        view = reading.model_dump(mode="json")
        view["problems"] = verify_basis_reading(self.store, reading)
        return view

    # -- landed comparisons (F20-PO4) ------------------------------

    def strike_landed_comparison(
        self, commodity: str, as_of: date, priced_for: str
    ) -> LandedComparison:
        if not priced_for or not priced_for.strip():
            raise GeoValidationError(
                "a landed comparison names the desk receiving "
                "point it is priced for"
            )
        comparison = compute_landed_comparison(
            self.store, commodity, as_of, priced_for, self.pack
        )
        if self.store.get_landed_comparison(comparison.comparison_id) is None:
            self.store.insert_landed_comparison(comparison)
        return comparison

    def get_landed_comparison(self, comparison_id: str) -> LandedComparison:
        comparison = self.store.get_landed_comparison(comparison_id)
        if comparison is None:
            raise GeoNotFoundError(f"no landed comparison {comparison_id}")
        return comparison

    def list_landed_comparisons(
        self, commodity: str | None = None
    ) -> list[LandedComparison]:
        return self.store.list_landed_comparisons(commodity)

    def landed_view(self, comparison_id: str) -> dict:
        comparison = self.get_landed_comparison(comparison_id)
        view = comparison.model_dump(mode="json")
        view["problems"] = verify_landed_comparison(self.store, comparison)
        return view

    # -- market maps (F20-GS1 + F20-GS2) ----------------------------

    def strike_map(self, commodity: str, as_of: date) -> MarketMap:
        reading = self._standing_reading(commodity, as_of)
        market_map = compute_market_map(
            self.store, commodity, as_of, self.pack, reading
        )
        if self.store.get_market_map(market_map.map_id) is None:
            self.store.insert_market_map(market_map)
        return market_map

    def _standing_reading(
        self, commodity: str, as_of: date
    ) -> BasisReading:
        """The basis reading a map pins: the one standing for
        this commodity, as-of and pack — struck first if none
        stands, so a map never floats free of a reading."""
        for reading in self.store.list_basis_readings(commodity):
            if (
                reading.as_of == as_of
                and reading.pack_version == self.pack.version
            ):
                return reading
        return self.strike_basis_reading(commodity, as_of)

    def get_map(self, map_id: str) -> MarketMap:
        market_map = self.store.get_market_map(map_id)
        if market_map is None:
            raise GeoNotFoundError(f"no market map {map_id}")
        return market_map

    def list_maps(
        self, commodity: str | None = None
    ) -> list[MarketMap]:
        return self.store.list_market_maps(commodity)

    def map_view(self, map_id: str) -> dict:
        market_map = self.get_map(map_id)
        view = market_map.model_dump(mode="json")
        view["problems"] = verify_market_map(self.store, market_map)
        return view

    # -- verification ------------------------------------------------

    def verify_all(self) -> list[str]:
        return verify_geo(self.store)


__all__ = [
    "GeoError",
    "GeoNotFoundError",
    "GeoService",
    "GeoValidationError",
]
