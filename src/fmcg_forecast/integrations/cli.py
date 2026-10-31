"""The integrations CLI — the same service the API serves.

    fmcg-agent-integrations --db data/fmcg.db pack
    fmcg-agent-integrations --db data/fmcg.db issue-token erp \
        --scopes forecasts,signals --by asha
    fmcg-agent-integrations --db data/fmcg.db tokens
    fmcg-agent-integrations --db data/fmcg.db revoke TOK-<id> \
        --actor asha --reason "the bridge was replaced"
    fmcg-agent-integrations --db data/fmcg.db subscribe crm \
        --url https://example.invalid/hook --kinds alert_raised,forecast_approved --by asha
    fmcg-agent-integrations --db data/fmcg.db dispatch
    fmcg-agent-integrations --db data/fmcg.db deliveries
    fmcg-agent-integrations --db data/fmcg.db build-pack --as-of 2026-01-05
    fmcg-agent-integrations --db data/fmcg.db request-job --by asha --as-of 2026-01-05
    fmcg-agent-integrations --db data/fmcg.db run-job JOB-<id>
    fmcg-agent-integrations --db data/fmcg.db tools
    fmcg-agent-integrations --db data/fmcg.db call get_signal --args '{"signal_id": "SIG-..."}'
    fmcg-agent-integrations --db data/fmcg.db verify

Secrets print exactly once, on the issue/subscribe
commands that create them — issue prints the token's
secret, subscribe the subscription's — and never
again: list commands print the artefacts, whose token
form carries no secret at all and whose subscription
form is redacted. `dispatch` posts through the real
webhook port; against an unreachable endpoint the
attempts land as failed deliveries with the error
named, which the command reports.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from fmcg_forecast.integrations.pack import load_integrations_pack
from fmcg_forecast.integrations.port import UrllibWebhookPort
from fmcg_forecast.integrations.service import (
    IntegrationError,
    IntegrationsService,
    public_subscription,
)
from fmcg_forecast.integrations.tools import TOOL_CATALOGUE, call_tool
from fmcg_forecast.integrations.verify import verify_integrations
from fmcg_forecast.store import build_store


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-integrations")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pack", help="print the integrations pack")
    p = sub.add_parser("issue-token", help="issue a scoped token")
    p.add_argument("name")
    p.add_argument("--scopes", required=True, help="comma-separated surfaces")
    p.add_argument("--by", required=True, help="the issuing person")
    sub.add_parser("tokens", help="list tokens (hashes only, never secrets)")
    p = sub.add_parser("revoke", help="revoke a token by named act")
    p.add_argument("token_id")
    p.add_argument("--actor", required=True)
    p.add_argument("--reason", required=True)
    p = sub.add_parser("subscribe", help="strike a webhook subscription")
    p.add_argument("name")
    p.add_argument("--url", required=True)
    p.add_argument("--kinds", required=True, help="comma-separated event kinds")
    p.add_argument("--by", required=True, help="the person striking it")
    sub.add_parser(
        "subscriptions", help="list subscriptions (secrets redacted)"
    )
    sub.add_parser("dispatch", help="deliver pending webhook events")
    sub.add_parser("deliveries", help="list delivery attempts")
    p = sub.add_parser("build-pack", help="build a board pack synchronously")
    p.add_argument("--as-of", required=True, help="the pack date, YYYY-MM-DD")
    sub.add_parser("packs", help="list standing board packs")
    p = sub.add_parser("request-job", help="request an export job")
    p.add_argument("--by", required=True)
    p.add_argument("--as-of", required=True)
    p = sub.add_parser("run-job", help="run a requested export job")
    p.add_argument("job_id")
    sub.add_parser("jobs", help="list export jobs with their folded states")
    sub.add_parser("tools", help="print the tool catalogue")
    p = sub.add_parser("call", help="call one tool")
    p.add_argument("name")
    p.add_argument("--args", default="{}", help="the tool arguments, JSON")
    sub.add_parser("verify", help="re-derive the integration layer")

    args = parser.parse_args(argv)
    pack = load_integrations_pack()
    if args.command == "pack":
        _print(pack.model_dump(mode="json"))
        return 0
    if args.command == "tools":
        _print(TOOL_CATALOGUE)
        return 0
    store = build_store(args.db)
    service = IntegrationsService(store, pack)
    try:
        if args.command == "issue-token":
            token, secret = service.issue_token(
                args.name,
                [s.strip() for s in args.scopes.split(",") if s.strip()],
                args.by,
            )
            _print(
                {
                    "token": token.model_dump(mode="json"),
                    "secret_shown_once": secret,
                }
            )
            return 0
        if args.command == "tokens":
            _print(
                [
                    {
                        **t.model_dump(mode="json"),
                        "state": service.token_state(t),
                    }
                    for t in service.list_tokens()
                ]
            )
            return 0
        if args.command == "revoke":
            act = service.revoke_token(args.token_id, args.actor, args.reason)
            _print(act.model_dump(mode="json"))
            return 0
        if args.command == "subscribe":
            subscription, secret = service.create_subscription(
                args.name,
                args.url,
                [k.strip() for k in args.kinds.split(",") if k.strip()],
                args.by,
            )
            _print(
                {
                    "subscription": public_subscription(subscription),
                    "secret_shown_once": secret,
                }
            )
            return 0
        if args.command == "subscriptions":
            _print(
                [public_subscription(s) for s in service.list_subscriptions()]
            )
            return 0
        if args.command == "dispatch":
            struck = service.dispatch(UrllibWebhookPort())
            _print([d.model_dump(mode="json") for d in struck])
            return 0
        if args.command == "deliveries":
            _print(
                [d.model_dump(mode="json") for d in service.list_deliveries()]
            )
            return 0
        if args.command == "build-pack":
            board = service.build_pack(date.fromisoformat(args.as_of))
            _print(board.model_dump(mode="json"))
            return 0
        if args.command == "packs":
            _print([b.model_dump(mode="json") for b in service.list_packs()])
            return 0
        if args.command == "request-job":
            job = service.request_job(
                args.by, date.fromisoformat(args.as_of)
            )
            _print(
                {**job.model_dump(mode="json"), "state": service.job_state(job)}
            )
            return 0
        if args.command == "run-job":
            act = service.run_job(args.job_id)
            _print(act.model_dump(mode="json"))
            return 0
        if args.command == "jobs":
            _print(
                [
                    {
                        **j.model_dump(mode="json"),
                        "state": service.job_state(j),
                    }
                    for j in service.list_jobs()
                ]
            )
            return 0
        if args.command == "call":
            _print(call_tool(store, args.name, json.loads(args.args)))
            return 0
        if args.command == "verify":
            problems = verify_integrations(store, pack)
            _print({"problems": problems})
            return 1 if problems else 0
    except IntegrationError as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
