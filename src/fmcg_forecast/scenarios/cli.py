"""The scenario studio CLI — the same service the API serves.

    fmcg-agent-scenarios --db data/fmcg.db parse \
        --commodity soybean --market indore \
        --base FCST-... --text "what if arrivals drop 10%?"
    fmcg-agent-scenarios --db data/fmcg.db run \
        --request SCRQ-... --base FCST-... --author a.sharma
    fmcg-agent-scenarios --db data/fmcg.db diff SCN-...
    fmcg-agent-scenarios --db data/fmcg.db adopt SCN-... \
        --adopter r.menon --role "Head of Trading Desk"
    fmcg-agent-scenarios --db data/fmcg.db adopted \
        --commodity soybean --market indore

Every command prints the same artefact JSON the API returns and
exits non-zero on a refusal, with the refusal on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from fmcg_forecast.events.service import EventService
from fmcg_forecast.forecast.service import ForecastService
from fmcg_forecast.modelport import OfflineModel
from fmcg_forecast.scenarios.models import LeverApplication
from fmcg_forecast.scenarios.service import ScenarioError, ScenarioService
from fmcg_forecast.sentiment.service import SentimentService
from fmcg_forecast.store import build_store


def _service(db: str) -> ScenarioService:
    store = build_store(db)
    model = OfflineModel()
    sentiment = SentimentService(store, model)
    events = EventService(store)
    forecasts = ForecastService(
        store,
        model,
        sentiment_provider=sentiment.forecast_input,
        sentiment_claim_verifier=sentiment.verify_claims,
        events_provider=events.forecast_adjustments,
    )
    return ScenarioService(
        store,
        model,
        forecasts,
        events,
        sentiment_provider=sentiment.forecast_input,
    )


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-scenarios")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("parse", help="parse a typed what-if into a request")
    p.add_argument("--commodity", required=True)
    p.add_argument("--market", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--base", default=None)

    p = sub.add_parser("create", help="post a structured lever set as a request")
    p.add_argument("--commodity", required=True)
    p.add_argument("--market", required=True)
    p.add_argument("--levers", required=True, help="JSON list of lever objects")

    p = sub.add_parser("run", help="run a scenario fork")
    p.add_argument("--request", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--author", required=True)
    p.add_argument("--on", default=None, help="creation date (ISO); default today")

    p = sub.add_parser("show", help="one scenario, labelled")
    p.add_argument("scenario_id")

    p = sub.add_parser("diff", help="the fork-vs-base diff")
    p.add_argument("scenario_id")

    p = sub.add_parser("verify", help="re-perform a stored scenario")
    p.add_argument("scenario_id")

    p = sub.add_parser("adopt", help="the adoption act")
    p.add_argument("scenario_id")
    p.add_argument("--adopter", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--on", default=None)

    p = sub.add_parser("adopted", help="the desk's adopted view for a series")
    p.add_argument("--commodity", required=True)
    p.add_argument("--market", required=True)

    args = parser.parse_args(argv)
    service = _service(args.db)
    try:
        if args.command == "parse":
            request = service.parse_request(
                args.commodity, args.market, args.text, args.base
            )
            _print(request.model_dump(mode="json"))
        elif args.command == "create":
            levers = [
                LeverApplication(**raw) for raw in json.loads(args.levers)
            ]
            request = service.create_request(args.commodity, args.market, levers)
            _print(request.model_dump(mode="json"))
        elif args.command == "run":
            run = service.run_scenario(
                args.request,
                args.base,
                args.author,
                date.fromisoformat(args.on) if args.on else date.today(),
            )
            _print(service.scenario_view(run.scenario_id))
        elif args.command == "show":
            _print(service.scenario_view(args.scenario_id))
        elif args.command == "diff":
            _print(service.diff(args.scenario_id).model_dump(mode="json"))
        elif args.command == "verify":
            problems = service.verify_stored(args.scenario_id)
            _print({"scenario_id": args.scenario_id, "problems": problems})
            return 1 if problems else 0
        elif args.command == "adopt":
            adoption = service.adopt(
                args.scenario_id,
                args.adopter,
                args.role,
                date.fromisoformat(args.on) if args.on else date.today(),
            )
            _print(adoption.model_dump(mode="json"))
        elif args.command == "adopted":
            _print(service.adopted_view(args.commodity, args.market))
    except ScenarioError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
