"""The access pack — who may see what, as data.

Until this round the desk's acts carried names and roles,
but its reads were open to whoever could reach the API:
a forecast's figures are commercially sensitive, and a
desk that cannot say who saw what cannot defend a number
it quoted. The rules that close that gap are stated
here, versioned, never buried in code:

- The roles (trader, desk head, viewer) and the read
  surfaces each role may use. The governed surfaces are
  the ones the desk's numbers leave by: the official
  forecast read, the dashboard assembly read, and the
  export read (the assembly's rendered page).
- Market scopes. A grant scopes a principal to named
  markets, or to all markets. A governed read is judged
  on the markets its artefact spans: every one must be
  in the principal's scope, or the artefact is hidden.
- Existence hiding. A governed read that is refused —
  the principal unknown, their role barred from the
  surface, or the artefact out of their scope — is
  answered exactly as if the artefact did not exist.
  A scoped reader cannot enumerate what they may not
  see by probing ids.
- The audit trail. Every governed read made under a
  named principal is recorded as an artefact before the
  answer is given, with its outcome on its face, and
  the audit log folds the record in strike order with
  no gaps — allowed reads and hidden ones alike, so
  the trail shows attempts as well as views. A read
  that names no principal is the local posture (the
  console's own reads, the demo): it proceeds unjudged
  and unrecorded, as the desk's reads always have —
  that boundary is stated, not hidden.
- Grants. A principal's role and scope stand only as a
  struck grant artefact: insert-only, superseded by a
  later act over the same folded name, repealable by an
  act that grants nothing. Grants are struck by a
  standing desk head who is not the subject — except
  the book's first grant, which its own subject strikes
  as desk head over all markets and which is flagged
  bootstrap on its face, because an empty book has no
  one else to strike it.

Names compare folded — case, spacing and punctuation
are not identity — under the same fold the desk's
chain rules use.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROLES: tuple[str, ...] = ("trader", "desk_head", "viewer")

SURFACES: tuple[str, ...] = (
    "forecast",
    "dashboard",
    "export",
    "grants",
    "master_data",
    "audit",
)

# The surfaces a governed read is judged on. Admin
# surfaces (grants, master_data, audit) are struck as
# acts and judged at strike time by the services.
READ_SURFACES: tuple[str, ...] = ("forecast", "dashboard", "export")

OUTCOMES: tuple[str, ...] = (
    "allowed",
    "hidden_unknown_principal",
    "hidden_role_surface",
    "hidden_out_of_scope",
)


class RoleScope(BaseModel):
    """One role's rights, as the pack states them."""

    model_config = ConfigDict(extra="forbid")

    role: str
    surfaces: list[str] = Field(
        description="The surfaces a principal holding this "
        "role may use — read surfaces are judged per read, "
        "admin surfaces at strike time"
    )
    may_grant: bool = Field(
        description="Whether this role may strike principal "
        "grants (and repeals) over other names"
    )
    may_edit_master_data: bool = Field(
        description="Whether this role may strike master "
        "data versions (F20-AD1)"
    )
    rule: str = Field(description="What this role is, stated")


class AccessPack(BaseModel):
    """Who may see what, as one versioned pack."""

    model_config = ConfigDict(extra="forbid")

    version: str
    roles: list[RoleScope] = Field(
        description="One entry per role — the loader refuses "
        "a pack that drops or duplicates one"
    )
    grant_rule: str = Field(
        description="How a grant comes to stand, stated"
    )
    scope_rule: str = Field(
        description="How a governed read is judged against "
        "a grant's market scope, stated"
    )
    hiding_rule: str = Field(
        description="How a refused governed read is "
        "answered, stated"
    )
    audit_rule: str = Field(
        description="What is recorded, and how the audit "
        "log folds it, stated"
    )
    scope_note: str

    @model_validator(mode="after")
    def _roles_cover_the_pack(self) -> "AccessPack":
        names = [r.role for r in self.roles]
        if sorted(names) != sorted(ROLES):
            raise ValueError(
                "an access pack carries exactly one entry "
                f"per role {ROLES}, got {names}"
            )
        for role in self.roles:
            unknown = [s for s in role.surfaces if s not in SURFACES]
            if unknown:
                raise ValueError(
                    f"role {role.role!r} names surfaces the "
                    f"pack does not govern: {unknown}"
                )
            if len(set(role.surfaces)) != len(role.surfaces):
                raise ValueError(
                    f"role {role.role!r} repeats a surface"
                )
        return self

    def role_scope(self, role: str) -> RoleScope:
        for entry in self.roles:
            if entry.role == role:
                return entry
        raise ValueError(f"no role {role!r} in the access pack")


ACCESS_SCOPE_NOTE = (
    "oversight only — a grant records who may see the "
    "desk's numbers; it places no trade and moves no "
    "money, and an access entry is a record of a read, "
    "never a copy of what was read"
)


ACCESS_PACK_V1 = AccessPack(
    version="2026.10.1",
    roles=[
        RoleScope(
            role="desk_head",
            surfaces=[
                "forecast", "dashboard", "export",
                "grants", "master_data", "audit",
            ],
            may_grant=True,
            may_edit_master_data=True,
            rule=(
                "The desk head sees the whole book, strikes "
                "grants and master data versions, and reads "
                "the audit trail."
            ),
        ),
        RoleScope(
            role="trader",
            surfaces=["forecast", "dashboard", "export"],
            may_grant=False,
            may_edit_master_data=False,
            rule=(
                "A trader reads and exports the governed "
                "surfaces for the markets their grant "
                "scopes them to — the series they work, "
                "not the whole book by default."
            ),
        ),
        RoleScope(
            role="viewer",
            surfaces=["forecast", "dashboard"],
            may_grant=False,
            may_edit_master_data=False,
            rule=(
                "A viewer reads official forecasts and "
                "dashboards within their scope but takes "
                "nothing out: no export surface."
            ),
        ),
    ],
    grant_rule=(
        "A grant is an insert-only artefact naming its "
        "subject, the role it confers (or none, which "
        "repeals), the markets it scopes (or all markets), "
        "its granter and its date, chained to the act it "
        "supersedes over the same folded name. The standing "
        "grant for a name is the latest act in that chain. "
        "An act stands only when its granter holds a "
        "standing desk-head grant and is not the subject — "
        "except the book's first act, struck by its own "
        "subject as desk head over all markets and flagged "
        "bootstrap on its face. A scope may name only "
        "markets the catalogue carries."
    ),
    scope_rule=(
        "A governed read is judged on the markets its "
        "artefact spans: an official forecast spans its "
        "own market; a dashboard assembly spans every "
        "market its panels resolved. The read is in scope "
        "when the grant covers all markets or names every "
        "spanned market. A read of an artefact spanning "
        "no market the catalogue knows is judged on the "
        "empty set — vacuously in scope for any granted "
        "principal, because it quotes no market's figures."
    ),
    hiding_rule=(
        "A governed read that is refused is answered "
        "exactly as if the artefact did not exist — the "
        "same 404, the same body — whatever the reason: "
        "the principal holds no standing grant, their role "
        "is barred from the surface, or the artefact spans "
        "a market outside their scope. The reason is "
        "recorded on the access entry, never in the answer."
    ),
    audit_rule=(
        "Every governed read made under a named principal "
        "strikes one access entry before the answer is "
        "given: the principal, the grant it was judged "
        "under, the surface, the artefact, the markets "
        "judged and the outcome, numbered in strike order. "
        "The audit log folds the entries numbered 1..N "
        "with no gaps, in strike order, up to its as-of; "
        "the verifier re-folds the record and compares "
        "entry for entry, re-judging every outcome under "
        "the grant its entry names."
    ),
    scope_note=ACCESS_SCOPE_NOTE,
)


def load_access_pack(version: str | None = None) -> AccessPack:
    """Load the genesis access pack, fail-closed.

    An unknown version is an error, never a silent
    fallback — a read judged under one pack must never
    be quietly re-judged under another.
    """
    if version is None or version == ACCESS_PACK_V1.version:
        return ACCESS_PACK_V1
    raise ValueError(f"unknown access pack version: {version!r}")
