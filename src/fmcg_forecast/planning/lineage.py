"""Provenance walks for planning figures (R8, extending F20-DR3).

The separation rule is structural: a desk figure's walk is
exactly one fact — the ``desk_entered`` terminal fact naming the
plan, its enterer and its date. A market figure's walk is the
R7 forecast walk (or the signal walk) and never contains a desk
fact; on the adopted-scenario basis the price walk is the R7
scenario walk — through the run artefact that holds the fork,
to the base forecast and its stored facts — because the fork
itself is not a forecast artefact on record. A mixed figure — the desk's tonnes valued at market
prices — carries the desk fact alongside the market walk, so a
reader can see both halves of where the number came from, and
the verifier counts the desk facts on every walk.
"""

from __future__ import annotations

from fmcg_forecast.dashboards.models import LineageFact
from fmcg_forecast.planning.models import RequirementPlan


def plan_fact(plan: RequirementPlan) -> LineageFact:
    """The terminal fact a desk figure rests on."""
    return LineageFact(
        kind="desk_entered",
        ref=plan.plan_id,
        detail=(
            f"requirement plan for {plan.commodity} at {plan.market}: "
            f"{len(plan.lines)} month(s), opening stock "
            f"{plan.opening_stock_tonnes} t — the desk's own "
            "statement, not market data"
        ),
        source=f"desk-entered by {plan.entered_by}",
        fact_date=plan.entered_on,
    )
