"""The planning pack — how a plan is priced and ranked, as data.

The desk's requirement plan is its own statement; everything the
planner derives from it is stated here, versioned: the month
price rule (the mean of the pinned forecast's daily P50 — and,
for the adverse case, P90 — over the days of the month the
forecast covers, rounded to 4dp before valuing), the stock
allocation (first-in-first-out by month), the coverage-days
rule, the purchase-option shapes, and the ranking criteria.
Options are ranked ONLY by those criteria — expected cost, then
adverse cost, then name. The series' buy signal is pinned on
every assessment as context and is named in an option's notes
when an option runs against it, but it never enters the ranking
arithmetic: a ranking a signal could bend would not be the
pack's ranking.

Prices are INR per quintal throughout this blueprint; a tonne
is 10 quintals, stated here because every exposure figure
depends on it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class OptionShape(BaseModel):
    """One purchase option, as the pack states it."""

    name: str
    title: str
    rule: str = Field(
        description="How the option's schedule is built, stated"
    )


class PlanningPack(BaseModel):
    version: str
    quintals_per_tonne: int = Field(
        description="Prices are per quintal; exposure multiplies "
        "tonnes by this before valuing"
    )
    month_price_rule: str = Field(
        description="How a plan month is priced from the pinned "
        "forecast, stated"
    )
    allocation_rule: str = Field(
        description="How opening stock is allocated across plan "
        "months, stated"
    )
    coverage_rule: str = Field(
        description="How coverage days are computed, stated"
    )
    options: list[OptionShape]
    ranking_rule: str = Field(
        description="The ONLY criteria options are ranked by, stated"
    )
    signal_rule: str = Field(
        description="What the pinned buy signal may and may not "
        "do to an assessment, stated"
    )


PLANNING_PACK_V1 = PlanningPack(
    version="2026.10.1",
    quintals_per_tonne=10,
    month_price_rule=(
        "A plan month is priced at the mean of the pinned "
        "forecast's daily P50 over the days of that month the "
        "forecast covers (the adverse case uses the daily P90 "
        "mean), each mean rounded to 4dp before any valuing. A "
        "month the forecast covers only in part is priced on its "
        "covered days and named partial; a month with no covered "
        "day is beyond the horizon — named, never valued."
    ),
    allocation_rule=(
        "Opening stock is allocated first-in-first-out by month: "
        "each month in order is covered up to its requirement "
        "until the stock is exhausted; the remainder of each "
        "month is its uncovered tonnes. The stockout month is "
        "the first month with uncovered tonnes."
    ),
    coverage_rule=(
        "Coverage days = opening stock / (total required tonnes "
        "/ total calendar days across the plan's months), "
        "rounded to 4dp — how long the desk's stock lasts at the "
        "plan's own average daily burn."
    ),
    options=[
        OptionShape(
            name="cover_now",
            title="Cover everything now",
            rule="Every uncovered tonne is scheduled in its own "
            "month at the spot price (the last observed modal "
            "price on or before the forecast's as_of). The price "
            "is certain, so expected and adverse cost are equal.",
        ),
        OptionShape(
            name="cover_staged",
            title="Cover the first month now, phase the rest",
            rule="The first month with uncovered tonnes is "
            "scheduled at spot; every later month is scheduled in "
            "its own month at that month's forecast mean (P50 for "
            "the expected cost, P90 for the adverse cost).",
        ),
        OptionShape(
            name="cover_phased",
            title="Phase every month at its forecast price",
            rule="Every uncovered tonne is scheduled in its own "
            "month at that month's forecast mean (P50 expected, "
            "P90 adverse) — nothing is bought ahead.",
        ),
    ],
    ranking_rule=(
        "Expected cost (the P50-basis total) ascending, then "
        "adverse cost (the P90-basis total) ascending, then "
        "option name ascending. Nothing else ranks an option — "
        "not the signal, not the desk's preference."
    ),
    signal_rule=(
        "The series' current buy signal (computed on the "
        "official head forecast) is pinned on the assessment as "
        "context. When the signal is wait, the cover_now option "
        "carries the stated caution that it buys against the "
        "signal. The signal never enters the ranking arithmetic."
    ),
)


def load_planning_pack(version: str | None = None) -> PlanningPack:
    """Load the planning pack, fail-closed."""
    if version is None or version == PLANNING_PACK_V1.version:
        return PLANNING_PACK_V1
    raise ValueError(f"unknown planning pack version: {version!r}")
