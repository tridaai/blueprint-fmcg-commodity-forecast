"""The access CLI — the same service the API serves.

    fmcg-agent-access --db data/fmcg.db pack
    fmcg-agent-access --db data/fmcg.db grant d.kaur --role desk_head --by d.kaur --on 2026-01-02
    fmcg-agent-access --db data/fmcg.db grant a.sharma --role trader --markets indore,kanpur --by d.kaur --on 2026-01-02
    fmcg-agent-access --db data/fmcg.db repeal a.sharma --by d.kaur --on 2026-02-01
    fmcg-agent-access --db data/fmcg.db grants
    fmcg-agent-access --db data/fmcg.db standing a.sharma
    fmcg-agent-access --db data/fmcg.db entries
    fmcg-agent-access --db data/fmcg.db strike-log --on 2026-01-31
    fmcg-agent-access --db data/fmcg.db verify

Every command prints the same artefact JSON the API
returns and exits non-zero on a refusal or a failed
verification, with the reason on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from fmcg_forecast.access.engine import AccessError
from fmcg_forecast.access.pack import load_access_pack
from fmcg_forecast.access.service import (
    AccessNotFoundError,
    AccessService,
    AccessValidationError,
)
from fmcg_forecast.access.verify import verify_access
from fmcg_forecast.store import build_store


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-access")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pack", help="print the access pack")
    p = sub.add_parser("grant", help="strike a grant (or narrow an existing one)")
    p.add_argument("subject")
    p.add_argument("--role", required=True)
    p.add_argument(
        "--markets",
        default=None,
        help="comma-separated market ids; omit for all markets",
    )
    p.add_argument("--by", required=True)
    p.add_argument("--on", type=date.fromisoformat, required=True)
    p = sub.add_parser("repeal", help="repeal a name's standing grant")
    p.add_argument("subject")
    p.add_argument("--by", required=True)
    p.add_argument("--on", type=date.fromisoformat, required=True)
    sub.add_parser("grants", help="list every grant act")
    p = sub.add_parser("standing", help="show a name's standing grant")
    p.add_argument("subject")
    sub.add_parser("entries", help="list the recorded reads")
    p = sub.add_parser("strike-log", help="fold the audit log")
    p.add_argument("--on", type=date.fromisoformat, required=True)
    sub.add_parser("verify", help="re-derive the access layer")
    args = parser.parse_args(argv)

    store = build_store(args.db)
    service = AccessService(store)
    try:
        if args.command == "pack":
            _print(load_access_pack().model_dump(mode="json"))
        elif args.command == "grant":
            markets = (
                [m.strip() for m in args.markets.split(",") if m.strip()]
                if args.markets
                else None
            )
            grant = service.strike_grant(
                args.subject, args.role, markets, args.by, args.on
            )
            _print(service.grant_view(grant))
        elif args.command == "repeal":
            grant = service.strike_grant(
                args.subject, None, None, args.by, args.on
            )
            _print(service.grant_view(grant))
        elif args.command == "grants":
            _print(
                [service.grant_view(g) for g in store.list_principal_grants()]
            )
        elif args.command == "standing":
            grant = service.standing_grant(args.subject)
            if grant is None:
                raise AccessNotFoundError(
                    f"no standing grant over {args.subject!r}"
                )
            _print(service.grant_view(grant))
        elif args.command == "entries":
            _print(
                [e.model_dump(mode="json") for e in store.list_access_entries()]
            )
        elif args.command == "strike-log":
            _print(service.strike_access_log(args.on).model_dump(mode="json"))
        elif args.command == "verify":
            problems = verify_access(store)
            _print({"problems": problems})
            if problems:
                return 1
        return 0
    except (AccessNotFoundError, AccessValidationError, AccessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
