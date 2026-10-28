"""The commodity catalogue: what Verdanta Foods' desk watches.

Seven commodities across their real Indian market geographies, each
with the generation parameters the dataset generator plants
(seasonality anchored on the harvest calendar, trend, flow bases).
These are stated constants of the blueprint's dataset — the generator
manifest repeats the planted structure so the eval gate can grade
against it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MarketSpec:
    market: str
    display: str
    price_factor: float
    arrivals_factor: float


@dataclass(frozen=True)
class CommoditySpec:
    commodity: str
    display: str
    base_price: float  # INR/quintal at the reference market
    markets: tuple[MarketSpec, ...]
    harvest_doy: int  # day of year at the arrivals peak
    price_seasonal_amp: float  # log-price seasonal amplitude
    arrivals_base: float  # quintals/day at the reference market
    arrivals_seasonal_amp: float
    trend_per_year: float  # log drift per year
    import_base: float  # quintals/day
    export_base: float  # quintals/day
    reporting: str = "mon_sat"  # coffee reports tue_fri
    drivers: tuple[str, ...] = (
        "modal_price",
        "arrivals",
        "stock_level",
        "import_flow",
        "export_flow",
        "weather_index",
    )


COFFEE_DRIVERS: tuple[str, ...] = ("modal_price", "arrivals", "weather_index")

COMMODITIES: tuple[CommoditySpec, ...] = (
    CommoditySpec(
        commodity="wheat",
        display="Wheat",
        base_price=2450.0,
        markets=(
            MarketSpec("delhi_khari_baoli", "Delhi (Khari Baoli)", 1.000, 1.00),
            MarketSpec("indore", "Indore", 0.985, 0.80),
            MarketSpec("kanpur", "Kanpur", 0.990, 0.70),
        ),
        harvest_doy=105,
        price_seasonal_amp=0.045,
        arrivals_base=42000.0,
        arrivals_seasonal_amp=1.10,
        trend_per_year=0.018,
        import_base=300.0,
        export_base=900.0,
    ),
    CommoditySpec(
        commodity="basmati_rice",
        display="Basmati rice",
        base_price=4300.0,
        markets=(
            MarketSpec("delhi_khari_baoli", "Delhi (Khari Baoli)", 1.000, 1.00),
            MarketSpec("karnal", "Karnal", 0.975, 0.85),
        ),
        harvest_doy=305,
        price_seasonal_amp=0.050,
        arrivals_base=26000.0,
        arrivals_seasonal_amp=1.20,
        trend_per_year=0.022,
        import_base=50.0,
        export_base=5200.0,
    ),
    CommoditySpec(
        commodity="soybean",
        display="Soybean",
        base_price=4650.0,
        markets=(
            MarketSpec("indore", "Indore", 1.000, 1.00),
            MarketSpec("nagpur", "Nagpur", 0.990, 0.75),
        ),
        harvest_doy=290,
        price_seasonal_amp=0.055,
        arrivals_base=31000.0,
        arrivals_seasonal_amp=1.25,
        trend_per_year=0.020,
        import_base=2600.0,
        export_base=150.0,
    ),
    CommoditySpec(
        commodity="groundnut",
        display="Groundnut",
        base_price=5900.0,
        markets=(
            MarketSpec("rajkot", "Rajkot", 1.000, 1.00),
            MarketSpec("gondal", "Gondal", 1.005, 0.80),
        ),
        harvest_doy=320,
        price_seasonal_amp=0.050,
        arrivals_base=19000.0,
        arrivals_seasonal_amp=1.15,
        trend_per_year=0.015,
        import_base=700.0,
        export_base=800.0,
    ),
    CommoditySpec(
        commodity="chili",
        display="Chili (dry)",
        base_price=16800.0,
        markets=(
            MarketSpec("guntur", "Guntur", 1.000, 1.00),
            MarketSpec("warangal", "Warangal", 0.990, 0.70),
        ),
        harvest_doy=45,
        price_seasonal_amp=0.070,
        arrivals_base=9500.0,
        arrivals_seasonal_amp=1.30,
        trend_per_year=0.030,
        import_base=250.0,
        export_base=2100.0,
    ),
    CommoditySpec(
        commodity="cumin",
        display="Cumin",
        base_price=26800.0,
        markets=(
            MarketSpec("unjha", "Unjha", 1.000, 1.00),
            MarketSpec("jodhpur", "Jodhpur", 0.995, 0.65),
        ),
        harvest_doy=75,
        price_seasonal_amp=0.065,
        arrivals_base=7200.0,
        arrivals_seasonal_amp=1.35,
        trend_per_year=0.025,
        import_base=120.0,
        export_base=2600.0,
    ),
    CommoditySpec(
        commodity="coffee",
        display="Coffee",
        base_price=33500.0,
        markets=(MarketSpec("bengaluru", "Bengaluru", 1.000, 1.00),),
        harvest_doy=350,
        price_seasonal_amp=0.060,
        arrivals_base=2600.0,
        arrivals_seasonal_amp=0.90,
        trend_per_year=0.028,
        import_base=900.0,
        export_base=1700.0,
        reporting="tue_fri",
        drivers=COFFEE_DRIVERS,
    ),
)

BY_NAME: dict[str, CommoditySpec] = {c.commodity: c for c in COMMODITIES}

# Drivers a commodity does not report are named gaps (Law 7): coffee
# has no stock or trade-flow reporting in this dataset.
ALL_DRIVERS: tuple[str, ...] = (
    "modal_price",
    "arrivals",
    "stock_level",
    "import_flow",
    "export_flow",
    "weather_index",
)


def missing_drivers(spec: CommoditySpec) -> list[str]:
    return [d for d in ALL_DRIVERS if d not in spec.drivers]
