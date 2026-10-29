"""The thin-data CLI — the same service the API serves.

    fmcg-agent-thin --db data/fmcg.db pack
    fmcg-agent-thin --db data/fmcg.db assess FCST-...
    fmcg-agent-thin --db data/fmcg.db assess-series groundnut rajkot
    fmcg-agent-thin --db data/fmcg.db assessments
    fmcg-agent-thin --db data/fmcg.db show THN-...
    fmcg-agent-thin --db data/fmcg.db verify THN-...
    fmcg-agent-thin --db data/fmcg.db claim FCST-... --horizon 30 --tier established

Every command prints the same artefact JSON the API returns and
exits non-zero on a refusal or a failed verification, with the
reason on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys

from fmcg_forecast.forecast.service import ForecastNotFoundError
from fmcg_forecast.store import build_store
from fmcg_forecast.thin.engine import ThinDataError
from fmcg_forecast.thin.pack import load_thin_data_pack
from fmcg_forecast.thin.service import ThinDataNotFoundError, ThinDataService


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-thin")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pack", help="print the thin-data pack")
    p = sub.add_parser("assess", help="assess one forecast")
    p.add_argument("forecast_id")
    p = sub.add_parser("assess-series", help="assess a series' head forecast")
    p.add_argument("commodity")
    p.add_argument("market")
    p = sub.add_parser("assessments", help="list assessments")
    p.add_argument("--commodity", default=None)
    p.add_argument("--market", default=None)
    p = sub.add_parser("show", help="show one assessment with its problems")
    p.add_argument("assessment_id")
    p = sub.add_parser("verify", help="re-perform one assessment, or all with --all")
    p.add_argument("assessment_id", nargs="?")
    p.add_argument("--all", action="store_true")
    p = sub.add_parser("claim", help="grade a tier claim for a forecast horizon")
    p.add_argument("forecast_id")
    p.add_argument("--horizon", type=int, required=True)
    p.add_argument("--tier", required=True)

    args = parser.parse_args(argv)
    store = build_store(args.db)
    service = ThinDataService(store)
    try:
        if args.command == "pack":
            _print(load_thin_data_pack().model_dump(mode="json"))
        elif args.command == "assess":
            assessment = service.assess_forecast(args.forecast_id)
            _print(service.assessment_view(assessment.assessment_id))
        elif args.command == "assess-series":
            assessment = service.assess_series(args.commodity, args.market)
            _print(service.assessment_view(assessment.assessment_id))
        elif args.command == "assessments":
            _print(
                [
                    a.model_dump(mode="json")
                    for a in service.list_assessments(args.commodity, args.market)
                ]
            )
        elif args.command == "show":
            _print(service.assessment_view(args.assessment_id))
        elif args.command == "verify":
            if args.all:
                problems = service.verify_all()
                _print({"scope": "all", "problems": problems})
            else:
                problems = service.verify_stored(args.assessment_id)
                _print({"assessment_id": args.assessment_id, "problems": problems})
            if problems:
                return 1
        elif args.command == "claim":
            problems = service.verify_claim(
                args.forecast_id, args.horizon, args.tier
            )
            _print(
                {
                    "forecast_id": args.forecast_id,
                    "horizon_days": args.horizon,
                    "claimed_tier": args.tier,
                    "problems": problems,
                }
            )
            if problems:
                return 1
    except (
        ForecastNotFoundError,
        ThinDataNotFoundError,
        ThinDataError,
        ValueError,
    ) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
