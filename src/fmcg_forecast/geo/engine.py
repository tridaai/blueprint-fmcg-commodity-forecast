"""The geo computations: basis, landed cost, weather
overlay and the map composition.

Pure functions over the store's reads. The basis is paired
arithmetic: a spread exists only on a date both markets
reported, so a thin or offset market shows fewer paired days
and names the shortfall instead of interpolating one. Landed
cost is integer-paise addition of a stored price and the
desk's standing entries — nothing is estimated. The map
composes artefacts of record: the pinned basis reading, the
alert fold, the stored weather facts, the event registry.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta

from fmcg_forecast.alerts.engine import fold_state
from fmcg_forecast.alerts.pack import SEVERITY_RANK, load_alert_pack
from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.geo.models import (
    ActiveEventRef,
    BasisMarketRow,
    BasisReading,
    CostLineEntry,
    LandedComparison,
    LandedLine,
    LandedMarketRow,
    MapCell,
    MarketMap,
    WeatherOverlayRow,
    basis_content_id,
    landed_content_id,
    map_content_id,
)
from fmcg_forecast.geo.pack import GEO_SCOPE_NOTE, GeoPack
from fmcg_forecast.geo.render import render_market_map
from fmcg_forecast.store import Store


class GeoError(ValueError):
    """A geo computation the record cannot support."""


def to_paise(value: float) -> int:
    """A stored INR price to integer paise, rounded once."""
    return int(round(value * 100))


def _price_points(
    store: Store, commodity: str, market: str, end: date
) -> dict[date, int]:
    rows = store.series(commodity, market, "modal_price", None, end)
    return {r.obs_date: to_paise(r.value) for r in rows}


def paired_spreads(
    store: Store,
    commodity: str,
    market: str,
    reference_market: str,
    start: date,
    end: date,
) -> list[tuple[date, int]]:
    """(date, spread in paise) for every date in [start, end]
    on which both markets reported a modal price."""
    own = _price_points(store, commodity, market, end)
    reference = _price_points(store, commodity, reference_market, end)
    return [
        (day, own[day] - reference[day])
        for day in sorted(own.keys() & reference.keys())
        if start <= day <= end
    ]


def quantile(sorted_values: list[int], q: float) -> int:
    """The pack's percentile: linear interpolation at rank
    q x (n - 1) over the sorted values, rounded to the
    nearest paise."""
    if not sorted_values:
        raise GeoError("a quantile needs at least one value")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = q * (len(sorted_values) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_values[int(rank)]
    fraction = rank - low
    value = sorted_values[low] * (1 - fraction) + sorted_values[high] * fraction
    return int(round(value))


def compute_basis_reading(
    store: Store, commodity: str, as_of: date, pack: GeoPack
) -> BasisReading:
    spec = BY_NAME.get(commodity)
    if spec is None:
        raise GeoError(f"unknown commodity {commodity!r}")
    reference = spec.markets[0]
    window_start = as_of - timedelta(days=pack.band_window_days - 1)
    rows: list[BasisMarketRow] = []
    for market_spec in spec.markets:
        pairs = paired_spreads(
            store, commodity, market_spec.market, reference.market,
            window_start, as_of,
        )
        gaps: list[str] = []
        if not pairs:
            gaps.append(
                f"{market_spec.display} and {reference.display} share "
                f"no reporting date in the {pack.band_window_days}-day "
                f"window ending {as_of.isoformat()} — no basis can "
                "be stated."
            )
            rows.append(
                BasisMarketRow(
                    market=market_spec.market,
                    display=market_spec.display,
                    paired_days=0,
                    history_start=None,
                    history_end=None,
                    current_date=None,
                    current_age_days=None,
                    freshness="none",
                    current_spread_paise=None,
                    band_low_paise=None,
                    band_median_paise=None,
                    band_high_paise=None,
                    classification="no_paired_history",
                    gaps=gaps,
                )
            )
            continue
        spreads = sorted(spread for _, spread in pairs)
        band_low = quantile(spreads, pack.band_low_quantile)
        band_median = quantile(spreads, 0.50)
        band_high = quantile(spreads, pack.band_high_quantile)
        current_date, current_spread = pairs[-1]
        age = (as_of - current_date).days
        freshness = "stale" if age > pack.stale_after_days else "current"
        if market_spec.market == reference.market:
            classification = "reference"
        elif len(pairs) < pack.min_paired_days:
            classification = "insufficient_history"
            gaps.append(
                f"Only {len(pairs)} paired days in the window — "
                f"the pack needs {pack.min_paired_days} before a "
                "spread is classified."
            )
        elif current_spread > band_high:
            classification = "wide"
        elif current_spread < band_low:
            classification = "narrow"
        else:
            classification = "within"
        if freshness == "stale":
            gaps.append(
                f"The last paired date is {current_date.isoformat()}, "
                f"{age} days before the as-of — the current spread "
                "is stated as of that date, not the as-of."
            )
        rows.append(
            BasisMarketRow(
                market=market_spec.market,
                display=market_spec.display,
                paired_days=len(pairs),
                history_start=pairs[0][0],
                history_end=pairs[-1][0],
                current_date=current_date,
                current_age_days=age,
                freshness=freshness,
                current_spread_paise=current_spread,
                band_low_paise=band_low,
                band_median_paise=band_median,
                band_high_paise=band_high,
                classification=classification,
                gaps=gaps,
            )
        )
    reading = BasisReading(
        reading_id="",
        commodity=commodity,
        as_of=as_of,
        pack_version=pack.version,
        reference_market=reference.market,
        reference_display=reference.display,
        rows=rows,
    )
    return reading.model_copy(update={"reading_id": basis_content_id(reading)})


def head_cost_entries(
    store: Store,
    commodity: str,
    market: str,
    as_of: date | None = None,
) -> dict[str, CostLineEntry]:
    """The standing entry per line: the fold over the
    market's entries — the latest by (entered_on, entry_id)
    stands, earlier entries stay on the record. With an
    as_of, only entries entered on or before it take part,
    so a rate the desk enters later never reprices an
    earlier comparison."""
    heads: dict[str, CostLineEntry] = {}
    for entry in store.list_cost_line_entries(commodity, market):
        if as_of is not None and entry.entered_on > as_of:
            continue
        current = heads.get(entry.line)
        if current is None or (entry.entered_on, entry.entry_id) > (
            current.entered_on,
            current.entry_id,
        ):
            heads[entry.line] = entry
    return heads


def _latest_price(
    store: Store, commodity: str, market: str, as_of: date
) -> tuple[int | None, date | None]:
    rows = store.series(commodity, market, "modal_price", None, as_of)
    if not rows:
        return None, None
    last = rows[-1]
    return to_paise(last.value), last.obs_date


def compute_landed_comparison(
    store: Store,
    commodity: str,
    as_of: date,
    priced_for: str,
    pack: GeoPack,
) -> LandedComparison:
    spec = BY_NAME.get(commodity)
    if spec is None:
        raise GeoError(f"unknown commodity {commodity!r}")
    rows: list[LandedMarketRow] = []
    for market_spec in spec.markets:
        price_paise, price_date = _latest_price(
            store, commodity, market_spec.market, as_of
        )
        if price_paise is None:
            price_state = "no_current_price"
        else:
            age = (as_of - price_date).days
            price_state = "stale" if age > pack.stale_after_days else "current"
        heads = head_cost_entries(
            store, commodity, market_spec.market, as_of
        )
        lines: list[LandedLine] = []
        missing: list[str] = []
        for line_spec in pack.cost_lines:
            entry = heads.get(line_spec.line)
            if entry is None:
                missing.append(line_spec.line)
                lines.append(
                    LandedLine(
                        line=line_spec.line,
                        display=line_spec.display,
                        state="missing",
                        rate_paise_per_quintal=None,
                        entry_id=None,
                        entered_by=None,
                        entered_on=None,
                    )
                )
            else:
                lines.append(
                    LandedLine(
                        line=line_spec.line,
                        display=line_spec.display,
                        state="entered",
                        rate_paise_per_quintal=entry.rate_paise_per_quintal,
                        entry_id=entry.entry_id,
                        entered_by=entry.entered_by,
                        entered_on=entry.entered_on,
                    )
                )
        if price_paise is None or missing:
            landed = None
            state = "not_computable"
        else:
            landed = price_paise + sum(
                line.rate_paise_per_quintal
                for line in lines
                if line.rate_paise_per_quintal is not None
            )
            state = "computable"
        rows.append(
            LandedMarketRow(
                market=market_spec.market,
                display=market_spec.display,
                price_state=price_state,
                price_paise=price_paise,
                price_date=price_date,
                lines=lines,
                landed_paise=landed,
                state=state,
                missing_lines=missing,
                rank=None,
            )
        )
    computable = sorted(
        (r for r in rows if r.state == "computable"),
        key=lambda r: (r.landed_paise, r.market),
    )
    ranks = {row.market: i + 1 for i, row in enumerate(computable)}
    rows = [
        row.model_copy(update={"rank": ranks.get(row.market)}) for row in rows
    ]
    comparison = LandedComparison(
        comparison_id="",
        commodity=commodity,
        as_of=as_of,
        pack_version=pack.version,
        priced_for=priced_for,
        rows=rows,
        scope_note=GEO_SCOPE_NOTE,
    )
    return comparison.model_copy(
        update={"comparison_id": landed_content_id(comparison)}
    )


def compute_weather_row(
    store: Store, commodity: str, market: str, as_of: date, pack: GeoPack
) -> WeatherOverlayRow:
    rows = store.series(commodity, market, "weather_index", None, as_of)
    if not rows:
        return WeatherOverlayRow(
            market=market, state="no_current_data", latest_date=None,
            latest_value=None, window_facts=0, mean=None, std=None, z=None,
        )
    latest = rows[-1]
    window_begin = latest.obs_date - timedelta(days=pack.weather_window_days - 1)
    window = [r for r in rows if r.obs_date >= window_begin]
    if len(window) < pack.weather_min_days:
        return WeatherOverlayRow(
            market=market, state="insufficient_history",
            latest_date=latest.obs_date, latest_value=latest.value,
            window_facts=len(window), mean=None, std=None, z=None,
        )
    values = [r.value for r in window]
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = math.sqrt(variance)
    mean = round(mean, 6)
    std = round(std, 6)
    if std == 0.0:
        return WeatherOverlayRow(
            market=market, state="flat", latest_date=latest.obs_date,
            latest_value=latest.value, window_facts=len(window),
            mean=mean, std=std, z=None,
        )
    z = round((latest.value - mean) / std, 4)
    state = "deviating" if abs(z) >= pack.weather_deviation_z else "within"
    return WeatherOverlayRow(
        market=market, state=state, latest_date=latest.obs_date,
        latest_value=latest.value, window_facts=len(window),
        mean=mean, std=std, z=z,
    )


def _open_alert_state(
    store: Store, commodity: str, market: str, as_of: date
) -> tuple[int, str | None]:
    """Alerts for one market whose folded state at the end of
    as_of is open or acknowledged, and their top severity."""
    pack = load_alert_pack()
    now = datetime.combine(as_of, time.max)
    count = 0
    top: str | None = None
    for alert in store.list_alerts(commodity, market):
        if alert.raised_at > now:
            continue
        acts = [
            a for a in store.list_alert_acts(alert.alert_id)
            if a.acted_at <= now
        ]
        state = fold_state(alert, acts, now, pack)
        if state["state"] == "closed":
            continue
        count += 1
        if top is None or SEVERITY_RANK[alert.severity] > SEVERITY_RANK[top]:
            top = alert.severity
    return count, top


def compute_market_map(
    store: Store,
    commodity: str,
    as_of: date,
    pack: GeoPack,
    basis_reading: BasisReading,
) -> MarketMap:
    spec = BY_NAME.get(commodity)
    if spec is None:
        raise GeoError(f"unknown commodity {commodity!r}")
    if (
        basis_reading.commodity != commodity
        or basis_reading.as_of != as_of
        or basis_reading.pack_version != pack.version
    ):
        raise GeoError(
            "the pinned basis reading does not match this map's "
            "commodity, as-of and pack"
        )
    geography = {g.market: g for g in pack.geography}
    basis_rows = {row.market: row for row in basis_reading.rows}
    active_events = [
        ActiveEventRef(
            event_id=event.event_id,
            event_class=event.event_class,
            window_start=event.window_start,
            window_end=event.window_end,
        )
        for event in store.list_market_events(commodity)
        if event.window_start <= as_of
        and (event.window_end is None or as_of <= event.window_end)
    ]
    cells: list[MapCell] = []
    for market_spec in spec.markets:
        geo = geography.get(market_spec.market)
        if geo is None:
            raise GeoError(
                f"the geo pack's geography names no cell for "
                f"market {market_spec.market!r}"
            )
        price_paise, price_date = _latest_price(
            store, commodity, market_spec.market, as_of
        )
        if price_paise is None:
            data_state = "no_current_data"
        else:
            age = (as_of - price_date).days
            data_state = "stale" if age > pack.stale_after_days else "current"
        basis_row = basis_rows.get(market_spec.market)
        if basis_row is None:
            raise GeoError(
                f"the pinned basis reading carries no row for "
                f"market {market_spec.market!r}"
            )
        open_alerts, top_severity = _open_alert_state(
            store, commodity, market_spec.market, as_of
        )
        cells.append(
            MapCell(
                market=market_spec.market,
                display=market_spec.display,
                region=geo.region,
                grid_row=geo.grid_row,
                grid_col=geo.grid_col,
                data_state=data_state,
                price_paise=price_paise,
                price_date=price_date,
                basis_classification=basis_row.classification,
                current_spread_paise=basis_row.current_spread_paise,
                open_alerts=open_alerts,
                top_severity=top_severity,
                weather=compute_weather_row(
                    store, commodity, market_spec.market, as_of, pack
                ),
                series_href=(
                    f"/series?commodity={commodity}"
                    f"&market={market_spec.market}&driver=modal_price"
                ),
            )
        )
    draft = MarketMap(
        map_id="",
        commodity=commodity,
        as_of=as_of,
        pack_version=pack.version,
        basis_reading_id=basis_reading.reading_id,
        active_events=active_events,
        cells=cells,
        html="",
    )
    html = render_market_map(draft)
    market_map = draft.model_copy(update={"html": html})
    return market_map.model_copy(update={"map_id": map_content_id(market_map)})
