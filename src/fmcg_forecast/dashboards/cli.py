"""The dashboard CLI — the same service the API serves.

    fmcg-agent-dashboards --db data/fmcg.db ask \
        --by a.sharma --text "wheat forecast at delhi and soybean sentiment"
    fmcg-agent-dashboards --db data/fmcg.db save DSPEC-... \
        --name "morning wheat" --by a.sharma
    fmcg-agent-dashboards --db data/fmcg.db views
    fmcg-agent-dashboards --db data/fmcg.db assemble DSPEC-...
    fmcg-agent-dashboards --db data/fmcg.db show DASH-...
    fmcg-agent-dashboards --db data/fmcg.db appendix DASH-...
    fmcg-agent-dashboards --db data/fmcg.db verify DASH-...
    fmcg-agent-dashboards --db data/fmcg.db board --on 2026-02-15
    fmcg-agent-dashboards --db data/fmcg.db board-html --on 2026-02-15

Every command prints the same artefact JSON the API returns
(board-html prints the page) and exits non-zero on a refusal,
with the refusal on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from fmcg_forecast.dashboards.service import DashboardError, DashboardService
from fmcg_forecast.events.service import EventService
from fmcg_forecast.modelport import OfflineModel
from fmcg_forecast.sentiment.service import SentimentService
from fmcg_forecast.store import build_store


def _service(db: str) -> DashboardService:
    store = build_store(db)
    model = OfflineModel()
    sentiment = SentimentService(store, model)
    events = EventService(store)
    return DashboardService(store, model, events, sentiment)


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-dashboards")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ask", help="ask a plain-language prompt -> a spec")
    p.add_argument("--text", required=True)
    p.add_argument("--by", required=True, help="the named asker")
    p.add_argument("--on", default=None, help="ask date (ISO); default today")

    p = sub.add_parser("specs", help="list stored specs")

    p = sub.add_parser("save", help="save a spec as a named view")
    p.add_argument("spec_id")
    p.add_argument("--name", required=True)
    p.add_argument("--by", required=True)
    p.add_argument("--on", default=None)

    p = sub.add_parser("views", help="list saved views")
    p.add_argument("--name", default=None)

    p = sub.add_parser("assemble", help="assemble (or re-run) a spec")
    p.add_argument("spec_id")
    p.add_argument("--on", default=None, help="assembly date (ISO); default today")

    p = sub.add_parser("show", help="one stored assembly")
    p.add_argument("assembly_id")

    p = sub.add_parser("appendix", help="one assembly's provenance appendix")
    p.add_argument("assembly_id")

    p = sub.add_parser("verify", help="re-perform a stored assembly")
    p.add_argument("assembly_id")

    p = sub.add_parser("board", help="the morning desk board, as data")
    p.add_argument("--on", default=None, help="board date (ISO); default the last history day")

    p = sub.add_parser("board-html", help="the morning desk board, as a page")
    p.add_argument("--on", default=None)

    args = parser.parse_args(argv)
    service = _service(args.db)
    try:
        if args.command == "ask":
            spec = service.ask(
                args.text,
                args.by,
                date.fromisoformat(args.on) if args.on else date.today(),
            )
            _print(spec.model_dump(mode="json"))
        elif args.command == "specs":
            _print(
                {"specs": [s.model_dump(mode="json") for s in service.list_specs()]}
            )
        elif args.command == "save":
            view = service.save_view(
                args.spec_id,
                args.name,
                args.by,
                date.fromisoformat(args.on) if args.on else date.today(),
            )
            _print(view.model_dump(mode="json"))
        elif args.command == "views":
            _print(
                {
                    "views": [
                        v.model_dump(mode="json")
                        for v in service.list_views(args.name)
                    ]
                }
            )
        elif args.command == "assemble":
            assembly = service.assemble(
                args.spec_id,
                date.fromisoformat(args.on) if args.on else date.today(),
            )
            _print(assembly.model_dump(mode="json"))
        elif args.command == "show":
            _print(service.get_assembly(args.assembly_id).model_dump(mode="json"))
        elif args.command == "appendix":
            _print(service.appendix(args.assembly_id))
        elif args.command == "verify":
            problems = service.verify_stored(args.assembly_id)
            _print({"assembly_id": args.assembly_id, "problems": problems})
            return 1 if problems else 0
        elif args.command == "board":
            view = service.board_view(
                date.fromisoformat(args.on) if args.on else None
            )
            _print({"board": view["board"], "sections": view["sections"]})
        elif args.command == "board-html":
            view = service.board_view(
                date.fromisoformat(args.on) if args.on else None
            )
            print(view["html"])
    except DashboardError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
