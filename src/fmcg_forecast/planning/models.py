"""The planning artefacts: the desk's plan, and its assessment.

A requirement plan is the desk's own statement — who entered it,
when, what stock the desk holds, and the tonnes it needs month
by month. Its ``origin`` is ``desk_entered`` on the artefact and
on every surface; it is never market data and never borrows
market provenance.

A coverage assessment is computed from one plan and one pinned
price source — the official head forecast, or an adopted
scenario's fork, badged as such — and is content-addressed over
both, the pinned signal, the pack version and every figure it
states. Each figure carries a ``basis`` — ``desk`` (rests only
on the plan), ``market`` (rests only on market artefacts) or
``mixed`` (plan tonnes valued at market prices) — and the
lineage walk that proves it; the verifier checks the separation
as strictly as the arithmetic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from fmcg_forecast.dashboards.models import LineageFact

PLAN_ORIGIN = "desk_entered"

ASSESSMENT_SCOPE_NOTE = (
    "planning arithmetic only — no purchase is placed or "
    "instructed; procurement execution is out of scope by design"
)


class PlanLine(BaseModel):
    """One month of the desk's stated requirement."""

    month: date = Field(description="The month, as its first day")
    required_tonnes: float


class RequirementPlan(BaseModel):
    plan_id: str = Field(description="Content address: PLAN-<sha256[:16]>")
    commodity: str
    market: str
    entered_by: str = Field(description="The named desk user who entered it")
    entered_on: date
    origin: Literal["desk_entered"] = "desk_entered"
    opening_stock_tonnes: float = Field(
        description="Stock the desk states it holds, in tonnes — "
        "a desk statement, not a market observation"
    )
    lines: list[PlanLine]
    note: str = ""


class MonthCoverage(BaseModel):
    """One plan month, priced and allocated."""

    month: date
    required_tonnes: float
    covered_by_stock_tonnes: float
    uncovered_tonnes: float
    forecast_days_covered: int = Field(
        description="Days of this month the pinned forecast covers"
    )
    forecast_days_in_month: int
    price_state: Literal["valued", "partial", "beyond_horizon"]
    mean_p50_inr: float | None = Field(
        description="Mean daily P50 over covered days, 4dp; None "
        "beyond the horizon"
    )
    mean_p90_inr: float | None
    exposure_inr: float | None = Field(
        description="Uncovered tonnes x quintals per tonne x "
        "mean P50, 2dp; None beyond the horizon"
    )


class OptionLine(BaseModel):
    """One scheduled tranche of a purchase option."""

    month: date
    tonnes: float
    price_basis: str = Field(
        description="spot / forecast_p50_mean / forecast_p90_mean "
        "— which stated price this tranche is costed at in the "
        "option's schedule (the P50 basis)"
    )
    price_inr: float
    cost_inr: float


class PurchaseOption(BaseModel):
    name: str
    title: str
    schedule: list[OptionLine] = Field(
        description="The tranches, costed on the P50 basis "
        "(spot tranches at spot)"
    )
    cost_at_p50_inr: float = Field(description="Expected cost, 2dp")
    cost_at_p90_inr: float = Field(
        description="Adverse cost: forecast-priced tranches at "
        "the P90 means, spot tranches unchanged, 2dp"
    )
    rank: int
    notes: list[str]


class PlanningFigure(BaseModel):
    """One figure an assessment states, with its basis and walk."""

    key: str
    label: str
    value: float | str | None
    unit: str
    basis: Literal["desk", "market", "mixed"] = Field(
        description="desk: rests only on the plan. market: rests "
        "only on market artefacts. mixed: plan tonnes at market "
        "prices — its walk carries exactly one desk_entered fact "
        "alongside the market walk"
    )
    artefact_id: str
    lineage: list[LineageFact]


class CoverageAssessment(BaseModel):
    assessment_id: str = Field(
        description="Content address: COV-<sha256[:16]>"
    )
    plan_id: str
    commodity: str
    market: str
    basis_kind: Literal["official_forecast", "adopted_scenario"]
    forecast_id: str = Field(
        description="The forecast artefact whose prices were used "
        "— the head forecast, or the adopted run's fork"
    )
    scenario_id: str | None = Field(
        description="The adopted scenario run, when scenario-based"
    )
    scenario_status_at_assessment: str | None
    as_of: date = Field(description="The price source's as_of")
    spot_inr: float
    spot_date: date
    signal_id: str = Field(
        description="The series' buy signal pinned as context — "
        "computed on the official head forecast"
    )
    signal_value: str
    pack_version: str
    signal_pack_version: str
    coverage_days: float
    stockout_month: date | None
    months: list[MonthCoverage]
    total_required_tonnes: float
    total_uncovered_tonnes: float = Field(
        description="Uncovered tonnes over valued and partial "
        "months (beyond-horizon months carry their own rows)"
    )
    total_exposure_inr: float = Field(
        description="Sum of valued months' exposure, 2dp"
    )
    unvalued_months: list[date] = Field(
        description="Plan months beyond the forecast horizon — "
        "named, never valued"
    )
    options: list[PurchaseOption]
    figures: list[PlanningFigure]
    notes: list[str]
    scope_note: str


def plan_content_id(plan: RequirementPlan) -> str:
    payload = plan.model_dump(mode="json", exclude={"plan_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "PLAN-" + hashlib.sha256(canonical.encode()).hexdigest()[:16]


def assessment_content_id(assessment: CoverageAssessment) -> str:
    payload = assessment.model_dump(mode="json", exclude={"assessment_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "COV-" + hashlib.sha256(canonical.encode()).hexdigest()[:16]
