"""The console CLI — the same service the API serves.

    fmcg-agent-console --db data/fmcg.db pack
    fmcg-agent-console --db data/fmcg.db preflight coffee bengaluru
    fmcg-agent-console --db data/fmcg.db queue
    fmcg-agent-console --db data/fmcg.db reject FCST-... \\
        --by a.sharma --role desk_head --reason stale_inputs
    fmcg-agent-console --db data/fmcg.db triage
    fmcg-agent-console --db data/fmcg.db confirm EVT-... \\
        --actor a.sharma --role analyst
    fmcg-agent-console --db data/fmcg.db view
    fmcg-agent-console --db data/fmcg.db verify

Every command prints the same artefact JSON the API returns and
exits non-zero on a refusal or a failed verification, with the
reason on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from fmcg_forecast.console.engine import ConsoleError
from fmcg_forecast.console.pack import load_console_pack
from fmcg_forecast.console.service import ConsoleService
from fmcg_forecast.events.service import EventService
from fmcg_forecast.store import build_store


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-console")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pack", help="print the console pack")

    p = sub.add_parser("preflight", help="strike a series pre-flight")
    p.add_argument("commodity")
    p.add_argument("market")
    p.add_argument("--as-of", type=date.fromisoformat, default=None)
    sub.add_parser("preflights", help="list struck pre-flight reports")
    p = sub.add_parser("show-preflight", help="show one report with problems")
    p.add_argument("report_id")
    p = sub.add_parser("verify-preflight", help="re-perform one report")
    p.add_argument("report_id")

    sub.add_parser("queue", help="the forecast review queue")
    p = sub.add_parser("reject", help="reject a draft forecast")
    p.add_argument("forecast_id")
    p.add_argument("--by", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--note", default="")
    p.add_argument("--on", type=date.fromisoformat, default=None)

    sub.add_parser("triage", help="the event triage queue")
    p = sub.add_parser("show-event", help="one event with verdict + triage")
    p.add_argument("event_id")
    for name, helptext in (
        ("confirm", "confirm an event for the official view"),
        ("retire", "retire an event"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("event_id")
        p.add_argument("--actor", required=True)
        p.add_argument("--role", required=True)
        p.add_argument("--note", default="")
        p.add_argument("--on", type=date.fromisoformat, default=None)
    p = sub.add_parser("amend", help="amend an event's declaration")
    p.add_argument("event_id")
    p.add_argument("--actor", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--note", default="")
    p.add_argument("--on", type=date.fromisoformat, default=None)
    p.add_argument(
        "--replacement-json",
        required=True,
        help="the replacement declaration, as a JSON object with "
        "the registry's declaration fields",
    )

    p = sub.add_parser("view", help="the composed console view")
    p.add_argument("--date", type=date.fromisoformat, default=None)
    sub.add_parser("verify", help="verify every console artefact")

    args = parser.parse_args(argv)
    store = build_store(args.db)
    service = ConsoleService(store, EventService(store))
    today = date.today()
    try:
        if args.command == "pack":
            _print(load_console_pack().model_dump(mode="json"))
        elif args.command == "preflight":
            report = service.strike_preflight(
                args.commodity, args.market, args.as_of
            )
            _print(service.preflight_view(report.report_id))
        elif args.command == "preflights":
            _print(
                [r.model_dump(mode="json") for r in service.list_preflights()]
            )
        elif args.command == "show-preflight":
            _print(service.preflight_view(args.report_id))
        elif args.command == "verify-preflight":
            report = service.get_preflight(args.report_id)
            from fmcg_forecast.console.verify import verify_preflight

            problems = verify_preflight(store, report)
            _print({"report_id": args.report_id, "problems": problems})
            if problems:
                return 1
        elif args.command == "queue":
            _print(service.review_queue())
        elif args.command == "reject":
            act = service.reject_forecast(
                args.forecast_id,
                args.by,
                args.role,
                args.on or today,
                args.reason,
                args.note,
            )
            _print(act.model_dump(mode="json"))
        elif args.command == "triage":
            _print(service.triage_queue())
        elif args.command == "show-event":
            _print(service.triage_view(args.event_id))
        elif args.command == "confirm":
            act = service.confirm_event(
                args.event_id, args.actor, args.role,
                args.on or today, args.note,
            )
            _print(act.model_dump(mode="json"))
        elif args.command == "retire":
            act = service.retire_event(
                args.event_id, args.actor, args.role,
                args.on or today, args.note,
            )
            _print(act.model_dump(mode="json"))
        elif args.command == "amend":
            replacement = json.loads(args.replacement_json)
            for field in ("window_start", "window_end", "declared_on"):
                if replacement.get(field):
                    replacement[field] = date.fromisoformat(
                        replacement[field]
                    )
            act = service.amend_event(
                args.event_id, args.actor, args.role,
                args.on or today, replacement, args.note,
            )
            _print(act.model_dump(mode="json"))
        elif args.command == "view":
            _print(service.console_view(args.date))
        elif args.command == "verify":
            problems = service.verify_stored()
            _print({"scope": "all", "problems": problems})
            if problems:
                return 1
    except (ConsoleError, ValueError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
