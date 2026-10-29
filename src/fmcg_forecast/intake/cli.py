"""The assisted-intake CLI — the same service the API serves.

    fmcg-agent-intake --db data/fmcg.db enter --commodity coffee \
        --market bengaluru --date 2026-01-05 --driver modal_price \
        --value 34100 --entered-by d.assist --entered-by-role desk_assistant \
        --at 2026-01-05T10:30:00 --source-note "phoned in by the Bengaluru market contact"
    fmcg-agent-intake --db data/fmcg.db entries --state pending
    fmcg-agent-intake --db data/fmcg.db show ENT-...
    fmcg-agent-intake --db data/fmcg.db confirm ENT-... --checker r.menon \
        --checker-role desk_head --at 2026-01-05T11:00:00
    fmcg-agent-intake --db data/fmcg.db reject ENT-... --checker r.menon \
        --checker-role desk_head --at 2026-01-05T11:00:00 --note "figure could not be corroborated"
    fmcg-agent-intake --db data/fmcg.db verify ENT-...

Every command prints the same artefact JSON the API returns and
exits non-zero on a refusal, with the refusal on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime

from fmcg_forecast.intake.service import (
    IntakeNotFoundError,
    IntakeService,
    IntakeStateError,
    IntakeValidationError,
)
from fmcg_forecast.store import build_store


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-intake")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("enter", help="record a phoned-in figure (pending)")
    p.add_argument("--commodity", required=True)
    p.add_argument("--market", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--driver", required=True)
    p.add_argument("--value", type=float, required=True)
    p.add_argument("--entered-by", required=True)
    p.add_argument("--entered-by-role", required=True)
    p.add_argument("--at", required=True)
    p.add_argument("--source-note", required=True)
    p = sub.add_parser("entries", help="list entries")
    p.add_argument("--commodity", default=None)
    p.add_argument("--market", default=None)
    p.add_argument("--state", default=None)
    p = sub.add_parser("show", help="show one entry with its chain")
    p.add_argument("entry_id")
    p = sub.add_parser("confirm", help="confirm an entry (second person)")
    p.add_argument("entry_id")
    p.add_argument("--checker", required=True)
    p.add_argument("--checker-role", required=True)
    p.add_argument("--at", required=True)
    p.add_argument("--note", default="")
    p = sub.add_parser("reject", help="reject an entry (second person)")
    p.add_argument("entry_id")
    p.add_argument("--checker", required=True)
    p.add_argument("--checker-role", required=True)
    p.add_argument("--at", required=True)
    p.add_argument("--note", default="")
    p = sub.add_parser("verify", help="re-perform one entry's chain, or all with --all")
    p.add_argument("entry_id", nargs="?")
    p.add_argument("--all", action="store_true")

    args = parser.parse_args(argv)
    store = build_store(args.db)
    service = IntakeService(store)
    try:
        if args.command == "enter":
            entry = service.enter(
                commodity=args.commodity,
                market=args.market,
                obs_date=date.fromisoformat(args.date),
                driver=args.driver,
                value=args.value,
                entered_by=args.entered_by,
                entered_by_role=args.entered_by_role,
                entered_at=datetime.fromisoformat(args.at),
                source_note=args.source_note,
            )
            _print(service.entry_view(entry.entry_id))
        elif args.command == "entries":
            _print(
                [
                    service.entry_view(e.entry_id)
                    for e in service.list_entries(
                        args.commodity, args.market, args.state
                    )
                ]
            )
        elif args.command == "show":
            _print(service.entry_view(args.entry_id))
        elif args.command == "confirm":
            act = service.confirm(
                args.entry_id,
                checker=args.checker,
                checker_role=args.checker_role,
                acted_at=datetime.fromisoformat(args.at),
                note=args.note,
            )
            _print(act.model_dump(mode="json"))
        elif args.command == "reject":
            act = service.reject(
                args.entry_id,
                checker=args.checker,
                checker_role=args.checker_role,
                acted_at=datetime.fromisoformat(args.at),
                note=args.note,
            )
            _print(act.model_dump(mode="json"))
        elif args.command == "verify":
            if args.all:
                problems = service.verify_all()
                _print({"scope": "all", "problems": problems})
            else:
                problems = service.verify_stored(args.entry_id)
                _print({"entry_id": args.entry_id, "problems": problems})
            if problems:
                return 1
    except (
        IntakeNotFoundError,
        IntakeStateError,
        IntakeValidationError,
        ValueError,
    ) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
