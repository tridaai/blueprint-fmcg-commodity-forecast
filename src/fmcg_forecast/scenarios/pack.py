"""The scenario pack — the bounded lever catalogue, as data.

Law 5's mechanics are stated here, versioned, never buried in
code: which levers a scenario may move, which driver line each
lever moves, in what unit, inside what bounds, and by what stated
conversion the lever's desk-sized number (a percentage, a count of
days) becomes a shift of the engine's driver inputs. A what-if
outside the catalogue — or outside a bound — is refused, never
improvised. A change to any of it is a new pack version, and every
scenario request and run names the version it was made under.

The conversions (performed in shifts.py):

- ``arrivals_shift_pct`` — future arrivals are scaled by
  (1 + p/100) on every horizon day. The arrivals input is
  z(log arrivals), so the shift in input units is
  ln(1 + p/100) / sd(log arrivals), the sd taken over the series'
  observed history up to the run's as_of.
- ``stock_cover_days`` — the stock level is days of cover; the
  shift adds d / sd(stock level) to the standardised stock input
  on every horizon day, the sd over the same history.
- ``trade_flow_shift_pct`` — the last observed import flow is
  scaled by (1 + p/100), exports unchanged; the net-flow input is
  z(imports - exports), so the shift in input units is
  import_last x p/100 / sd(net flow), constant across the horizon.
- ``weather_deviation`` — the weather input is the raw index, so
  the shift adds d to the raw path on every horizon day, the
  result clipped to the index's stated range [-1, 1].
- ``sentiment_override`` — replaces the sentiment line's future
  path starting value: the path becomes override x persistence^h.
  Only where the base run's sentiment line was estimated; a thin
  corpus stays not-estimable under a scenario too.
- ``event`` / ``event_extension`` / ``hypothetical_event`` — the
  events slot: a registry event not in the base, a registry event
  in the base with its window prolonged, or a scenario-local
  event of a pack class whose stated transmission is a peak price
  effect in percent, carried through the event pack's path rule.
  Event levers move the events line only — never a driver input.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

LEVER_NAMES: tuple[str, ...] = (
    "arrivals_shift_pct",
    "stock_cover_days",
    "trade_flow_shift_pct",
    "weather_deviation",
    "sentiment_override",
    "event",
    "event_extension",
    "hypothetical_event",
)

# The driver line each numeric lever moves. Event levers move the
# events slot and are keyed separately.
LEVER_DRIVERS: dict[str, str] = {
    "arrivals_shift_pct": "arrivals",
    "stock_cover_days": "stock_level",
    "trade_flow_shift_pct": "trade_flow",
    "weather_deviation": "weather_index",
    "sentiment_override": "sentiment",
}


class LeverSpec(BaseModel):
    name: str
    unit: str = Field(description="The unit the value is stated in")
    min_value: float
    max_value: float
    rule: str = Field(description="How the lever moves its driver, stated")


class ScenarioPack(BaseModel):
    version: str
    levers: dict[str, LeverSpec] = Field(
        description="The bounded lever catalogue: these levers, "
        "these bounds, nothing else"
    )
    days_per_month: int = Field(
        description="'Another month' in a spoken what-if is this "
        "many days — stated, so the parse is checkable"
    )
    hypothetical_decay_days: int = Field(
        description="A hypothetical event's effect decays linearly "
        "to zero over this many days after its window closes, "
        "unless the lever states its own decay"
    )
    hypothetical_start_offset_max_days: int = Field(
        description="A hypothetical event may open at most this "
        "many days into the forecast horizon"
    )
    hypothetical_duration_max_days: int = Field(
        description="A hypothetical event's window may span at "
        "most this many days"
    )
    weather_index_min: float = Field(description="The weather index's stated range")
    weather_index_max: float
    grammar: str = Field(description="The plain-language grammar, stated")


SCENARIO_PACK_V1 = ScenarioPack(
    version="2026.10.1",
    levers={
        "arrivals_shift_pct": LeverSpec(
            name="arrivals_shift_pct",
            unit="percent of future arrivals level",
            min_value=-40.0,
            max_value=40.0,
            rule="future arrivals scaled by (1 + p/100) on every "
            "horizon day; in the arrivals input (z of log arrivals) "
            "this adds ln(1 + p/100) / sd(log arrivals) per day",
        ),
        "stock_cover_days": LeverSpec(
            name="stock_cover_days",
            unit="days of stock cover",
            min_value=-30.0,
            max_value=30.0,
            rule="adds d / sd(stock level) to the standardised "
            "stock-cover input on every horizon day",
        ),
        "trade_flow_shift_pct": LeverSpec(
            name="trade_flow_shift_pct",
            unit="percent of the last observed import flow",
            min_value=-60.0,
            max_value=60.0,
            rule="the last observed import flow scaled by "
            "(1 + p/100), exports unchanged; in the trade-flow "
            "input (z of imports - exports) this adds import_last "
            "x p/100 / sd(net flow) per day",
        ),
        "weather_deviation": LeverSpec(
            name="weather_deviation",
            unit="weather index points",
            min_value=-0.5,
            max_value=0.5,
            rule="adds d to the raw weather index path on every "
            "horizon day, clipped to the index's stated range",
        ),
        "sentiment_override": LeverSpec(
            name="sentiment_override",
            unit="sentiment index value",
            min_value=-1.0,
            max_value=1.0,
            rule="the sentiment future path starts at the override "
            "and decays at its measured persistence; only where "
            "the base run estimated the sentiment line",
        ),
        "event": LeverSpec(
            name="event",
            unit="registry event id",
            min_value=0.0,
            max_value=0.0,
            rule="a declared event from the registry, not already "
            "in the base forecast, enters the fork's events slot "
            "with its registry path",
        ),
        "event_extension": LeverSpec(
            name="event_extension",
            unit="days added to the event's window",
            min_value=1.0,
            max_value=90.0,
            rule="a declared event already in the base forecast "
            "has its window prolonged by this many days; the "
            "prolonged event is a scenario-local copy under the "
            "event pack's path rule, the registry record untouched",
        ),
        "hypothetical_event": LeverSpec(
            name="hypothetical_event",
            unit="percent peak price effect, days",
            min_value=-35.0,
            max_value=35.0,
            rule="a scenario-local event of a stated class whose "
            "peak log-price effect is ln(1 + p/100) for the stated "
            "percent p, over a window of the stated duration "
            "opening at the stated offset into the horizon, under "
            "the event pack's path rule",
        ),
    },
    days_per_month=30,
    hypothetical_decay_days=10,
    hypothetical_start_offset_max_days=60,
    hypothetical_duration_max_days=90,
    weather_index_min=-1.0,
    weather_index_max=1.0,
    grammar=(
        "A what-if is clauses joined by 'and', commas or "
        "semicolons, optionally opened by 'what if' and closed by "
        "'?'. Each clause must match exactly one catalogue shape: "
        "'arrivals drop|rise [by] N%' (also up/down); 'stock cover "
        "rises|falls [by] N days' (also up/down); 'trade flow' or "
        "'imports rise|drop [by] N%'; 'weather index deviation "
        "[of] +/-N' or 'weather index rises|falls by N'; "
        "'sentiment [index] to +/-N'; 'the tariff|export ban|"
        "drought stays|holds [for] another|N [more] months' (an "
        "extension of the matching declared event in the base "
        "forecast); 'extend event EVT-... by N days'; 'add event "
        "EVT-...'; or 'a [new] <event class> pushes prices up by "
        "N% for D days' / 'cuts prices by N% for D days' (a "
        "hypothetical event). Numbers are digits, except months, "
        "which may be number words (another = one). A clause that "
        "matches no shape is refused with the clause named "
        "verbatim; a value outside its lever's bound is refused "
        "with the bound named; each driver may be moved by at "
        "most one clause."
    ),
)


def load_scenario_pack(version: str | None = None) -> ScenarioPack:
    """Fail-closed loader: only the shipped pack exists in R6.

    An unknown version is an error, never a silent fallback — a
    scenario must name the pack it was actually parsed and run
    under.
    """
    if version is None or version == SCENARIO_PACK_V1.version:
        return SCENARIO_PACK_V1
    raise ValueError(f"unknown scenario pack version: {version!r}")
