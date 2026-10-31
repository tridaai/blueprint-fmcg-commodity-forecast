"""The monitoring CLI — the same service the API serves.

    fmcg-agent-monitoring --db data/fmcg.db pack
    fmcg-agent-monitoring --db data/fmcg.db runs
    fmcg-agent-monitoring --db data/fmcg.db runs --profile offline
    fmcg-agent-monitoring --db data/fmcg.db board
    fmcg-agent-monitoring --db data/fmcg.db boards
    fmcg-agent-monitoring --db data/fmcg.db board MON-<id>
    fmcg-agent-monitoring --db data/fmcg.db verify

Every command prints the same artefact JSON the API
returns and exits non-zero on a failed verification,
with the reason on stderr. `board` with no id strikes
a fresh board as-of now; with an id it reads the
standing board back.
"""

from __future__ import annotations

import argparse
import json
import sys

from fmcg_forecast.monitoring.pack import load_monitoring_pack
from fmcg_forecast.monitoring.service import MonitoringService
from fmcg_forecast.monitoring.verify import verify_monitoring
from fmcg_forecast.store import build_store


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-monitoring")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pack", help="print the monitoring pack")
    p = sub.add_parser("runs", help="list run-ledger records")
    p.add_argument("--profile", default=None)
    p.add_argument("--purpose", default=None)
    p = sub.add_parser("board", help="strike a board, or read one back")
    p.add_argument("board_id", nargs="?", default=None)
    sub.add_parser("boards", help="list standing boards")
    sub.add_parser("verify", help="re-derive the monitoring layer")

    args = parser.parse_args(argv)
    pack = load_monitoring_pack()
    if args.command == "pack":
        _print(pack.model_dump(mode="json"))
        return 0
    store = build_store(args.db)
    service = MonitoringService(store, pack)
    if args.command == "runs":
        _print(
            [
                r.model_dump(mode="json")
                for r in service.list_runs(args.profile, args.purpose)
            ]
        )
        return 0
    if args.command == "board":
        if args.board_id is None:
            _print(service.strike_board().model_dump(mode="json"))
            return 0
        board = service.get_board(args.board_id)
        if board is None:
            print(f"no board {args.board_id}", file=sys.stderr)
            return 2
        _print(board.model_dump(mode="json"))
        return 0
    if args.command == "boards":
        _print([b.model_dump(mode="json") for b in service.list_boards()])
        return 0
    if args.command == "verify":
        problems = verify_monitoring(store, pack)
        _print({"problems": problems})
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
