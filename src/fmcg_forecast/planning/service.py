"""The planning workflow every surface shares.

Entering a plan is a named desk act: a named enterer (placeholder
names refused, as at every gate in this repo), a catalogue
series, one line per calendar month, non-negative tonnes with
at least one real requirement. Entry is idempotent — the plan
is content-addressed, so re-entering the same statement lands on
the stored artefact.

Assessing a plan pins its price source: the official head
forecast, or — only when the desk has actually adopted a
scenario for the series — the adopted run's fork, badged
scenario-based. The series' buy signal is computed (or found)
on the official forecast and pinned as context under the pack's
signal rule.
"""

from __future__ import annotations

from datetime import date

from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.dashboards.assemble import head_forecast
from fmcg_forecast.planning.engine import PlanningError, compute_assessment
from fmcg_forecast.planning.models import (
    CoverageAssessment,
    PlanLine,
    RequirementPlan,
    plan_content_id,
)
from fmcg_forecast.planning.pack import PlanningPack, load_planning_pack
from fmcg_forecast.planning.verify import verify_assessment, verify_plan
from fmcg_forecast.signals.service import SignalService
from fmcg_forecast.store import Store

_PLACEHOLDER_NAMES = {"", "tbd", "test", "user", "admin", "someone", "n/a", "na"}


def _require_named(value: str, field: str) -> str:
    cleaned = (value or "").strip()
    if cleaned.lower() in _PLACEHOLDER_NAMES or len(cleaned) < 2:
        raise PlanningValidationError(
            f"{field} must be a named human — a plan entered by "
            f"{value!r} cannot be attributed, so the entry is refused"
        )
    return cleaned


class PlanningValidationError(ValueError):
    """A plan entry breaks the stated entry rules."""


class PlanningNotFoundError(LookupError):
    """A named plan, assessment or price source does not exist."""


class PlanningStateError(RuntimeError):
    """The desk's state does not support the requested assessment."""


class PlanningService:
    def __init__(
        self,
        store: Store,
        signals: SignalService | None = None,
        pack: PlanningPack | None = None,
    ):
        self.store = store
        self.signals = signals or SignalService(store)
        self.pack = pack or load_planning_pack()

    # -- plan entry ----------------------------------------------------

    def enter_plan(
        self,
        commodity: str,
        market: str,
        entered_by: str,
        entered_on: date,
        opening_stock_tonnes: float,
        lines: list[PlanLine],
        note: str = "",
    ) -> RequirementPlan:
        spec = BY_NAME.get(commodity)
        if spec is None:
            raise PlanningValidationError(
                f"unknown commodity {commodity!r} — the catalogue "
                "names seven"
            )
        if market not in spec.markets:
            raise PlanningValidationError(
                f"{market!r} is not a {commodity} market in the "
                f"catalogue (one of {', '.join(spec.markets)})"
            )
        entered_by = _require_named(entered_by, "entered_by")
        if opening_stock_tonnes < 0:
            raise PlanningValidationError(
                "opening stock cannot be negative — the desk states "
                "what it holds"
            )
        if not lines:
            raise PlanningValidationError(
                "a plan needs at least one monthly requirement line"
            )
        seen: set[date] = set()
        for line in lines:
            if line.month.day != 1:
                raise PlanningValidationError(
                    f"plan month {line.month} is not a month's first "
                    "day — requirements are stated by calendar month"
                )
            if line.month in seen:
                raise PlanningValidationError(
                    f"plan month {line.month} appears twice — one "
                    "line per month"
                )
            seen.add(line.month)
            if line.required_tonnes < 0:
                raise PlanningValidationError(
                    f"plan month {line.month} requires negative tonnes"
                )
        if not any(line.required_tonnes > 0 for line in lines):
            raise PlanningValidationError(
                "a plan whose every line is zero tonnes states no "
                "requirement — there is nothing to plan against"
            )
        plan = RequirementPlan(
            plan_id="PLAN-pending",
            commodity=commodity,
            market=market,
            entered_by=entered_by,
            entered_on=entered_on,
            opening_stock_tonnes=opening_stock_tonnes,
            lines=sorted(lines, key=lambda ln: ln.month),
            note=note,
        )
        plan = plan.model_copy(update={"plan_id": plan_content_id(plan)})
        if self.store.get_requirement_plan(plan.plan_id) is None:
            self.store.insert_requirement_plan(plan)
        return plan

    def get_plan(self, plan_id: str) -> RequirementPlan:
        plan = self.store.get_requirement_plan(plan_id)
        if plan is None:
            raise PlanningNotFoundError(f"no requirement plan {plan_id}")
        return plan

    def list_plans(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[RequirementPlan]:
        return self.store.list_requirement_plans(commodity, market)

    def plan_view(self, plan_id: str) -> dict:
        """One plan, labelled desk-entered on the face of the read."""
        plan = self.get_plan(plan_id)
        view = plan.model_dump(mode="json")
        view["origin_label"] = (
            "desk-entered — the desk's own statement of need, "
            "not market data"
        )
        view["problems"] = verify_plan(plan)
        return view

    # -- assessment ------------------------------------------------------

    def assess(
        self, plan_id: str, basis: str = "official_forecast"
    ) -> CoverageAssessment:
        plan = self.get_plan(plan_id)
        scenario_id: str | None = None
        scenario_status: str | None = None
        if basis == "official_forecast":
            price_source = head_forecast(
                self.store, plan.commodity, plan.market
            )
            if price_source is None:
                raise PlanningNotFoundError(
                    f"no forecast exists for {plan.commodity} at "
                    f"{plan.market} — run a forecast before assessing"
                )
            signal = self.signals.compute_for_forecast(price_source)
        elif basis == "adopted_scenario":
            run = next(
                (
                    s
                    for s in self.store.list_scenarios(
                        plan.commodity, plan.market
                    )
                    if s.status == "adopted"
                ),
                None,
            )
            if run is None:
                raise PlanningStateError(
                    f"no scenario has been adopted for "
                    f"{plan.commodity} at {plan.market} — a "
                    "scenario-based assessment prices on an adopted "
                    "fork only, never on a draft"
                )
            base = self.store.get_forecast(run.base_forecast_id)
            if base is None:
                raise PlanningNotFoundError(
                    f"the adopted scenario's base forecast "
                    f"{run.base_forecast_id} is not in the store"
                )
            signal = self.signals.compute_for_forecast(base)
            price_source = run.fork
            scenario_id = run.scenario_id
            scenario_status = run.status
        else:
            raise PlanningValidationError(
                f"unknown assessment basis {basis!r} — one of "
                "official_forecast / adopted_scenario"
            )
        assessment = compute_assessment(
            self.store,
            plan,
            price_source,
            basis,
            scenario_id,
            scenario_status,
            signal,
            self.pack,
        )
        if self.store.get_coverage_assessment(assessment.assessment_id) is None:
            self.store.insert_coverage_assessment(assessment)
        return assessment

    def get_assessment(self, assessment_id: str) -> CoverageAssessment:
        assessment = self.store.get_coverage_assessment(assessment_id)
        if assessment is None:
            raise PlanningNotFoundError(
                f"no coverage assessment {assessment_id}"
            )
        return assessment

    def list_assessments(
        self, plan_id: str | None = None
    ) -> list[CoverageAssessment]:
        return self.store.list_coverage_assessments(plan_id)

    def verify_plan_stored(self, plan_id: str) -> list[str]:
        return verify_plan(self.get_plan(plan_id))

    def verify_assessment_stored(self, assessment_id: str) -> list[str]:
        return verify_assessment(self.store, self.get_assessment(assessment_id))

    def assessment_view(self, assessment_id: str) -> dict:
        assessment = self.get_assessment(assessment_id)
        view = assessment.model_dump(mode="json")
        view["problems"] = verify_assessment(self.store, assessment)
        return view


__all__ = [
    "PlanningError",
    "PlanningNotFoundError",
    "PlanningService",
    "PlanningStateError",
    "PlanningValidationError",
]
