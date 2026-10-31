"""The desk CLI — the same service the API serves.

    fmcg-agent-desk --db data/fmcg.db pack
    fmcg-agent-desk --db data/fmcg.db propose --label 2026.11.1 --pack-file pack.json --by a.sharma --on 2026-01-02
    fmcg-agent-desk --db data/fmcg.db versions
    fmcg-agent-desk --db data/fmcg.db open-decision pack_change POL-... --by a.sharma --on 2026-01-02 --purpose "tighten the exposure bar"
    fmcg-agent-desk --db data/fmcg.db act DEC-... --by m.iyer --role analyst --outcome approve --on 2026-01-03
    fmcg-agent-desk --db data/fmcg.db decision DEC-...
    fmcg-agent-desk --db data/fmcg.db strike-log --on 2026-01-31
    fmcg-agent-desk --db data/fmcg.db comment forecast FCST-... --by m.iyer --on 2026-01-03 --body "check the arrivals line"
    fmcg-agent-desk --db data/fmcg.db task scenario SCN-... --title "confirm the lever with the desk" --by d.kaur --assignee m.iyer --on 2026-01-03
    fmcg-agent-desk --db data/fmcg.db task-act TSK-... --action close --by m.iyer --on 2026-01-05
    fmcg-agent-desk --db data/fmcg.db verify

Every command prints the same artefact JSON the API
returns and exits non-zero on a refusal or a failed
verification, with the reason on stderr. A proposal's
pack is read from a JSON file — a complete pack, never
a patch.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from fmcg_forecast.desk.engine import DeskError
from fmcg_forecast.desk.pack import load_desk_pack
from fmcg_forecast.desk.service import (
    DeskNotFoundError,
    DeskService,
    DeskValidationError,
)
from fmcg_forecast.store import build_store


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmcg-agent-desk")
    parser.add_argument("--db", default="./data/fmcg.db")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pack", help="print the standing desk policy pack")
    sub.add_parser("genesis", help="print the genesis pack in code")
    p = sub.add_parser("propose", help="propose a new pack version")
    p.add_argument("--label", required=True)
    p.add_argument("--pack-file", required=True)
    p.add_argument("--by", required=True)
    p.add_argument("--on", type=date.fromisoformat, required=True)
    sub.add_parser("versions", help="list proposed pack versions")
    p = sub.add_parser("version", help="show one pack version")
    p.add_argument("version_id")
    p = sub.add_parser("open-decision", help="open a chain decision")
    p.add_argument("kind")
    p.add_argument("target_id")
    p.add_argument("--by", required=True)
    p.add_argument("--on", type=date.fromisoformat, required=True)
    p.add_argument("--purpose", required=True)
    p = sub.add_parser("act", help="strike one step of a decision")
    p.add_argument("decision_id")
    p.add_argument("--by", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--outcome", required=True)
    p.add_argument("--on", type=date.fromisoformat, required=True)
    p.add_argument("--note", default="")
    p = sub.add_parser("decision", help="show one decision with its fold")
    p.add_argument("decision_id")
    p = sub.add_parser("decisions", help="list decisions")
    p.add_argument("--kind", default=None)
    p.add_argument("--target", default=None)
    p = sub.add_parser("strike-log", help="strike the decision log")
    p.add_argument("--on", type=date.fromisoformat, required=True)
    sub.add_parser("logs", help="list decision logs")
    p = sub.add_parser("log", help="show one decision log")
    p.add_argument("log_id")
    p = sub.add_parser("comment", help="pin a comment to an artefact")
    p.add_argument("target_kind")
    p.add_argument("target_id")
    p.add_argument("--by", required=True)
    p.add_argument("--on", type=date.fromisoformat, required=True)
    p.add_argument("--body", required=True)
    p = sub.add_parser("comments", help="list an artefact's comments")
    p.add_argument("target_kind")
    p.add_argument("target_id")
    p = sub.add_parser("task", help="open a follow-up task on an artefact")
    p.add_argument("target_kind")
    p.add_argument("target_id")
    p.add_argument("--title", required=True)
    p.add_argument("--by", required=True)
    p.add_argument("--assignee", required=True)
    p.add_argument("--on", type=date.fromisoformat, required=True)
    p = sub.add_parser("task-act", help="close or reopen a task")
    p.add_argument("task_id")
    p.add_argument("--action", required=True)
    p.add_argument("--by", required=True)
    p.add_argument("--on", type=date.fromisoformat, required=True)
    p.add_argument("--note", default="")
    p = sub.add_parser("show-task", help="show one task with its fold")
    p.add_argument("task_id")
    p = sub.add_parser("tasks", help="list tasks")
    p.add_argument("--kind", default=None)
    p.add_argument("--target", default=None)
    sub.add_parser("verify", help="re-perform every desk artefact")
    args = parser.parse_args(argv)
    store = build_store(args.db)
    service = DeskService(store)
    try:
        if args.command == "pack":
            standing = service.standing()
            _print(
                {
                    "label": standing["label"],
                    "source_version_id": standing["source_version_id"],
                    "pack": standing["pack"].model_dump(mode="json"),
                }
            )
        elif args.command == "genesis":
            _print(load_desk_pack().model_dump(mode="json"))
        elif args.command == "propose":
            pack_payload = json.loads(
                Path(args.pack_file).read_text(encoding="utf-8")
            )
            version = service.propose_policy_version(
                args.label, pack_payload, args.by, args.on
            )
            _print(service.policy_version_view(version.version_id))
        elif args.command == "versions":
            _print(
                [
                    v.model_dump(mode="json")
                    for v in service.list_policy_versions()
                ]
            )
        elif args.command == "version":
            _print(service.policy_version_view(args.version_id))
        elif args.command == "open-decision":
            decision = service.open_decision(
                args.kind, args.target_id, args.by, args.on,
                args.purpose,
            )
            _print(service.decision_view(decision.decision_id))
        elif args.command == "act":
            act = service.strike_act(
                args.decision_id, args.by, args.role,
                args.outcome, args.on, args.note,
            )
            _print(act.model_dump(mode="json"))
        elif args.command == "decision":
            _print(service.decision_view(args.decision_id))
        elif args.command == "decisions":
            _print(
                [
                    d.model_dump(mode="json")
                    for d in service.list_decisions(
                        args.kind, args.target
                    )
                ]
            )
        elif args.command == "strike-log":
            log = service.strike_decision_log(args.on)
            _print(service.decision_log_view(log.log_id))
        elif args.command == "logs":
            _print(
                [
                    log.model_dump(mode="json")
                    for log in service.list_decision_logs()
                ]
            )
        elif args.command == "log":
            _print(service.decision_log_view(args.log_id))
        elif args.command == "comment":
            comment = service.add_comment(
                args.target_kind, args.target_id, args.by,
                args.body, args.on,
            )
            _print(comment.model_dump(mode="json"))
        elif args.command == "comments":
            _print(
                [
                    c.model_dump(mode="json")
                    for c in service.list_comments(
                        args.target_kind, args.target_id
                    )
                ]
            )
        elif args.command == "task":
            task = service.open_task(
                args.target_kind, args.target_id, args.title,
                args.by, args.assignee, args.on,
            )
            _print(service.task_view(task.task_id))
        elif args.command == "task-act":
            act = service.strike_task_act(
                args.task_id, args.action, args.by, args.on,
                args.note,
            )
            _print(act.model_dump(mode="json"))
        elif args.command == "show-task":
            _print(service.task_view(args.task_id))
        elif args.command == "tasks":
            _print(
                [
                    t.model_dump(mode="json")
                    for t in service.list_tasks(args.kind, args.target)
                ]
            )
        elif args.command == "verify":
            problems = service.verify_all()
            _print({"scope": "all", "problems": problems})
            if problems:
                return 1
    except (
        DeskNotFoundError, DeskValidationError, DeskError, ValueError,
    ) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
