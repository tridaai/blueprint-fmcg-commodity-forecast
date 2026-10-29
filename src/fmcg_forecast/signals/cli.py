"""The signals CLI — the same service the API serves.

    fmcg-agent-signals --db data/fmcg.db compute soybean indore
    fmcg-agent-signals --db data/fmcg.db list
    fmcg-agent-signals --db data/fmcg.db show SIG-...
    fmcg-agent-signals --db data/fmcg.db verify SIG-...

Every command prints the same artefact JSON the API returns and
exits non-zero on a refusal, with the refusal on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys

from fmcg_forecast.signals.pack import load_signal_pack
from fmcg_forecast.signals.service import (
    SignalError,
    SignalNotFoundError,
    SignalService,
)
from fmcg_forecast.store import build_store


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-signals")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pack", help="print the signal pack")
    p = sub.add_parser("compute", help="compute a series' buy signal")
    p.add_argument("commodity")
    p.add_argument("market")
    p = sub.add_parser("list", help="list stored signals")
    p.add_argument("--commodity", default=None)
    p.add_argument("--market", default=None)
    p = sub.add_parser("show", help="show one signal")
    p.add_argument("signal_id")
    p = sub.add_parser("verify", help="re-perform one signal")
    p.add_argument("signal_id")

    args = parser.parse_args(argv)
    store = build_store(args.db)
    service = SignalService(store)
    try:
        if args.command == "pack":
            _print(load_signal_pack().model_dump(mode="json"))
        elif args.command == "compute":
            signal = service.compute_for_series(args.commodity, args.market)
            _print(signal.model_dump(mode="json"))
        elif args.command == "list":
            _print(
                [
                    s.model_dump(mode="json")
                    for s in service.list_signals(args.commodity, args.market)
                ]
            )
        elif args.command == "show":
            _print(service.signal_view(args.signal_id))
        elif args.command == "verify":
            problems = service.verify_stored(args.signal_id)
            _print({"signal_id": args.signal_id, "problems": problems})
            if problems:
                return 1
    except (SignalError, SignalNotFoundError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
