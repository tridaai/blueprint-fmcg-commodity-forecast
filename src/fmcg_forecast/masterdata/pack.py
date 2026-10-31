"""The master data pack — what the desk's reference
data is, and how it may change, as data.

The catalogue in code says which commodities trade at
which markets and on which weekly pattern. What it
cannot say is that a market closed for a festival, or
opened on a Sunday for a special session, or that a
display name was corrected — and a holiday is exactly
what 'missing data' means: a day the market never
opened is not a gap in coverage, and a special session
nobody recorded is. Until this round those facts had
nowhere to live. The rules for giving them one:

- Master data is versioned data, struck whole. A
  version carries every market's calendar (its weekly
  pattern, its holidays, its extra operating days),
  the commodity and market display names, and the unit
  statements — and supersedes the standing version by
  link. The genesis state is the catalogue's own:
  each market's calendar follows its commodity's
  reporting pattern, no holidays, no extras.
- Edits are acts with authors. A version is struck by
  a named editor holding the master-data right under
  the access pack (a standing desk-head grant), and
  carries a field-by-field diff against the version
  it supersedes, re-derived by the verifier. A strike
  that changes nothing is refused — a version that
  moves nothing is not a version. A version stands on
  strike: master data is reference data, and the
  AD2 chain governs the desk's policy limits, not
  a market's holiday list — the discipline here is
  authorship, versioning and re-derivation.
- A calendar day's status is computed, never stored:
  operating when the weekly pattern opens the market,
  closed when a stated holiday closes it, open when a
  stated extra operating day opens it. A date named as
  both a holiday and an extra day is refused at the
  strike — the desk must say which one it means —
  rather than silently resolved by an ordering rule.
- Coverage verdicts are pinned to a calendar. The
  thin-data windows (from the thin pack) count
  expected days under a stated master data version;
  re-deriving a verdict under another version names
  exactly the dates whose status changed, and only
  windows containing a changed date may move. A
  display-name edit moves no verdict at all.
- Units are statements, not conversions buried in
  arithmetic: prices in rupees per quintal, arrivals
  in quintals, ten quintals to the tonne — the
  planning pack's own figure, stated once here.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

WEEKLY_PATTERNS: tuple[str, ...] = ("mon_sat", "tue_fri")


class MasterDataPack(BaseModel):
    """How master data may change, as one versioned pack."""

    model_config = ConfigDict(extra="forbid")

    version: str
    edit_rule: str = Field(
        description="Who may strike a version, and what "
        "it must carry, stated"
    )
    calendar_rule: str = Field(
        description="How a day's operating status is "
        "computed from a calendar, stated"
    )
    coverage_rule: str = Field(
        description="How coverage verdicts pin to a "
        "calendar version, stated"
    )
    price_unit: str = Field(description="The unit prices are stated in")
    quantity_unit: str = Field(
        description="The unit arrivals and volumes are stated in"
    )
    quintals_per_tonne: int = Field(
        description="The weight conversion, stated once"
    )
    scope_note: str


MASTERDATA_SCOPE_NOTE = (
    "reference data only — a calendar states when a "
    "market sat; it records no price and moves no "
    "observation, and re-deriving a coverage verdict "
    "under a new calendar changes the verdict's "
    "expectation, never the history it was counted from"
)


MASTERDATA_PACK_V1 = MasterDataPack(
    version="2026.10.1",
    edit_rule=(
        "A master data version is struck whole by a named "
        "editor holding a standing desk-head grant under "
        "the access pack, supersedes the standing version "
        "by link, and carries a field-by-field diff "
        "against it — every calendar's holidays and extra "
        "days, every display name, every unit statement — "
        "which the verifier re-derives. A strike whose "
        "diff is empty is refused. The version stands on "
        "strike; the access pack version it was judged "
        "under is recorded on its face."
    ),
    calendar_rule=(
        "A market's day is operating when its weekly "
        "pattern opens it (mon_sat: Monday to Saturday; "
        "tue_fri: Tuesday and Friday), closed when a "
        "stated holiday names the date, open when a "
        "stated extra operating day names it. A date "
        "named in both is refused at the strike: the "
        "editor names it once, as one or the other."
    ),
    coverage_rule=(
        "A coverage verdict names the master data "
        "version it was derived under. Expected days are "
        "the window's operating days under that version's "
        "calendar; observed days are the stored modal "
        "prices, unchanged by any calendar. Re-deriving "
        "under another version names the dates whose "
        "operating status changed inside the window, and "
        "only a window containing a changed date may "
        "return a different verdict."
    ),
    price_unit="INR per quintal",
    quantity_unit="quintals",
    quintals_per_tonne=10,
    scope_note=MASTERDATA_SCOPE_NOTE,
)


def load_masterdata_pack(version: str | None = None) -> MasterDataPack:
    """Load the genesis master data pack, fail-closed."""
    if version is None or version == MASTERDATA_PACK_V1.version:
        return MASTERDATA_PACK_V1
    raise ValueError(f"unknown master data pack version: {version!r}")
