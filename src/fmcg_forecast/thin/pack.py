"""The thin-data pack — how confidence is earned, as data.

Law 7's rules are stated here, versioned, never buried in code:
which windows a series' coverage is judged over, when a driver
counts as stale, what a horizon must show to earn each confidence
tier, and the caps that missing drivers, stale drivers, a
degraded accuracy record and an unestimable sentiment line
impose. A change to any of it is a new pack version, and every
assessment names the version it was computed under — the
verifier re-performs under exactly that pack.

The tier ladder, as the pack states it (applied per horizon):

1. **Unproven.** No accuracy record stands behind the horizon —
   there is nothing measured to have confidence *in*, whatever
   the coverage looks like.
2. **Base tier** from the measured evidence: the horizon's own
   window coverage, the 365-day history coverage, the record's
   pooled MAPE and band coverage, and the forecast band's width
   against the series' own realised volatility (the band must
   not be implausibly narrow for the series' own history, and
   an extremely wide band is itself thin evidence). Meeting
   every established bar earns ``established``; meeting every
   guarded bar earns ``guarded``; anything else measured is
   ``thin``.
3. **Caps**, applied after the base tier, never raising it: a
   catalogue driver the commodity does not report caps the
   tier at ``guarded``; a stale driver caps it at ``thin``; a
   degraded accuracy record caps it at ``thin``; a sentiment
   line that is not estimable caps it at ``guarded``.

Every reason a horizon did not earn a higher tier rides on the
assessment's face — a tier without its reasons is a padded
number, and this pack exists to refuse padding.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

TIERS: tuple[str, ...] = ("unproven", "thin", "guarded", "established")

TIER_RANK: dict[str, int] = {name: i for i, name in enumerate(TIERS)}

WINDOWS_DAYS: tuple[int, ...] = (7, 30, 90, 365)


class ThinDataPack(BaseModel):
    version: str
    windows_days: list[int] = Field(
        description="The coverage windows judged, in calendar days"
    )
    stale_after_days: int = Field(
        description="A reported driver whose last observation is "
        "more than this many days before as_of is stale"
    )
    sentiment_stale_after_days: int = Field(
        description="The sentiment index's own staleness bar, in "
        "days from the last index week's end to as_of"
    )
    established_window_coverage: float = Field(
        description="Minimum operating-day coverage in the "
        "horizon's own window for the established tier"
    )
    established_history_coverage: float = Field(
        description="Minimum operating-day coverage in the "
        "365-day window for the established tier"
    )
    established_max_mape_pct: float = Field(
        description="Maximum pooled MAPE for the established tier"
    )
    established_min_band_coverage: float = Field(
        description="Minimum realised band coverage in the "
        "accuracy record for the established tier"
    )
    established_ratio_min: float = Field(
        description="Minimum ratio of the forecast band's width "
        "to the realised-volatility width for established"
    )
    established_ratio_max: float = Field(
        description="Maximum such ratio for established"
    )
    guarded_window_coverage: float = Field(
        description="Minimum own-window coverage for guarded"
    )
    guarded_history_coverage: float = Field(
        description="Minimum 365-day coverage for guarded"
    )
    guarded_max_mape_pct: float = Field(
        description="Maximum pooled MAPE for guarded"
    )
    guarded_min_band_coverage: float = Field(
        description="Minimum realised band coverage for guarded"
    )
    guarded_ratio_min: float = Field(
        description="Minimum band-width ratio for guarded"
    )
    guarded_ratio_max: float = Field(
        description="Maximum band-width ratio for guarded"
    )
    band_z: float = Field(
        description="The normal quantile the P10-P90 width is "
        "compared at (1.2816 for a central 80% band)"
    )
    tier_rule: str = Field(
        description="The tier ladder, stated — the engine "
        "performs exactly this"
    )


THIN_DATA_PACK_V1 = ThinDataPack(
    version="2026.10.1",
    windows_days=list(WINDOWS_DAYS),
    stale_after_days=14,
    sentiment_stale_after_days=21,
    established_window_coverage=0.95,
    established_history_coverage=0.90,
    established_max_mape_pct=5.0,
    established_min_band_coverage=0.75,
    established_ratio_min=0.75,
    established_ratio_max=1.75,
    guarded_window_coverage=0.85,
    guarded_history_coverage=0.75,
    guarded_max_mape_pct=7.5,
    guarded_min_band_coverage=0.60,
    guarded_ratio_min=0.55,
    guarded_ratio_max=2.50,
    band_z=1.2815515655446004,
    tier_rule=(
        "Per horizon: unproven when no accuracy record stands "
        "behind it. Otherwise the base tier is established when "
        "own-window coverage, 365-day coverage, pooled MAPE, "
        "band coverage and the band-width ratio against realised "
        "volatility all meet the established bars; guarded when "
        "they all meet the guarded bars; thin otherwise. Caps "
        "then apply, never raising the tier: an unreported "
        "catalogue driver caps at guarded, a stale driver caps "
        "at thin, a degraded record caps at thin, and a "
        "not-estimable sentiment line caps at guarded. Every "
        "failed bar and every applied cap is named as a reason "
        "on the horizon's face."
    ),
)


def load_thin_data_pack(version: str | None = None) -> ThinDataPack:
    """Load the thin-data pack, fail-closed.

    An unknown version is an error, never a silent fallback —
    an assessment computed under one pack must never be
    quietly re-read under another.
    """
    if version is None or version == THIN_DATA_PACK_V1.version:
        return THIN_DATA_PACK_V1
    raise ValueError(f"unknown thin-data pack version: {version!r}")
