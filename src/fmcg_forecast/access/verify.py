"""Re-derive the access layer from its artefacts.

Nothing here trusts the service's folds:

- the grant book must fold into exactly one chain per
  name, each act's supersedes link naming the act the
  fold says stood before it, the sequences gapless;
- every act's granter discipline is re-judged by
  folding the book in strike order up to that act —
  a non-bootstrap act struck by a name that did not
  then hold a granting role is named;
- every entry's outcome is re-judged under the grant
  its face names (an immutable artefact, not the
  moving fold), and its sequence must run gapless
  from 1;
- every audit log is re-folded from the entries and
  compared line for line.

Returns a list of problems; an empty list is a pass.
"""

from __future__ import annotations

from fmcg_forecast.access.engine import (
    AccessError,
    fold_grants,
    folded_name,
    judge_read,
)
from fmcg_forecast.access.models import AccessLogEntry
from fmcg_forecast.access.pack import load_access_pack
from fmcg_forecast.access.service import ACCESS_LOG_FOLD_RULE
from fmcg_forecast.store import Store


def verify_access(store: Store) -> list[str]:
    problems: list[str] = []
    pack = load_access_pack()
    grants = store.list_principal_grants()
    entries = store.list_access_entries()

    grants_by_id = {g.grant_id: g for g in grants}

    # Sequences run gapless from 1 in strike order.
    for position, grant in enumerate(grants, start=1):
        if grant.seq != position:
            problems.append(
                f"grant {grant.grant_id} carries sequence "
                f"{grant.seq} at position {position} — the "
                "grant book's strike order has a gap"
            )
    for position, entry in enumerate(entries, start=1):
        if entry.seq != position:
            problems.append(
                f"access entry {entry.entry_id} carries "
                f"sequence {entry.seq} at position "
                f"{position} — the audit trail has a gap"
            )

    # The book folds into one chain per name, and each
    # act's link names the act the fold superseded.
    try:
        fold_grants(grants)
    except AccessError as exc:
        problems.append(f"the grant book does not fold: {exc}")
    # Granter discipline, re-judged in strike order.
    seen: list = []
    try:
        for grant in grants:
            if grant.seq == 1:
                if not grant.bootstrap:
                    problems.append(
                        f"grant {grant.grant_id} opens the book "
                        "but is not flagged bootstrap"
                    )
                if folded_name(grant.granted_by) != folded_name(
                    grant.subject
                ):
                    problems.append(
                        f"bootstrap grant {grant.grant_id} was "
                        "struck by "
                        f"{grant.granted_by!r}, not its own "
                        "subject"
                    )
                if grant.role != "desk_head" or grant.markets is not None:
                    problems.append(
                        f"bootstrap grant {grant.grant_id} does "
                        "not confer the desk-head role over "
                        "all markets"
                    )
            else:
                if grant.bootstrap:
                    problems.append(
                        f"grant {grant.grant_id} is flagged "
                        "bootstrap but is not the book's "
                        "first act"
                    )
                prior_standing = fold_grants(seen)
                granter = prior_standing.get(folded_name(grant.granted_by))
                if (
                    granter is None
                    or granter.role is None
                    or not pack.role_scope(granter.role).may_grant
                ):
                    problems.append(
                        f"grant {grant.grant_id} was struck by "
                        f"{grant.granted_by!r}, who held no "
                        "granting role when it was struck"
                    )
                if (
                    folded_name(grant.granted_by)
                    == folded_name(grant.subject)
                    and grant.role is not None
                ):
                    problems.append(
                        f"grant {grant.grant_id} grants its "
                        "own granter a role"
                    )
            seen.append(grant)
    except AccessError as exc:
        problems.append(f"granter discipline cannot be re-judged: {exc}")

    # Every entry re-judged under the grant it names.
    for entry in entries:
        grant = grants_by_id.get(entry.grant_id) if entry.grant_id else None
        if entry.grant_id is not None and grant is None:
            problems.append(
                f"access entry {entry.entry_id} names grant "
                f"{entry.grant_id}, which is not on record"
            )
            continue
        if grant is not None and entry.role != grant.role:
            problems.append(
                f"access entry {entry.entry_id} records role "
                f"{entry.role!r} but its grant confers "
                f"{grant.role!r}"
            )
        expected = judge_read(pack, grant, entry.surface, entry.markets)
        if entry.outcome != expected:
            problems.append(
                f"access entry {entry.entry_id} records "
                f"outcome {entry.outcome!r}; re-judged under "
                f"its grant it is {expected!r}"
            )

    # Every audit log re-folded and compared.
    expected_lines = [
        AccessLogEntry(
            seq=position,
            entry_id=entry.entry_id,
            principal=entry.principal,
            role=entry.role,
            surface=entry.surface,
            target_kind=entry.target_kind,
            target_id=entry.target_id,
            outcome=entry.outcome,
            read_on=entry.read_on,
        )
        for position, entry in enumerate(entries, start=1)
    ]
    for log in store.list_access_logs():
        if log.entries != expected_lines:
            problems.append(
                f"access log {log.log_id} does not re-fold "
                "from the entries on record"
            )
        if log.upto_seq != (entries[-1].seq if entries else 0):
            problems.append(
                f"access log {log.log_id} folds up to "
                f"sequence {log.upto_seq}; the record runs "
                f"to {entries[-1].seq if entries else 0}"
            )
        if log.fold_rule != ACCESS_LOG_FOLD_RULE:
            problems.append(
                f"access log {log.log_id} states a fold rule "
                "the layer does not use"
            )
    return problems
