"""The access engine — grant folds and read judgements,
in code.

Everything here is a pure fold or judgement over stored
artefacts under the pack's stated rules:

- **The standing grant.** A name's acts form one chain
  by supersession links; the standing grant is the act
  no later act supersedes. A chain that forks or breaks
  is not folded quietly — the fold raises, and the
  verifier names it.
- **The judgement.** A governed read is judged under
  one grant artefact: no grant, hidden; a role the pack
  bars from the surface, hidden; a spanned market
  outside the grant's scope, hidden; otherwise allowed.
  The reasons are the pack's outcome vocabulary, and
  they are recorded on the entry — the answer the
  reader gets is existence-hiding either way.

Names compare folded under the desk's fold: case,
spacing and punctuation are not identity.
"""

from __future__ import annotations

from fmcg_forecast.access.models import PrincipalGrant
from fmcg_forecast.access.pack import AccessPack


class AccessError(Exception):
    """An access computation the record refuses."""


def folded_name(name: str) -> str:
    """The desk's name fold: \"A. Sharma\", \"a.sharma\"
    and \"A  SHARMA\" are one person."""
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def fold_grants(
    grants: list[PrincipalGrant],
) -> dict[str, PrincipalGrant]:
    """The standing grant per folded subject name.

    Acts are chained by supersedes links; the standing
    act is the one no other act over the name
    supersedes. Raises AccessError on a fork (two acts
    superseding one act) or a broken chain (an act
    superseding an act over a different name, or one
    that is not on record).
    """
    by_id = {g.grant_id: g for g in grants}
    groups: dict[str, list[PrincipalGrant]] = {}
    for grant in grants:
        groups.setdefault(folded_name(grant.subject), []).append(grant)
    standing: dict[str, PrincipalGrant] = {}
    for folded, acts in groups.items():
        superseded: set[str] = set()
        for grant in acts:
            if grant.supersedes_grant_id is None:
                continue
            prior = by_id.get(grant.supersedes_grant_id)
            if prior is None:
                raise AccessError(
                    f"grant {grant.grant_id} supersedes "
                    f"{grant.supersedes_grant_id}, which is not "
                    "on record — a broken chain"
                )
            if folded_name(prior.subject) != folded:
                raise AccessError(
                    f"grant {grant.grant_id} over "
                    f"{grant.subject!r} supersedes an act over "
                    f"{prior.subject!r} — a chain over two names"
                )
            if grant.supersedes_grant_id in superseded:
                raise AccessError(
                    f"grants fork over {grant.subject!r}: two "
                    "acts supersede "
                    f"{grant.supersedes_grant_id}"
                )
            superseded.add(grant.supersedes_grant_id)
        heads = [g for g in acts if g.grant_id not in superseded]
        if len(heads) != 1:
            raise AccessError(
                f"the acts over {acts[0].subject!r} fold to "
                f"{len(heads)} heads, not one chain"
            )
        walked: set[str] = set()
        current: PrincipalGrant | None = heads[0]
        while current is not None:
            if current.grant_id in walked:
                raise AccessError(
                    f"the chain over {acts[0].subject!r} cycles"
                )
            walked.add(current.grant_id)
            current = (
                by_id.get(current.supersedes_grant_id)
                if current.supersedes_grant_id
                else None
            )
        if walked != {g.grant_id for g in acts}:
            raise AccessError(
                f"acts over {acts[0].subject!r} sit outside "
                "the chain the fold walks — a second chain "
                "over one name"
            )
        standing[folded] = heads[0]
    return standing


def judge_read(
    pack: AccessPack,
    grant: PrincipalGrant | None,
    surface: str,
    markets: list[str],
) -> str:
    """Judge one governed read under one grant artefact.

    Returns the pack's outcome vocabulary. A grant that
    confers no role (a repeal) judges as no grant: the
    name stands ungranted.
    """
    if grant is None or grant.role is None:
        return "hidden_unknown_principal"
    scope = pack.role_scope(grant.role)
    if surface not in scope.surfaces:
        return "hidden_role_surface"
    if grant.markets is not None:
        in_scope = set(grant.markets)
        if any(market not in in_scope for market in markets):
            return "hidden_out_of_scope"
    return "allowed"
