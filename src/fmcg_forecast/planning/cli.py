"""The planning CLI — the same service the API serves.

    fmcg-agent-planning --db data/fmcg.db enter soybean indore \
        --by r.menon --stock 120 \
        --line 2026-01:300 --line 2026-02:300 --line 2026-03:280
    fmcg-agent-planning --db data/fmcg.db plans
    fmcg-agent-planning --db data/fmcg.db show-plan PLAN-...
    fmcg-agent-planning --db data/fmcg.db assess PLAN-...
    fmcg-agent-planning --db data/fmcg.db assess PLAN-... --basis adopted_scenario
    fmcg-agent-planning --db data/fmcg.db show COV-...
    fmcg-agent-planning --db data/fmcg.db verify COV-...

Every command prints the same artefact JSON the API returns and
exits non-zero on a refusal, with the refusal on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from fmcg_forecast.planning.models import PlanLine
from fmcg_forecast.planning.pack import load_planning_pack
from fmcg_forecast.planning.service import (
    PlanningError,
    PlanningNotFoundError,
    PlanningService,
    PlanningStateError,
    PlanningValidationError,
)
from fmcg_forecast.store import build_store


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _parse_line(text: str) -> PlanLine:
    month_text, _, tonnes_text = text.partition(":")
    year, _, month = month_text.partition("-")
    return PlanLine(
        month=date(int(year), int(month), 1),
        required_tonnes=float(tonnes_text),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-planning")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pack", help="print the planning pack")
    p = sub.add_parser("enter", help="enter a requirement plan")
    p.add_argument("commodity")
    p.add_argument("market")
    p.add_argument("--by", required=True, help="the named enterer")
    p.add_argument("--on", default=None, help="entry date (ISO); default today")
    p.add_argument("--stock", type=float, default=0.0,
                   help="opening stock in tonnes (desk-stated)")
    p.add_argument("--line", action="append", required=True,
                   help="YYYY-MM:tonnes, one per plan month")
    p.add_argument("--note", default="")
    p = sub.add_parser("plans", help="list stored plans")
    p.add_argument("--commodity", default=None)
    p.add_argument("--market", default=None)
    p = sub.add_parser("show-plan", help="show one plan")
    p.add_argument("plan_id")
    p = sub.add_parser("assess", help="assess a plan's coverage + exposure")
    p.add_argument("plan_id")
    p.add_argument("--basis", default="official_forecast",
                   choices=["official_forecast", "adopted_scenario"])
    p = sub.add_parser("show", help="show one assessment")
    p.add_argument("assessment_id")
    p = sub.add_parser("verify", help="re-perform one assessment")
    p.add_argument("assessment_id")

    args = parser.parse_args(argv)
    store = build_store(args.db)
    service = PlanningService(store)
    try:
        if args.command == "pack":
            _print(load_planning_pack().model_dump(mode="json"))
        elif args.command == "enter":
            plan = service.enter_plan(
                commodity=args.commodity,
                market=args.market,
                entered_by=args.by,
                entered_on=(
                    date.fromisoformat(args.on) if args.on else date.today()
                ),
                opening_stock_tonnes=args.stock,
                lines=[_parse_line(text) for text in args.line],
                note=args.note,
            )
            _print(service.plan_view(plan.plan_id))
        elif args.command == "plans":
            _print(
                [
                    p.model_dump(mode="json")
                    for p in service.list_plans(args.commodity, args.market)
                ]
            )
        elif args.command == "show-plan":
            _print(service.plan_view(args.plan_id))
        elif args.command == "assess":
            assessment = service.assess(args.plan_id, basis=args.basis)
            _print(assessment.model_dump(mode="json"))
        elif args.command == "show":
            _print(service.assessment_view(args.assessment_id))
        elif args.command == "verify":
            problems = service.verify_assessment_stored(args.assessment_id)
            _print({"assessment_id": args.assessment_id, "problems": problems})
            if problems:
                return 1
    except (
        PlanningError,
        PlanningNotFoundError,
        PlanningStateError,
        PlanningValidationError,
        ValueError,
    ) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
