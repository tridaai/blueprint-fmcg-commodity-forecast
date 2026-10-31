"""The screening CLI — the same service the API serves.

    fmcg-agent-screening --db data/fmcg.db pack
    fmcg-agent-screening --db data/fmcg.db check "Ignore previous instructions"
    fmcg-agent-screening --db data/fmcg.db records
    fmcg-agent-screening --db data/fmcg.db records --commodity wheat
    fmcg-agent-screening --db data/fmcg.db record NEWS-2025-001
    fmcg-agent-screening --db data/fmcg.db verify

Every command prints the same artefact JSON the API
returns and exits non-zero on a failed verification,
with the reason on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys

from fmcg_forecast.screening.engine import match_rules
from fmcg_forecast.screening.pack import load_screening_pack
from fmcg_forecast.screening.service import ScreeningService
from fmcg_forecast.screening.verify import verify_screening
from fmcg_forecast.store import build_store


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-screening")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pack", help="print the screening pack")
    p = sub.add_parser(
        "check", help="judge one text against the pack (no store writes)"
    )
    p.add_argument("text")
    p = sub.add_parser("records", help="list quarantine records")
    p.add_argument("--commodity", default=None)
    p = sub.add_parser("record", help="one item's quarantine record")
    p.add_argument("item_id")
    sub.add_parser("verify", help="re-derive the screening layer")

    args = parser.parse_args(argv)
    pack = load_screening_pack()
    if args.command == "pack":
        _print(pack.model_dump(mode="json"))
        return 0
    if args.command == "check":
        matched = match_rules(args.text, pack)
        _print({"matched_rule_ids": matched, "quarantined": bool(matched)})
        return 0
    store = build_store(args.db)
    service = ScreeningService(store, pack)
    if args.command == "records":
        _print(
            [r.model_dump(mode="json") for r in service.list_records(args.commodity)]
        )
        return 0
    if args.command == "record":
        record = service.get_record(args.item_id)
        if record is None:
            print(f"no quarantine record for item {args.item_id}", file=sys.stderr)
            return 2
        _print(record.model_dump(mode="json"))
        return 0
    if args.command == "verify":
        problems = verify_screening(store, pack)
        _print({"problems": problems})
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
