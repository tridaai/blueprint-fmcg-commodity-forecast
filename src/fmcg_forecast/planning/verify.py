"""Re-performance verification for planning artefacts.

The verifier trusts nothing stored. A plan is re-checked
structurally (content address, the desk-entered origin, the
month discipline). An assessment is re-performed end to end —
the engine runs again over the stored plan, the pinned price
source (head forecast, or the adopted run's fork), the pinned
signal and the assessment's own pack versions — and compared
field for field. Every figure's lineage walk is re-checked
against the store through the R7 lineage verifier, and the
provenance separation is checked on its own lines: a desk
figure's walk is exactly the desk fact, a market figure's walk
contains no desk fact, a mixed figure's walk carries exactly
one. The option ranking is re-sorted by the pack's criteria and
compared. The pinned forecast (or fork) and the pinned signal
are themselves re-performed, so an assessment resting on a
tampered input fails here too.
"""

from __future__ import annotations

from fmcg_forecast.dashboards.models import DashboardFigure
from fmcg_forecast.dashboards.verify import lineage_problems
from fmcg_forecast.forecast.verify import verify_forecast
from fmcg_forecast.planning.engine import PlanningError, compute_assessment
from fmcg_forecast.planning.models import (
    CoverageAssessment,
    RequirementPlan,
    assessment_content_id,
    plan_content_id,
)
from fmcg_forecast.planning.pack import load_planning_pack
from fmcg_forecast.signals.verify import verify_signal
from fmcg_forecast.store import Store


def verify_plan(plan: RequirementPlan) -> list[str]:
    """Return the list of problems with a stored requirement plan."""
    problems: list[str] = []
    if plan_content_id(plan) != plan.plan_id:
        problems.append(
            f"content id mismatch: stored {plan.plan_id}, recomputed "
            f"{plan_content_id(plan)} — the artefact was altered "
            "after entry"
        )
    if plan.origin != "desk_entered":
        problems.append(
            f"plan origin is {plan.origin!r}, not desk_entered — a "
            "requirement plan is the desk's statement or it is nothing"
        )
    months = [line.month for line in plan.lines]
    if months != sorted(months) or len(set(months)) != len(months):
        problems.append("plan lines are not one per month, in month order")
    for line in plan.lines:
        if line.month.day != 1:
            problems.append(
                f"plan line month {line.month} is not a month's first day"
            )
        if line.required_tonnes < 0:
            problems.append(
                f"plan line {line.month} requires negative tonnes"
            )
    if plan.opening_stock_tonnes < 0:
        problems.append("opening stock is negative")
    return problems


def verify_assessment(
    store: Store, assessment: CoverageAssessment
) -> list[str]:
    """Return the list of problems with a stored coverage assessment."""
    problems: list[str] = []
    if assessment_content_id(assessment) != assessment.assessment_id:
        problems.append(
            f"content id mismatch: stored {assessment.assessment_id}, "
            f"recomputed {assessment_content_id(assessment)} — the "
            "artefact was altered after computation"
        )
    plan = store.get_requirement_plan(assessment.plan_id)
    if plan is None:
        problems.append(f"plan {assessment.plan_id} is not in the store")
        return problems
    problems.extend(f"plan: {p}" for p in verify_plan(plan))

    if assessment.basis_kind == "adopted_scenario":
        run = (
            store.get_scenario(assessment.scenario_id)
            if assessment.scenario_id
            else None
        )
        if run is None:
            problems.append(
                f"scenario {assessment.scenario_id} is not in the store"
            )
            return problems
        price_source = run.fork
        if price_source.forecast_id != assessment.forecast_id:
            problems.append(
                f"assessment prices on {assessment.forecast_id} but "
                f"scenario {run.scenario_id}'s fork is "
                f"{price_source.forecast_id}"
            )
        base = store.get_forecast(run.base_forecast_id)
        if base is None:
            problems.append(
                f"the scenario's base forecast {run.base_forecast_id} "
                "is not in the store"
            )
            return problems
        signal_forecast_id = base.forecast_id
    else:
        found = store.get_forecast(assessment.forecast_id)
        if found is None:
            problems.append(
                f"forecast {assessment.forecast_id} is not in the store"
            )
            return problems
        price_source = found
        signal_forecast_id = found.forecast_id
    problems.extend(
        f"price source: {p}" for p in verify_forecast(price_source)
    )

    signal = store.get_buy_signal(assessment.signal_id)
    if signal is None:
        problems.append(
            f"pinned signal {assessment.signal_id} is not in the store"
        )
        return problems
    if signal.forecast_id != signal_forecast_id:
        problems.append(
            f"pinned signal {signal.signal_id} was computed on "
            f"{signal.forecast_id}, not the assessment's official "
            f"forecast {signal_forecast_id}"
        )
    if signal.value != assessment.signal_value:
        problems.append(
            f"assessment states signal {assessment.signal_value!r} "
            f"but the pinned signal reads {signal.value!r}"
        )
    problems.extend(f"signal: {p}" for p in verify_signal(store, signal))

    try:
        pack = load_planning_pack(assessment.pack_version)
    except ValueError as exc:
        problems.append(str(exc))
        return problems
    try:
        fresh = compute_assessment(
            store,
            plan,
            price_source,
            assessment.basis_kind,
            assessment.scenario_id,
            assessment.scenario_status_at_assessment,
            signal,
            pack,
        )
    except PlanningError as exc:
        problems.append(f"assessment no longer re-performs: {exc}")
        return problems
    stored = assessment.model_dump(mode="json")
    recomputed = fresh.model_dump(mode="json")
    for key in sorted(stored):
        if key == "assessment_id":
            continue
        if stored[key] != recomputed[key]:
            problems.append(
                f"field {key} differs on re-performance: stored "
                f"{stored[key]!r}, recomputed {recomputed[key]!r}"
            )

    for figure in assessment.figures:
        problems.extend(
            lineage_problems(
                store,
                DashboardFigure(
                    key=figure.key,
                    label=figure.label,
                    value=figure.value,
                    unit=figure.unit,
                    artefact_id=figure.artefact_id,
                    lineage=figure.lineage,
                ),
            )
        )
        kinds = [fact.kind for fact in figure.lineage]
        if figure.basis == "desk" and kinds != ["desk_entered"]:
            problems.append(
                f"figure {figure.key}: a desk figure's walk must be "
                f"exactly the desk-entered fact, found {kinds}"
            )
        if figure.basis == "market" and "desk_entered" in kinds:
            problems.append(
                f"figure {figure.key}: a market figure's walk "
                "contains a desk-entered fact — the provenances are mixed"
            )
        if figure.basis == "mixed" and kinds.count("desk_entered") != 1:
            problems.append(
                f"figure {figure.key}: a mixed figure's walk must "
                f"carry exactly one desk-entered fact, found "
                f"{kinds.count('desk_entered')}"
            )

    expected = sorted(
        assessment.options,
        key=lambda o: (o.cost_at_p50_inr, o.cost_at_p90_inr, o.name),
    )
    if [o.name for o in assessment.options] != [o.name for o in expected]:
        problems.append(
            "options are not in the pack's ranking order (expected "
            "cost, then adverse cost, then name)"
        )
    if [o.rank for o in assessment.options] != list(
        range(1, len(assessment.options) + 1)
    ):
        problems.append("option ranks are not 1..n in ranking order")
    return problems
