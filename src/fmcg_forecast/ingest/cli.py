"""The data-plane CLI — the same service the API serves.

    fmcg-agent-ingest --db data/fmcg.db sources
    fmcg-agent-ingest --db data/fmcg.db register-source \
        --source-id coop_mandi_drop --kind file_drop \
        --display "Cooperative mandi file drop" --owner "market data desk" \
        --cadence daily --drivers modal_price,arrivals \
        --licence-note "Cooperative society data share" \
        --registered-by d.rao --registered-by-role desk_head \
        --at 2026-01-05T09:00:00
    fmcg-agent-ingest --db data/fmcg.db load-file \
        --source agmarknet_file_drop --file arrivals.csv \
        --as-of 2026-01-05 --received-by d.rao --at 2026-01-05T09:30:00
    fmcg-agent-ingest --db data/fmcg.db batches
    fmcg-agent-ingest --db data/fmcg.db show BCH-...
    fmcg-agent-ingest --db data/fmcg.db quarantine
    fmcg-agent-ingest --db data/fmcg.db correct --commodity coffee \
        --market bengaluru --date 2025-12-29 --driver modal_price \
        --value 34250 --reason "transcription slip" \
        --corrected-by r.menon --corrected-by-role desk_head \
        --at 2026-01-05T10:00:00
    fmcg-agent-ingest --db data/fmcg.db effective --commodity coffee \
        --market bengaluru --date 2025-12-29 --driver modal_price
    fmcg-agent-ingest --db data/fmcg.db replay --commodity wheat \
        --market lucknow --origins 2025-07-01,2025-08-01 \
        --replayed-by d.rao --at 2026-01-05T11:00:00
    fmcg-agent-ingest --db data/fmcg.db verify

Every command prints the same artefact JSON the API returns and
exits non-zero on a refusal, with the refusal on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from fmcg_forecast.ingest.service import (
    IngestNotFoundError,
    IngestService,
    IngestValidationError,
)
from fmcg_forecast.store import build_store


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-ingest")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sources", help="list the source registry")
    p = sub.add_parser("register-source", help="register a source (a named act)")
    p.add_argument("--source-id", required=True)
    p.add_argument("--kind", required=True)
    p.add_argument("--display", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--cadence", required=True)
    p.add_argument("--drivers", required=True, help="comma-separated driver names")
    p.add_argument("--licence-note", required=True)
    p.add_argument("--registered-by", required=True)
    p.add_argument("--registered-by-role", required=True)
    p.add_argument("--at", required=True)
    p = sub.add_parser("load-file", help="load a file-drop delivery")
    p.add_argument("--source", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--as-of", default=None)
    p.add_argument("--kind", default="file_drop")
    p.add_argument("--received-by", required=True)
    p.add_argument("--at", required=True)
    sub.add_parser("batches", help="list batches").add_argument(
        "--source", default=None
    )
    p = sub.add_parser("show", help="show one batch with its rows and verdict")
    p.add_argument("batch_id")
    sub.add_parser("quarantine", help="list quarantine records").add_argument(
        "--batch", default=None
    )
    p = sub.add_parser("correct", help="record a correction overlay")
    p.add_argument("--commodity", required=True)
    p.add_argument("--market", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--driver", required=True)
    p.add_argument("--value", type=float, required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--corrected-by", required=True)
    p.add_argument("--corrected-by-role", required=True)
    p.add_argument("--at", required=True)
    p.add_argument("--corrects-quarantine", default=None)
    p = sub.add_parser("effective", help="read a fact's effective value")
    p.add_argument("--commodity", required=True)
    p.add_argument("--market", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--driver", required=True)
    p = sub.add_parser("replay", help="replay backtests over backfilled origins")
    p.add_argument("--commodity", required=True)
    p.add_argument("--market", required=True)
    p.add_argument("--origins", required=True, help="comma-separated ISO dates")
    p.add_argument("--replayed-by", required=True)
    p.add_argument("--at", required=True)
    sub.add_parser("verify", help="re-perform the whole data plane")

    args = parser.parse_args(argv)
    store = build_store(args.db)
    service = IngestService(store)
    try:
        if args.command == "sources":
            _print([s.model_dump(mode="json") for s in service.list_sources()])
        elif args.command == "register-source":
            registration = service.register_source(
                args.source_id,
                args.kind,
                args.display,
                args.owner,
                args.cadence,
                [d.strip() for d in args.drivers.split(",") if d.strip()],
                args.licence_note,
                args.registered_by,
                args.registered_by_role,
                datetime.fromisoformat(args.at),
            )
            _print(registration.model_dump(mode="json"))
        elif args.command == "load-file":
            batch = service.load_file_drop(
                args.source,
                Path(args.file).read_text(encoding="utf-8"),
                as_of=date.fromisoformat(args.as_of) if args.as_of else None,
                received_by=args.received_by,
                received_at=datetime.fromisoformat(args.at),
                connector_kind=args.kind,
            )
            _print(service.batch_view(batch.batch_id))
        elif args.command == "batches":
            _print(
                [b.model_dump(mode="json") for b in service.list_batches(args.source)]
            )
        elif args.command == "show":
            _print(service.batch_view(args.batch_id))
        elif args.command == "quarantine":
            _print(
                [
                    r.model_dump(mode="json")
                    for r in service.list_quarantine(batch_id=args.batch)
                ]
            )
        elif args.command == "correct":
            correction = service.correct(
                args.commodity,
                args.market,
                date.fromisoformat(args.date),
                args.driver,
                args.value,
                reason=args.reason,
                corrected_by=args.corrected_by,
                corrected_by_role=args.corrected_by_role,
                corrected_at=datetime.fromisoformat(args.at),
                corrects_quarantine_id=args.corrects_quarantine,
            )
            _print(correction.model_dump(mode="json"))
        elif args.command == "effective":
            _print(
                service.effective_fact(
                    args.commodity,
                    args.market,
                    date.fromisoformat(args.date),
                    args.driver,
                )
            )
        elif args.command == "replay":
            replay = service.replay_backtests(
                args.commodity,
                args.market,
                [date.fromisoformat(d.strip()) for d in args.origins.split(",")],
                replayed_by=args.replayed_by,
                replayed_at=datetime.fromisoformat(args.at),
            )
            _print(replay.model_dump(mode="json"))
        elif args.command == "verify":
            problems = service.verify_all()
            _print({"problems": problems})
            if problems:
                return 1
    except (IngestValidationError, IngestNotFoundError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
