"""The access service — grants struck under discipline,
governed reads judged and recorded, the audit log.

The strike-time rules, all judged here in code:

- A grant act's granter holds a standing desk-head
  grant and is not the subject — except the book's
  first act, which must be a bootstrap: its own subject
  as granter, the desk-head role, all markets.
- A scope names only markets the catalogue carries;
  a repeal confers nothing and scopes nothing.
- A governed read names its principal, is judged under
  the standing grant, and is recorded as an entry
  before the answer — the caller answers allowed, and
  answers every hidden outcome exactly as if the
  artefact did not exist.
"""

from __future__ import annotations

from datetime import date

from fmcg_forecast.access.engine import (
    AccessError,
    fold_grants,
    folded_name,
    judge_read,
)
from fmcg_forecast.access.models import (
    AccessEntry,
    AccessLog,
    AccessLogEntry,
    PrincipalGrant,
    access_log_content_id,
    entry_content_id,
    grant_content_id,
)
from fmcg_forecast.access.pack import (
    ROLES,
    AccessPack,
    load_access_pack,
)
from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.store import Store

_CATALOGUE_MARKETS = sorted(
    {m.market for spec in BY_NAME.values() for m in spec.markets}
)

ACCESS_LOG_FOLD_RULE = (
    "every access entry on record, folded in strike "
    "(sequence) order and numbered from 1 with no gaps; "
    "each line carries the entry's id, principal, role, "
    "surface, target and outcome as struck"
)


class AccessNotFoundError(LookupError):
    """No access artefact with that id."""


class AccessValidationError(ValueError):
    """An access act or read the pack refuses."""


def _require_named(value: str, what: str) -> str:
    if not value or not value.strip():
        raise AccessValidationError(f"a {what} must be named")
    return value.strip()


class AccessService:
    def __init__(self, store: Store, pack: AccessPack | None = None):
        self.store = store
        self.pack = pack or load_access_pack()

    # -- grants ------------------------------------------------------

    def standing_grants(self) -> dict[str, PrincipalGrant]:
        try:
            return fold_grants(self.store.list_principal_grants())
        except AccessError as exc:
            raise AccessValidationError(str(exc)) from exc

    def standing_grant(self, subject: str) -> PrincipalGrant | None:
        return self.standing_grants().get(folded_name(subject))

    def strike_grant(
        self,
        subject: str,
        role: str | None,
        markets: list[str] | None,
        granted_by: str,
        granted_on: date,
    ) -> PrincipalGrant:
        subject = _require_named(subject, "grant subject")
        granted_by = _require_named(granted_by, "granter")
        grants = self.store.list_principal_grants()
        folded_subject = folded_name(subject)
        try:
            standing = fold_grants(grants)
        except AccessError as exc:
            raise AccessValidationError(str(exc)) from exc
        prior = standing.get(folded_subject)
        bootstrap = not grants
        if bootstrap:
            if folded_name(granted_by) != folded_subject:
                raise AccessValidationError(
                    "the book's first grant is struck by its "
                    "own subject — there is no one else"
                )
            if role != "desk_head" or markets is not None:
                raise AccessValidationError(
                    "the bootstrap grant confers the desk-head "
                    "role over all markets, nothing narrower"
                )
        else:
            granter = standing.get(folded_name(granted_by))
            if (
                granter is None
                or granter.role is None
                or not self.pack.role_scope(granter.role).may_grant
            ):
                raise AccessValidationError(
                    f"granter {granted_by!r} holds no standing "
                    "grant that may strike grants"
                )
            if folded_name(granted_by) == folded_subject and role is not None:
                raise AccessValidationError(
                    "a principal may not grant themselves a "
                    "role — a desk head strikes grants over "
                    "other names (a self-repeal is an act, "
                    "and stands)"
                )
        if role is not None and role not in ROLES:
            raise AccessValidationError(
                f"role {role!r} is not a role the pack states "
                f"({', '.join(ROLES)})"
            )
        if role is None:
            if markets:
                raise AccessValidationError(
                    "a repeal confers nothing — it carries "
                    "no market scope"
                )
            markets = None
        if markets is not None:
            unknown = [m for m in markets if m not in _CATALOGUE_MARKETS]
            if unknown:
                raise AccessValidationError(
                    "a scope names only markets the catalogue "
                    f"carries; unknown: {unknown}"
                )
            if len(set(markets)) != len(markets):
                raise AccessValidationError(
                    "a scope names each market once"
                )
            markets = sorted(markets)
        grant = PrincipalGrant(
            grant_id="pending",
            seq=len(grants) + 1,
            subject=subject,
            role=role,
            markets=markets,
            granted_by=granted_by,
            granted_on=granted_on,
            supersedes_grant_id=prior.grant_id if prior else None,
            bootstrap=bootstrap,
            pack_version=self.pack.version,
        )
        grant = grant.model_copy(
            update={"grant_id": grant_content_id(grant)}
        )
        self.store.insert_principal_grant(grant)
        return grant

    def grant_view(self, grant: PrincipalGrant) -> dict:
        standing = self.standing_grants()
        head = standing.get(folded_name(grant.subject))
        payload = grant.model_dump(mode="json")
        payload["standing"] = bool(head and head.grant_id == grant.grant_id)
        payload["confers"] = grant.role is not None
        return payload

    # -- governed reads ------------------------------------------------

    def record_read(
        self,
        principal: str,
        surface: str,
        target_kind: str,
        target_id: str,
        markets: list[str],
        read_on: date,
    ) -> AccessEntry:
        """Judge one governed read and record it.

        Returns the struck entry; its outcome is the
        judgement. The caller answers allowed, and every
        hidden outcome as a 404.
        """
        principal = _require_named(principal, "reader")
        grant = self.standing_grant(principal)
        outcome = judge_read(self.pack, grant, surface, list(markets))
        entry = AccessEntry(
            entry_id="pending",
            seq=len(self.store.list_access_entries()) + 1,
            principal=principal,
            grant_id=grant.grant_id if grant else None,
            role=grant.role if grant else None,
            surface=surface,
            target_kind=target_kind,
            target_id=target_id,
            markets=sorted(set(markets)),
            outcome=outcome,
            read_on=read_on,
            pack_version=self.pack.version,
        )
        entry = entry.model_copy(
            update={"entry_id": entry_content_id(entry)}
        )
        self.store.insert_access_entry(entry)
        return entry

    # -- the audit log -----------------------------------------------

    def strike_access_log(self, struck_on: date) -> AccessLog:
        entries = self.store.list_access_entries()
        folded = [
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
        log = AccessLog(
            log_id="pending",
            struck_on=struck_on,
            upto_seq=entries[-1].seq if entries else 0,
            entries=folded,
            fold_rule=ACCESS_LOG_FOLD_RULE,
        )
        log = log.model_copy(
            update={"log_id": access_log_content_id(log)}
        )
        self.store.insert_access_log(log)
        return log

    def get_access_log(self, log_id: str) -> AccessLog:
        log = self.store.get_access_log(log_id)
        if log is None:
            raise AccessNotFoundError(f"no access log {log_id}")
        return log
