"""Re-performance for the geo layer.

Every geo artefact is recomputed from the store under its
own pack and compared field for field: a basis reading
against the raw observation series, a landed comparison
against the stored prices and the standing cost-line fold,
a map against its pinned reading plus the alert fold, the
weather facts and the registry — HTML included, so a page
that no longer matches its cells is a problem, not a
rendering choice. A stored artefact whose content address
does not recompute is tampered, and is named as such.
"""

from __future__ import annotations

from fmcg_forecast.geo.engine import (
    compute_basis_reading,
    compute_landed_comparison,
    compute_market_map,
)
from fmcg_forecast.geo.models import (
    BasisReading,
    CostLineEntry,
    LandedComparison,
    MarketMap,
    basis_content_id,
    cost_line_content_id,
    landed_content_id,
    map_content_id,
)
from fmcg_forecast.geo.pack import load_geo_pack
from fmcg_forecast.store import Store


def _diff(stored: dict, recomputed: dict, path: str = "") -> list[str]:
    """Field-level differences between two artefact dumps."""
    problems: list[str] = []
    if isinstance(stored, dict) and isinstance(recomputed, dict):
        for key in sorted(set(stored) | set(recomputed)):
            problems.extend(
                _diff(stored.get(key), recomputed.get(key), f"{path}{key}.")
            )
    elif isinstance(stored, list) and isinstance(recomputed, list):
        if len(stored) != len(recomputed):
            problems.append(
                f"{path[:-1]}: {len(stored)} rows stored, "
                f"{len(recomputed)} re-performed"
            )
        for i, (a, b) in enumerate(zip(stored, recomputed)):
            problems.extend(_diff(a, b, f"{path}{i}."))
    elif stored != recomputed:
        problems.append(
            f"{path[:-1]}: stored {stored!r} != re-performed {recomputed!r}"
        )
    return problems


def verify_cost_line_entry(entry: CostLineEntry) -> list[str]:
    problems: list[str] = []
    if entry.entry_id != cost_line_content_id(entry):
        problems.append(
            f"cost line entry {entry.entry_id}: content address "
            "does not recompute — the entry was altered after entry"
        )
    if entry.origin != "desk_entered":
        problems.append(
            f"cost line entry {entry.entry_id}: origin is "
            f"{entry.origin!r}, not desk_entered"
        )
    catalogue = {spec.line for spec in load_geo_pack().cost_lines}
    if entry.line not in catalogue:
        problems.append(
            f"cost line entry {entry.entry_id}: line {entry.line!r} "
            "is not in the geo pack's cost-line catalogue"
        )
    if entry.rate_paise_per_quintal < 0:
        problems.append(
            f"cost line entry {entry.entry_id}: a negative rate"
        )
    return problems


def verify_basis_reading(store: Store, reading: BasisReading) -> list[str]:
    problems: list[str] = []
    if reading.reading_id != basis_content_id(reading):
        problems.append(
            f"basis reading {reading.reading_id}: content address "
            "does not recompute — the reading was altered after striking"
        )
    pack = load_geo_pack(reading.pack_version)
    recomputed = compute_basis_reading(
        store, reading.commodity, reading.as_of, pack
    )
    problems.extend(
        f"basis reading {reading.reading_id}: {problem}"
        for problem in _diff(
            reading.model_dump(mode="json"),
            recomputed.model_dump(mode="json"),
        )
    )
    return problems


def verify_landed_comparison(
    store: Store, comparison: LandedComparison
) -> list[str]:
    problems: list[str] = []
    if comparison.comparison_id != landed_content_id(comparison):
        problems.append(
            f"landed comparison {comparison.comparison_id}: content "
            "address does not recompute — the comparison was "
            "altered after striking"
        )
    pack = load_geo_pack(comparison.pack_version)
    recomputed = compute_landed_comparison(
        store,
        comparison.commodity,
        comparison.as_of,
        comparison.priced_for,
        pack,
    )
    problems.extend(
        f"landed comparison {comparison.comparison_id}: {problem}"
        for problem in _diff(
            comparison.model_dump(mode="json"),
            recomputed.model_dump(mode="json"),
        )
    )
    return problems


def verify_market_map(store: Store, market_map: MarketMap) -> list[str]:
    problems: list[str] = []
    if market_map.map_id != map_content_id(market_map):
        problems.append(
            f"market map {market_map.map_id}: content address "
            "does not recompute — the map was altered after striking"
        )
    reading = store.get_basis_reading(market_map.basis_reading_id)
    if reading is None:
        problems.append(
            f"market map {market_map.map_id}: its pinned basis "
            f"reading {market_map.basis_reading_id} is not on record"
        )
        return problems
    problems.extend(
        f"market map {market_map.map_id} pins a basis reading "
        f"with problems: {problem}"
        for problem in verify_basis_reading(store, reading)
    )
    pack = load_geo_pack(market_map.pack_version)
    recomputed = compute_market_map(
        store, market_map.commodity, market_map.as_of, pack, reading
    )
    problems.extend(
        f"market map {market_map.map_id}: {problem}"
        for problem in _diff(
            market_map.model_dump(mode="json"),
            recomputed.model_dump(mode="json"),
        )
    )
    return problems


def verify_geo(store: Store) -> list[str]:
    """Every geo artefact on record, re-performed."""
    problems: list[str] = []
    for entry in store.list_cost_line_entries():
        problems.extend(verify_cost_line_entry(entry))
    for reading in store.list_basis_readings():
        problems.extend(verify_basis_reading(store, reading))
    for comparison in store.list_landed_comparisons():
        problems.extend(verify_landed_comparison(store, comparison))
    for market_map in store.list_market_maps():
        problems.extend(verify_market_map(store, market_map))
    return problems
