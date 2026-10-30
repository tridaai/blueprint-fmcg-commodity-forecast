"""The analytics CLI — the same service the API serves.

    fmcg-agent-analytics --db data/fmcg.db pack
    fmcg-agent-analytics --db data/fmcg.db build
    fmcg-agent-analytics --db data/fmcg.db reports
    fmcg-agent-analytics --db data/fmcg.db show OPS-...
    fmcg-agent-analytics --db data/fmcg.db verify OPS-...
    fmcg-agent-analytics --db data/fmcg.db verify --all

Every command prints the same artefact JSON the API returns and
exits non-zero on a refusal or a failed verification, with the
reason on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys

from fmcg_forecast.analytics.engine import AnalyticsError
from fmcg_forecast.analytics.pack import load_analytics_pack
from fmcg_forecast.analytics.service import (
    AnalyticsNotFoundError,
    AnalyticsService,
)
from fmcg_forecast.store import build_store


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-analytics")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pack", help="print the analytics pack")
    sub.add_parser("build", help="compute the ops report and store it")
    sub.add_parser("reports", help="list stored ops reports")
    p = sub.add_parser("show", help="show one report with its problems")
    p.add_argument("report_id")
    p = sub.add_parser("verify", help="re-perform one report, or all with --all")
    p.add_argument("report_id", nargs="?")
    p.add_argument("--all", action="store_true")

    args = parser.parse_args(argv)
    store = build_store(args.db)
    service = AnalyticsService(store)
    try:
        if args.command == "pack":
            _print(load_analytics_pack().model_dump(mode="json"))
        elif args.command == "build":
            report = service.build_report()
            _print(service.report_view(report.report_id))
        elif args.command == "reports":
            _print(
                [r.model_dump(mode="json") for r in service.list_reports()]
            )
        elif args.command == "show":
            _print(service.report_view(args.report_id))
        elif args.command == "verify":
            if args.all:
                problems = service.verify_all()
                _print({"scope": "all", "problems": problems})
            else:
                problems = service.verify_stored(args.report_id)
                _print({"report_id": args.report_id, "problems": problems})
            if problems:
                return 1
    except (AnalyticsNotFoundError, AnalyticsError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
