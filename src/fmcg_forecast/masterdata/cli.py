"""The master data CLI — the same service the API serves.

    fmcg-agent-masterdata --db data/fmcg.db pack
    fmcg-agent-masterdata --db data/fmcg.db standing
    fmcg-agent-masterdata --db data/fmcg.db strike --label diwali-2026 --state-file state.json --by d.kaur --on 2026-01-02
    fmcg-agent-masterdata --db data/fmcg.db versions
    fmcg-agent-masterdata --db data/fmcg.db version MDV-...
    fmcg-agent-masterdata --db data/fmcg.db coverage wheat kanpur --as-of 2025-12-31
    fmcg-agent-masterdata --db data/fmcg.db verify

Every command prints the same artefact JSON the API
returns and exits non-zero on a refusal or a failed
verification, with the reason on stderr. A version's
state is read from a JSON file — a complete state,
never a patch.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from fmcg_forecast.masterdata.engine import MasterDataError
from fmcg_forecast.masterdata.pack import load_masterdata_pack
from fmcg_forecast.masterdata.service import (
    MasterDataNotFoundError,
    MasterDataService,
    MasterDataValidationError,
)
from fmcg_forecast.masterdata.verify import verify_masterdata
from fmcg_forecast.store import build_store


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-masterdata")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pack", help="print the master data pack")
    sub.add_parser("standing", help="print the standing state")
    p = sub.add_parser("strike", help="strike a new version")
    p.add_argument("--label", required=True)
    p.add_argument("--state-file", required=True)
    p.add_argument("--by", required=True)
    p.add_argument("--on", type=date.fromisoformat, required=True)
    sub.add_parser("versions", help="list struck versions")
    p = sub.add_parser("version", help="show one version")
    p.add_argument("version_id")
    p = sub.add_parser("coverage", help="re-derive coverage under two calendars")
    p.add_argument("commodity")
    p.add_argument("market")
    p.add_argument("--as-of", type=date.fromisoformat, required=True)
    p.add_argument("--version-id", default=None)
    sub.add_parser("verify", help="re-derive the master data layer")
    args = parser.parse_args(argv)

    store = build_store(args.db)
    service = MasterDataService(store)
    try:
        if args.command == "pack":
            _print(load_masterdata_pack().model_dump(mode="json"))
        elif args.command == "standing":
            standing = service.standing()
            _print(
                {
                    "label": standing["label"],
                    "source_version_id": standing["source_version_id"],
                    "state": standing["state"].model_dump(mode="json"),
                }
            )
        elif args.command == "strike":
            state = json.loads(Path(args.state_file).read_text())
            version = service.strike_version(
                args.label, state, args.by, args.on
            )
            _print(service.version_view(version))
        elif args.command == "versions":
            _print(
                [
                    service.version_view(v)
                    for v in store.list_master_data_versions()
                ]
            )
        elif args.command == "version":
            _print(service.version_view(service.get_version(args.version_id)))
        elif args.command == "coverage":
            _print(
                service.coverage(
                    args.commodity, args.market, args.as_of,
                    version_id=args.version_id,
                )
            )
        elif args.command == "verify":
            problems = verify_masterdata(store)
            _print({"problems": problems})
            if problems:
                return 1
        return 0
    except (
        MasterDataNotFoundError,
        MasterDataValidationError,
        MasterDataError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
