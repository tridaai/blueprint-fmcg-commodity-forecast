"""The geo CLI — the same service the API serves.

    fmcg-agent-geo --db data/fmcg.db pack
    fmcg-agent-geo --db data/fmcg.db enter-cost wheat indore freight 45000 --by a.rao --on 2026-01-02
    fmcg-agent-geo --db data/fmcg.db costs --commodity wheat
    fmcg-agent-geo --db data/fmcg.db basis wheat --as-of 2025-12-31
    fmcg-agent-geo --db data/fmcg.db landed wheat --as-of 2025-12-31 --priced-for verdanta_plant
    fmcg-agent-geo --db data/fmcg.db map wheat --as-of 2025-12-31
    fmcg-agent-geo --db data/fmcg.db show basis BASIS-...
    fmcg-agent-geo --db data/fmcg.db verify

Every command prints the same artefact JSON the API returns
and exits non-zero on a refusal or a failed verification,
with the reason on stderr. Rates are integer paise per
quintal — the CLI takes paise, never a decimal price.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from fmcg_forecast.geo.engine import GeoError
from fmcg_forecast.geo.pack import load_geo_pack
from fmcg_forecast.geo.service import (
    GeoNotFoundError,
    GeoService,
    GeoValidationError,
)
from fmcg_forecast.store import build_store


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-geo")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pack", help="print the geo pack")
    p = sub.add_parser("enter-cost", help="enter one desk cost line")
    p.add_argument("commodity")
    p.add_argument("market")
    p.add_argument("line")
    p.add_argument("rate_paise", type=int)
    p.add_argument("--by", required=True)
    p.add_argument("--on", type=date.fromisoformat, required=True)
    p.add_argument("--note", default="")
    p = sub.add_parser("costs", help="list desk cost-line entries")
    p.add_argument("--commodity", default=None)
    p.add_argument("--market", default=None)
    p = sub.add_parser("basis", help="strike a basis reading")
    p.add_argument("commodity")
    p.add_argument("--as-of", type=date.fromisoformat, required=True)
    p = sub.add_parser("landed", help="strike a landed comparison")
    p.add_argument("commodity")
    p.add_argument("--as-of", type=date.fromisoformat, required=True)
    p.add_argument("--priced-for", required=True)
    p = sub.add_parser("map", help="strike a market map")
    p.add_argument("commodity")
    p.add_argument("--as-of", type=date.fromisoformat, required=True)
    p = sub.add_parser("show", help="show one artefact with its problems")
    p.add_argument("kind", choices=["basis", "landed", "map"])
    p.add_argument("artefact_id")
    p = sub.add_parser("verify", help="re-perform every geo artefact")
    args = parser.parse_args(argv)
    store = build_store(args.db)
    service = GeoService(store)
    try:
        if args.command == "pack":
            _print(load_geo_pack().model_dump(mode="json"))
        elif args.command == "enter-cost":
            entry = service.enter_cost_line(
                args.commodity,
                args.market,
                args.line,
                args.rate_paise,
                args.by,
                args.on,
                args.note,
            )
            _print(entry.model_dump(mode="json"))
        elif args.command == "costs":
            _print(
                [
                    e.model_dump(mode="json")
                    for e in service.list_cost_lines(
                        args.commodity, args.market
                    )
                ]
            )
        elif args.command == "basis":
            reading = service.strike_basis_reading(
                args.commodity, args.as_of
            )
            _print(service.basis_view(reading.reading_id))
        elif args.command == "landed":
            comparison = service.strike_landed_comparison(
                args.commodity, args.as_of, args.priced_for
            )
            _print(service.landed_view(comparison.comparison_id))
        elif args.command == "map":
            market_map = service.strike_map(args.commodity, args.as_of)
            _print(service.map_view(market_map.map_id))
        elif args.command == "show":
            view = {
                "basis": service.basis_view,
                "landed": service.landed_view,
                "map": service.map_view,
            }[args.kind](args.artefact_id)
            _print(view)
        elif args.command == "verify":
            problems = service.verify_all()
            _print({"scope": "all", "problems": problems})
            if problems:
                return 1
    except (GeoNotFoundError, GeoValidationError, GeoError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
