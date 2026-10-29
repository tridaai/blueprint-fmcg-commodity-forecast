"""The alerts CLI — the same service the API serves.

    fmcg-agent-alerts --db data/fmcg.db subscribe --subscriber r.menon \
        --role desk_head --entered-on 2026-01-01 --commodities soybean,wheat \
        --kinds buy_signal,event_window,price_move,accuracy_degraded,coverage_collapse
    fmcg-agent-alerts --db data/fmcg.db sweep --at 2026-01-05T09:00:00
    fmcg-agent-alerts --db data/fmcg.db alerts
    fmcg-agent-alerts --db data/fmcg.db show ALT-... --at 2026-01-08T09:00:00
    fmcg-agent-alerts --db data/fmcg.db ack ALT-... --actor r.menon \
        --role desk_head --at 2026-01-05T10:00:00
    fmcg-agent-alerts --db data/fmcg.db close ALT-... --actor r.menon \
        --role desk_head --at 2026-01-05T11:00:00 --reason acted_on
    fmcg-agent-alerts --db data/fmcg.db digest SUB-... --date 2026-01-05

Every command prints the same artefact JSON the API returns and
exits non-zero on a refusal, with the refusal on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime

from fmcg_forecast.alerts.pack import load_alert_pack
from fmcg_forecast.alerts.service import (
    AlertNotFoundError,
    AlertService,
    AlertStateError,
    AlertValidationError,
)
from fmcg_forecast.store import build_store


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-alerts")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pack", help="print the alert pack")
    p = sub.add_parser("subscribe", help="enter or supersede a subscription")
    p.add_argument("--subscriber", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--entered-on", required=True)
    p.add_argument("--commodities", default="")
    p.add_argument("--markets", default="")
    p.add_argument("--kinds", required=True)
    p.add_argument("--min-severity", default="minor")
    p.add_argument("--note", default="")
    p = sub.add_parser("subscriptions", help="list subscriptions")
    p.add_argument("--subscriber", default=None)
    p = sub.add_parser("sweep", help="derive alerts from the record")
    p.add_argument("--at", required=True)
    sub.add_parser("crossings", help="list computed price crossings")
    p = sub.add_parser("alerts", help="list alerts")
    p.add_argument("--commodity", default=None)
    p.add_argument("--market", default=None)
    p.add_argument("--subscription-id", default=None)
    p = sub.add_parser("show", help="show one alert with its folded state")
    p.add_argument("alert_id")
    p.add_argument("--at", default=None)
    p = sub.add_parser("ack", help="acknowledge an alert")
    p.add_argument("alert_id")
    p.add_argument("--actor", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--at", required=True)
    p.add_argument("--note", default="")
    p = sub.add_parser("close", help="close an alert with a stated reason")
    p.add_argument("alert_id")
    p.add_argument("--actor", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--at", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--note", default="")
    p = sub.add_parser("digest", help="build a subscriber's daily digest")
    p.add_argument("subscription_id")
    p.add_argument("--date", required=True)
    p = sub.add_parser("verify", help="re-perform one alert, or all with --all")
    p.add_argument("alert_id", nargs="?")
    p.add_argument("--all", action="store_true")

    args = parser.parse_args(argv)
    store = build_store(args.db)
    service = AlertService(store)
    try:
        if args.command == "pack":
            _print(load_alert_pack().model_dump(mode="json"))
        elif args.command == "subscribe":
            subscription = service.enter_subscription(
                subscriber=args.subscriber,
                role=args.role,
                entered_on=date.fromisoformat(args.entered_on),
                commodities=_csv(args.commodities),
                markets=_csv(args.markets),
                kinds=_csv(args.kinds),
                min_severity=args.min_severity,
                note=args.note,
            )
            _print(service.subscription_view(subscription.subscription_id))
        elif args.command == "subscriptions":
            _print(
                [
                    service.subscription_view(s.subscription_id)
                    for s in service.list_subscriptions(args.subscriber)
                ]
            )
        elif args.command == "sweep":
            _print(service.sweep(datetime.fromisoformat(args.at)))
        elif args.command == "crossings":
            from fmcg_forecast.alerts.engine import compute_crossings

            _print(
                [
                    c.model_dump(mode="json")
                    for c in compute_crossings(store, service.pack)
                ]
            )
        elif args.command == "alerts":
            _print(
                [
                    a.model_dump(mode="json")
                    for a in service.list_alerts(
                        args.commodity, args.market, args.subscription_id
                    )
                ]
            )
        elif args.command == "show":
            now = (
                datetime.fromisoformat(args.at)
                if args.at
                else datetime.now()
            )
            _print(service.alert_view(args.alert_id, now))
        elif args.command == "ack":
            act = service.acknowledge(
                args.alert_id,
                actor=args.actor,
                role=args.role,
                acted_at=datetime.fromisoformat(args.at),
                note=args.note,
            )
            _print(act.model_dump(mode="json"))
        elif args.command == "close":
            act = service.close(
                args.alert_id,
                actor=args.actor,
                role=args.role,
                acted_at=datetime.fromisoformat(args.at),
                reason=args.reason,
                note=args.note,
            )
            _print(act.model_dump(mode="json"))
        elif args.command == "digest":
            digest = service.build_digest(
                args.subscription_id, date.fromisoformat(args.date)
            )
            _print(service.digest_view(digest.digest_id))
        elif args.command == "verify":
            if args.all:
                problems = service.verify_all()
                _print({"scope": "all", "problems": problems})
            else:
                problems = service.verify_stored(args.alert_id)
                _print({"alert_id": args.alert_id, "problems": problems})
            if problems:
                return 1
    except (
        AlertNotFoundError,
        AlertStateError,
        AlertValidationError,
        ValueError,
    ) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
