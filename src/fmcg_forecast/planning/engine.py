"""The planning engine — the pack's arithmetic, performed.

Pure computation over one requirement plan, one pinned price
source (a forecast artefact — the official head, or an adopted
scenario's fork), the pinned buy signal and the store (for spot
and the lineage walks). Stock is allocated first-in-first-out;
months are priced by the pack's month rule; exposure is
uncovered tonnes x quintals per tonne x the month's mean P50,
rounded to the paisa per month; options are built by the pack's
stated shapes and ranked by the pack's stated criteria only.
The verifier re-performs this function and compares every
field, so the arithmetic here is the whole contract.
"""

from __future__ import annotations

import calendar
from datetime import date

from fmcg_forecast.dashboards.lineage import forecast_lineage, scenario_lineage
from fmcg_forecast.forecast.models import Forecast
from fmcg_forecast.planning.lineage import plan_fact
from fmcg_forecast.planning.models import (
    ASSESSMENT_SCOPE_NOTE,
    CoverageAssessment,
    MonthCoverage,
    OptionLine,
    PlanningFigure,
    PurchaseOption,
    RequirementPlan,
    assessment_content_id,
)
from fmcg_forecast.planning.pack import PlanningPack
from fmcg_forecast.signals.lineage import signal_lineage
from fmcg_forecast.signals.models import BuySignal
from fmcg_forecast.store import Store


class PlanningError(ValueError):
    """An assessment cannot be computed from the pinned inputs."""


def _month_key(d: date) -> tuple[int, int]:
    return (d.year, d.month)


def compute_assessment(
    store: Store,
    plan: RequirementPlan,
    price_source: Forecast,
    basis_kind: str,
    scenario_id: str | None,
    scenario_status: str | None,
    signal: BuySignal,
    pack: PlanningPack,
) -> CoverageAssessment:
    """Compute the assessment artefact for one plan + price source."""
    rows = store.series(
        plan.commodity, plan.market, "modal_price", end=price_source.as_of
    )
    if not rows:
        raise PlanningError(
            f"no modal_price observations for {plan.commodity} at "
            f"{plan.market} on or before {price_source.as_of} — "
            "options need a spot price"
        )
    spot = rows[-1]

    days_by_month: dict[tuple[int, int], list] = {}
    for day in price_source.days:
        days_by_month.setdefault(_month_key(day.forecast_date), []).append(day)

    q = pack.quintals_per_tonne
    stock_remaining = plan.opening_stock_tonnes
    months: list[MonthCoverage] = []
    for line in sorted(plan.lines, key=lambda ln: ln.month):
        days_in_month = calendar.monthrange(line.month.year, line.month.month)[1]
        covered_days = days_by_month.get(_month_key(line.month), [])
        covered_by_stock = round(min(stock_remaining, line.required_tonnes), 4)
        uncovered = round(line.required_tonnes - covered_by_stock, 4)
        stock_remaining = round(stock_remaining - covered_by_stock, 4)
        if not covered_days:
            state = "beyond_horizon"
            mean_p50 = mean_p90 = exposure = None
        else:
            mean_p50 = round(
                sum(d.p50 for d in covered_days) / len(covered_days), 4
            )
            mean_p90 = round(
                sum(d.p90 for d in covered_days) / len(covered_days), 4
            )
            state = (
                "valued" if len(covered_days) == days_in_month else "partial"
            )
            exposure = round(uncovered * q * mean_p50, 2)
        months.append(
            MonthCoverage(
                month=line.month,
                required_tonnes=line.required_tonnes,
                covered_by_stock_tonnes=covered_by_stock,
                uncovered_tonnes=uncovered,
                forecast_days_covered=len(covered_days),
                forecast_days_in_month=days_in_month,
                price_state=state,  # type: ignore[arg-type]
                mean_p50_inr=mean_p50,
                mean_p90_inr=mean_p90,
                exposure_inr=exposure,
            )
        )

    total_required = round(sum(ln.required_tonnes for ln in plan.lines), 4)
    total_plan_days = sum(m.forecast_days_in_month for m in months)
    daily_burn = total_required / total_plan_days if total_plan_days else 0.0
    coverage_days = (
        round(plan.opening_stock_tonnes / daily_burn, 4) if daily_burn > 0 else 0.0
    )
    stockout_month = next(
        (m.month for m in months if m.uncovered_tonnes > 0), None
    )
    priced = [m for m in months if m.price_state in ("valued", "partial")]
    unvalued = [m.month for m in months if m.price_state == "beyond_horizon"]
    total_uncovered = round(sum(m.uncovered_tonnes for m in priced), 4)
    total_exposure = round(
        sum(m.exposure_inr or 0.0 for m in priced), 2
    )

    notes: list[str] = []
    if basis_kind == "adopted_scenario":
        notes.append(
            f"priced on adopted scenario {scenario_id} — fork "
            f"artefact {price_source.forecast_id}; badged "
            "scenario-based and never blended with the official "
            "forecast view"
        )
    else:
        notes.append(
            f"priced on the official head forecast {price_source.forecast_id}"
        )
    notes.append(
        f"signal context: {signal.signal_id} reads {signal.value} "
        f"on the official forecast (as of {signal.as_of.isoformat()}) "
        "— pinned as context under the pack's signal rule; it "
        "never enters the ranking arithmetic"
    )
    for m in months:
        if m.price_state == "partial":
            notes.append(
                f"{m.month.strftime('%B %Y')} is priced on "
                f"{m.forecast_days_covered} of "
                f"{m.forecast_days_in_month} days — the forecast "
                "horizon ends inside the month"
            )
    if unvalued:
        notes.append(
            "beyond the forecast horizon, named and never valued: "
            + ", ".join(d.strftime("%B %Y") for d in unvalued)
        )

    options = _build_options(months, priced, spot.value, signal, pack, unvalued)

    figures = _build_figures(
        store, plan, price_source, basis_kind, scenario_id, signal,
        months, coverage_days, total_required, total_uncovered,
        total_exposure, options,
    )

    assessment = CoverageAssessment(
        assessment_id="COV-pending",
        plan_id=plan.plan_id,
        commodity=plan.commodity,
        market=plan.market,
        basis_kind=basis_kind,  # type: ignore[arg-type]
        forecast_id=price_source.forecast_id,
        scenario_id=scenario_id,
        scenario_status_at_assessment=scenario_status,
        as_of=price_source.as_of,
        spot_inr=spot.value,
        spot_date=spot.obs_date,
        signal_id=signal.signal_id,
        signal_value=signal.value,
        pack_version=pack.version,
        signal_pack_version=signal.pack_version,
        coverage_days=coverage_days,
        stockout_month=stockout_month,
        months=months,
        total_required_tonnes=total_required,
        total_uncovered_tonnes=total_uncovered,
        total_exposure_inr=total_exposure,
        unvalued_months=unvalued,
        options=options,
        figures=figures,
        notes=notes,
        scope_note=ASSESSMENT_SCOPE_NOTE,
    )
    return assessment.model_copy(
        update={"assessment_id": assessment_content_id(assessment)}
    )


def _build_options(
    months: list[MonthCoverage],
    priced: list[MonthCoverage],
    spot_inr: float,
    signal: BuySignal,
    pack: PlanningPack,
    unvalued: list[date],
) -> list[PurchaseOption]:
    q = pack.quintals_per_tonne
    open_months = [m for m in priced if m.uncovered_tonnes > 0]

    def line(month: MonthCoverage, basis: str, price: float) -> OptionLine:
        return OptionLine(
            month=month.month,
            tonnes=month.uncovered_tonnes,
            price_basis=basis,
            price_inr=price,
            cost_inr=round(month.uncovered_tonnes * q * price, 2),
        )

    def totals(schedule: list[OptionLine], p90_cost: float) -> tuple[float, float]:
        return round(sum(ln.cost_inr for ln in schedule), 2), round(p90_cost, 2)

    built: list[PurchaseOption] = []

    # cover_now — every uncovered tonne at spot; price certain.
    schedule = [line(m, "spot", spot_inr) for m in open_months]
    expected, adverse = totals(schedule, sum(ln.cost_inr for ln in schedule))
    built.append(
        PurchaseOption(
            name="cover_now", title="Cover everything now",
            schedule=schedule, cost_at_p50_inr=expected,
            cost_at_p90_inr=adverse, rank=0, notes=[],
        )
    )

    # cover_staged — first open month at spot, the rest phased.
    schedule = []
    p90_total = 0.0
    for i, m in enumerate(open_months):
        if i == 0:
            ln = line(m, "spot", spot_inr)
            p90_total += ln.cost_inr
        else:
            ln = line(m, "forecast_p50_mean", m.mean_p50_inr or 0.0)
            p90_total += round(m.uncovered_tonnes * q * (m.mean_p90_inr or 0.0), 2)
        schedule.append(ln)
    expected, adverse = totals(schedule, p90_total)
    built.append(
        PurchaseOption(
            name="cover_staged",
            title="Cover the first month now, phase the rest",
            schedule=schedule, cost_at_p50_inr=expected,
            cost_at_p90_inr=adverse, rank=0, notes=[],
        )
    )

    # cover_phased — every month at its forecast mean.
    schedule = [
        line(m, "forecast_p50_mean", m.mean_p50_inr or 0.0) for m in open_months
    ]
    p90_total = sum(
        round(m.uncovered_tonnes * q * (m.mean_p90_inr or 0.0), 2)
        for m in open_months
    )
    expected, adverse = totals(schedule, p90_total)
    built.append(
        PurchaseOption(
            name="cover_phased", title="Phase every month at its forecast price",
            schedule=schedule, cost_at_p50_inr=expected,
            cost_at_p90_inr=adverse, rank=0, notes=[],
        )
    )

    shared_notes: list[str] = []
    if not open_months:
        shared_notes.append(
            "no uncovered tonnes inside the forecast horizon — "
            "nothing to schedule"
        )
    if unvalued:
        shared_notes.append(
            "plan months beyond the forecast horizon ("
            + ", ".join(d.strftime("%B %Y") for d in unvalued)
            + ") are unpriced in every option"
        )
    for option in built:
        option.notes.extend(shared_notes)
        if option.name == "cover_now" and signal.value == "wait":
            option.notes.append(
                "caution: the pinned signal for this series is "
                "wait — this option buys against the signal"
            )

    ranked = sorted(
        built, key=lambda o: (o.cost_at_p50_inr, o.cost_at_p90_inr, o.name)
    )
    for rank, option in enumerate(ranked, start=1):
        option.rank = rank
    return ranked


def _build_figures(
    store: Store,
    plan: RequirementPlan,
    price_source: Forecast,
    basis_kind: str,
    scenario_id: str | None,
    signal: BuySignal,
    months: list[MonthCoverage],
    coverage_days: float,
    total_required: float,
    total_uncovered: float,
    total_exposure: float,
    options: list[PurchaseOption],
) -> list[PlanningFigure]:
    desk_walk = [plan_fact(plan)]
    if basis_kind == "adopted_scenario" and scenario_id is not None:
        # The fork is not a forecast artefact on record — it
        # lives inside the scenario run, never in the desk's
        # forecast record — so the price walk is the R7 scenario
        # walk (run -> base forecast -> the base series' stored
        # facts), and the run is the figures' artefact of record,
        # exactly as on a dashboard's scenario panel. Walking the
        # fork through forecast_lineage instead would name a
        # forecast the store does not hold as a forecast.
        run = store.get_scenario(scenario_id)
        if run is None:
            raise PlanningError(
                f"scenario {scenario_id} is not in the store — a "
                "scenario-based assessment cannot state its lineage"
            )
        price_walk = scenario_lineage(store, run)
        price_artefact_id = run.scenario_id
    else:
        price_walk = forecast_lineage(store, price_source)
        price_artefact_id = price_source.forecast_id
    mixed_walk = desk_walk + price_walk

    figures: list[PlanningFigure] = [
        PlanningFigure(
            key="total_required_tonnes",
            label=f"Total requirement — {plan.commodity} at {plan.market}",
            value=total_required, unit="tonnes", basis="desk",
            artefact_id=plan.plan_id, lineage=desk_walk,
        ),
        PlanningFigure(
            key="opening_stock_tonnes",
            label="Opening stock (desk-stated)",
            value=plan.opening_stock_tonnes, unit="tonnes", basis="desk",
            artefact_id=plan.plan_id, lineage=desk_walk,
        ),
        PlanningFigure(
            key="coverage_days",
            label="Coverage days at the plan's average daily burn",
            value=coverage_days, unit="days", basis="mixed",
            artefact_id=price_artefact_id, lineage=mixed_walk,
        ),
        PlanningFigure(
            key="total_uncovered_tonnes",
            label="Uncovered tonnes inside the horizon",
            value=total_uncovered, unit="tonnes", basis="mixed",
            artefact_id=price_artefact_id, lineage=mixed_walk,
        ),
        PlanningFigure(
            key="total_exposure_inr",
            label="Uncovered exposure at forecast P50",
            value=total_exposure, unit="INR", basis="mixed",
            artefact_id=price_artefact_id, lineage=mixed_walk,
        ),
        PlanningFigure(
            key="signal",
            label=f"Buy signal (context) — {plan.commodity} at {plan.market}",
            value=signal.value, unit="signal", basis="market",
            artefact_id=signal.signal_id,
            lineage=signal_lineage(store, signal),
        ),
    ]
    for m in months:
        if m.price_state in ("valued", "partial"):
            figures.append(
                PlanningFigure(
                    key=f"exposure_{m.month:%Y_%m}",
                    label=(
                        f"Uncovered exposure — {m.month.strftime('%B %Y')}"
                    ),
                    value=m.exposure_inr, unit="INR", basis="mixed",
                    artefact_id=price_artefact_id, lineage=mixed_walk,
                )
            )
    for option in options:
        figures.append(
            PlanningFigure(
                key=f"option_{option.name}_expected_cost",
                label=f"Option {option.name} — expected cost (rank {option.rank})",
                value=option.cost_at_p50_inr, unit="INR", basis="mixed",
                artefact_id=price_artefact_id, lineage=mixed_walk,
            )
        )
        figures.append(
            PlanningFigure(
                key=f"option_{option.name}_adverse_cost",
                label=f"Option {option.name} — adverse cost (P90)",
                value=option.cost_at_p90_inr, unit="INR", basis="mixed",
                artefact_id=price_artefact_id, lineage=mixed_walk,
            )
        )
    return figures
