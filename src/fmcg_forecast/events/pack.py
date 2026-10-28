"""The event pack — classes, channels and the stated rules, as data.

Law 4's mechanics are stated here, versioned, never buried in code:
which event classes exist, which driver channel each class may
claim as its transmission, the vocabulary of estimation bases a
transmission may rest on, how a declared event becomes a per-day
log-price path (the ramp, the window, the post-window decay), how
wide a shocked forecast's intervals run, and how a claimed
transmission is checked against measured history (the
seasonally-matched year-over-year comparison, with its stated
verification band). A change to any of it is a new pack version,
and every registered event names the version it was declared
under.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# The driver channels a transmission may name. ``modal_price`` is
# the direct price channel — an event whose mechanism is stated
# directly in price terms. The others are the dataset's reported
# drivers the shock moves on its way to the price.
CHANNELS: tuple[str, ...] = (
    "modal_price",
    "arrivals",
    "stock_level",
    "import_flow",
    "export_flow",
    "weather_index",
)


class EventPack(BaseModel):
    version: str
    classes: dict[str, list[str]] = Field(
        description="Event class -> the transmission channels a "
        "declaration of that class may claim"
    )
    bases: list[str] = Field(
        description="The named estimation bases a transmission may "
        "rest on: announced_measure (an announced policy measure "
        "with a stated size), measured_analogue (a past event of "
        "the same class measured in this dataset), desk_estimate "
        "(analyst judgement, named as such)"
    )
    ramp_days: int = Field(
        description="An event's effect ramps linearly from zero to "
        "its peak over this many days from the window's start"
    )
    interval_widening_factor: float = Field(
        description="On any forecast day where a declared event's "
        "adjustment is non-zero, the interval growth factor is "
        "multiplied by this — a shocked forecast carries honestly "
        "wider bands, by a stated factor, never a silent tweak"
    )
    measurement_pre_span_days: int = Field(
        description="Transmission measurement: the pre-event window "
        "spans this many days..."
    )
    measurement_pre_gap_days: int = Field(
        description="...ending this many days before the window starts"
    )
    measurement_post_gap_days: int = Field(
        description="The post-event window opens this many days "
        "after the window starts..."
    )
    measurement_post_span_days: int = Field(
        description="...and spans at most this many days (clipped "
        "at the event window's end for shorter events)"
    )
    measurement_prior_year_shift_days: int = Field(
        description="Both windows are re-measured shifted back by "
        "this many days; the effect is the ratio of ratios, which "
        "differences out seasonality and trend"
    )
    verified_band_low: float = Field(
        description="A claimed transmission verifies when the "
        "measured log effect, divided by the claimed peak log "
        "effect, sits inside [verified_band_low, verified_band_high] "
        "with the same sign"
    )
    verified_band_high: float
    impact_min_obs: int = Field(
        description="The impact view fits its no-event baseline on "
        "pre-window history only, and needs at least this many "
        "price observations..."
    )
    impact_min_span_days: int = Field(description="...spanning at least this many days")
    path_rule: str = Field(description="How an event becomes a per-day log-price path, stated")
    measurement_rule: str = Field(description="How a claimed transmission is measured, stated")
    impact_rule: str = Field(description="How the what-happened view is computed, stated")


EVENT_PACK_V1 = EventPack(
    version="2026.10.1",
    classes={
        "tariff_change": ["import_flow", "modal_price"],
        "export_restriction": ["export_flow", "modal_price"],
        "import_policy": ["import_flow", "modal_price"],
        "weather_shock": ["weather_index", "modal_price"],
        "logistics_disruption": ["arrivals", "modal_price"],
        "demand_shock": ["modal_price"],
    },
    bases=["announced_measure", "measured_analogue", "desk_estimate"],
    ramp_days=3,
    interval_widening_factor=1.25,
    measurement_pre_span_days=20,
    measurement_pre_gap_days=5,
    measurement_post_gap_days=5,
    measurement_post_span_days=15,
    measurement_prior_year_shift_days=365,
    verified_band_low=0.5,
    verified_band_high=1.5,
    impact_min_obs=250,
    impact_min_span_days=365,
    path_rule=(
        "for one event with peak log-price effect m, window "
        "[start, end] (end may be open) and stated decay_days D: a "
        "day before start carries 0; inside the window the effect "
        "is m x min(1, (age + 1) / ramp_days) with age the days "
        "since start; after the window closes it decays linearly, "
        "m x max(0, 1 - days_since_end / D), reaching zero D days "
        "after the end; an open-ended window never decays"
    ),
    measurement_rule=(
        "per market of the event's commodity: ratio of ratios of "
        "mean modal price — the post/pre move in the event's own "
        "windows divided by the same calendar windows one year "
        "earlier (pre: measurement_pre_span_days ending "
        "measurement_pre_gap_days before the start; post: opening "
        "measurement_post_gap_days after the start, spanning at "
        "most measurement_post_span_days, clipped at the window "
        "end). The measured effect is the median log ratio across "
        "the commodity's markets; it verifies the claim when the "
        "sign agrees and measured / claimed sits inside the "
        "stated band. A window whose measurement windows fall "
        "outside observed history is not_measurable, named — "
        "never estimated"
    ),
    impact_rule=(
        "the no-event baseline is the forecast engine's baseline "
        "method (OLS of log price on trend + day-of-year "
        "seasonality, anchored at the series' first observed day) "
        "fitted on observations strictly before the window start "
        "only, then projected through the window and its decay "
        "tail; each observed day's log effect is log(observed) - "
        "log(baseline); days with no observation carry no effect, "
        "never an interpolated one"
    ),
)


def load_event_pack(version: str | None = None) -> EventPack:
    """Fail-closed loader: only the shipped pack exists in R5.

    An unknown version is an error, never a silent fallback — an
    event must name the pack it was actually declared under.
    """
    if version is None or version == EVENT_PACK_V1.version:
        return EVENT_PACK_V1
    raise ValueError(f"unknown event pack version: {version!r}")
