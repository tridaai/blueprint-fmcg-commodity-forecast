"""The geo pack — how basis, landed cost and the map are
judged, as data.

Everything Round 14 computes is stated here, versioned, never
buried in code: the reference-market rule, the history window
and the percentile method the band is built with, the paired-
days floor below which a band is named insufficient instead
of classified, the staleness bar for a current price, the
landed-cost line catalogue (the only lines a desk entry may
name), the ranking rule for landed comparisons, the weather
overlay's window and deviation bar, and the schematic
geography the map plots — approximate grid positions that
carry the shape of the country, stated as schematic, never
surveyed coordinates.

Money is integer paise throughout this layer: a stored price
is converted once, by rounding to the nearest paise, and every
spread, band edge and landed total is integer arithmetic from
there — a band edge can never drift by a float residue.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CostLineSpec(BaseModel):
    """One landed-cost line the desk may enter, as the pack
    states it."""

    line: str
    display: str
    rule: str = Field(
        description="What the line covers, stated"
    )


class MarketGeo(BaseModel):
    """One market's schematic place on the map."""

    market: str
    region: str = Field(
        description="The region label the map prints"
    )
    grid_row: int = Field(
        description="Schematic grid row, 0 at the north"
    )
    grid_col: int = Field(
        description="Schematic grid column, 0 at the west"
    )


class GeoPack(BaseModel):
    version: str
    reference_rule: str = Field(
        description="How a commodity's reference market is "
        "chosen, stated"
    )
    band_window_days: int = Field(
        description="Trailing calendar window of paired "
        "history the band is built from, ending at as_of"
    )
    band_low_quantile: float = Field(
        description="The band's lower edge quantile"
    )
    band_high_quantile: float = Field(
        description="The band's upper edge quantile"
    )
    percentile_rule: str = Field(
        description="How a quantile is read off the sorted "
        "paired spreads, stated"
    )
    min_paired_days: int = Field(
        description="Below this many paired days in the "
        "window the band is stated but the current spread "
        "is not classified — insufficient history, named"
    )
    stale_after_days: int = Field(
        description="A current price or paired date older "
        "than this many days before as_of is stale, named"
    )
    classification_rule: str = Field(
        description="How the current spread is classified "
        "against its band, stated"
    )
    cost_lines: list[CostLineSpec] = Field(
        description="The landed-cost line catalogue: a desk "
        "entry may name only these lines, and a landed cost "
        "needs every one of them present for its market"
    )
    landed_rule: str = Field(
        description="How a landed cost is composed and what "
        "an incomplete market reads, stated"
    )
    landed_ranking_rule: str = Field(
        description="The ONLY criteria landed markets are "
        "ranked by, stated"
    )
    weather_window_days: int = Field(
        description="Trailing window of weather-index facts "
        "the overlay's mean and spread are computed over"
    )
    weather_min_days: int = Field(
        description="Below this many weather facts the "
        "overlay names the market's weather insufficient"
    )
    weather_deviation_z: float = Field(
        description="Absolute z at or above which the "
        "overlay calls the latest weather deviating"
    )
    weather_rule: str = Field(
        description="How the overlay deviation is computed — "
        "from the same stored weather-index facts the "
        "forecast engine consumed, never a second source"
    )
    geography: list[MarketGeo] = Field(
        description="Schematic grid positions for every "
        "catalogue market — approximate, stated as such"
    )
    geography_note: str = Field(
        description="What the grid is and is not, stated"
    )
    scope_note: str


GEO_SCOPE_NOTE = (
    "comparison only — no purchase, transfer or trade is "
    "placed or instructed; procurement execution is out of "
    "scope by design"
)

# Schematic positions: rows run north to south, columns west
# to east, placed so the map carries India's shape (the
# north-western markets high and left, Bengaluru low centre).
# They are a reading aid, not coordinates.
GEOGRAPHY: tuple[MarketGeo, ...] = (
    MarketGeo(market="unjha", region="Gujarat (north)",
              grid_row=1, grid_col=0),
    MarketGeo(market="rajkot", region="Saurashtra (Gujarat)",
              grid_row=2, grid_col=0),
    MarketGeo(market="gondal", region="Saurashtra (Gujarat)",
              grid_row=3, grid_col=0),
    MarketGeo(market="jodhpur", region="Rajasthan (west)",
              grid_row=0, grid_col=1),
    MarketGeo(market="indore", region="Madhya Pradesh",
              grid_row=1, grid_col=2),
    MarketGeo(market="karnal", region="Haryana",
              grid_row=0, grid_col=2),
    MarketGeo(market="delhi_khari_baoli", region="Delhi",
              grid_row=0, grid_col=3),
    MarketGeo(market="nagpur", region="Maharashtra (Vidarbha)",
              grid_row=1, grid_col=3),
    MarketGeo(market="kanpur", region="Uttar Pradesh",
              grid_row=0, grid_col=4),
    MarketGeo(market="warangal", region="Telangana",
              grid_row=2, grid_col=3),
    MarketGeo(market="guntur", region="Andhra Pradesh",
              grid_row=3, grid_col=3),
    MarketGeo(market="bengaluru", region="Karnataka",
              grid_row=4, grid_col=2),
)


GEO_PACK_V1 = GeoPack(
    version="2026.10.1",
    reference_rule=(
        "A commodity's reference market is the first market "
        "the catalogue lists for it — the market whose "
        "catalogue price factor is 1.000. Every spread is "
        "this market's modal price minus the reference "
        "market's modal price on the same date, in paise."
    ),
    band_window_days=365,
    band_low_quantile=0.10,
    band_high_quantile=0.90,
    percentile_rule=(
        "A quantile is read off the sorted paired spreads "
        "by linear interpolation at rank q x (n - 1), and "
        "rounded to the nearest paise. The band median is "
        "the 0.50 quantile under the same rule."
    ),
    min_paired_days=60,
    stale_after_days=7,
    classification_rule=(
        "With at least the pack's minimum paired days, the "
        "current spread (the last paired date's spread) is "
        "wide when it sits above the band's upper edge, "
        "narrow when below the lower edge, and within "
        "otherwise. Below the floor the band figures are "
        "stated but no classification is assigned — the row "
        "reads insufficient_history. No paired date at all "
        "reads no_paired_history, with every figure absent."
    ),
    cost_lines=[
        CostLineSpec(
            line="freight",
            display="Freight to the desk",
            rule="The per-quintal cost of moving the "
            "commodity from this market to the desk's "
            "receiving point, as the desk states it.",
        ),
        CostLineSpec(
            line="handling",
            display="Handling and loading",
            rule="The per-quintal loading, unloading and "
            "market-fee cost at this market, as the desk "
            "states it.",
        ),
    ],
    landed_rule=(
        "A market's landed cost is its current modal price "
        "(the last observation on or before as_of, in "
        "paise) plus every catalogue cost line's standing "
        "desk-entered rate for that market — the latest "
        "entry entered on or before the as-of, so a rate "
        "entered later never reprices this comparison. "
        "A market "
        "missing any line reads not_computable and names "
        "each missing line — no line is ever assumed, "
        "borrowed from another market or defaulted. A "
        "market with no current price is not computable "
        "either, and says so."
    ),
    landed_ranking_rule=(
        "Computable markets rank by landed cost ascending, "
        "then market name ascending. Not-computable markets "
        "are never ranked. Nothing else ranks a market."
    ),
    weather_window_days=90,
    weather_min_days=20,
    weather_deviation_z=1.5,
    weather_rule=(
        "The overlay reads the market's stored "
        "weather-index facts over the trailing window "
        "ending at its latest fact on or before as_of: "
        "the deviation is (latest - mean) / population "
        "standard deviation over that window, rounded to "
        "4dp. It is computed from exactly the facts the "
        "forecast engine consumed — the overlay keeps no "
        "weather source of its own."
    ),
    geography=list(GEOGRAPHY),
    geography_note=(
        "Grid positions are schematic — placed by hand so "
        "the map carries the country's shape for reading. "
        "They are not coordinates, distances on the map "
        "mean nothing, and no figure is derived from them."
    ),
    scope_note=GEO_SCOPE_NOTE,
)


def load_geo_pack(version: str | None = None) -> GeoPack:
    """Load the geo pack, fail-closed.

    An unknown version is an error, never a silent fallback
    — an artefact computed under one pack must never be
    quietly re-read under another.
    """
    if version is None or version == GEO_PACK_V1.version:
        return GEO_PACK_V1
    raise ValueError(f"unknown geo pack version: {version!r}")
