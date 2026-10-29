"""The signal pack — what decides a buy window, as data.

Every threshold that turns a forecast into a buy-window call is
stated here, versioned, never buried in code: the horizon the
call is judged at, the rise/fall bars the 30-day path must clear
against spot, the band width beyond which a single commitment is
too exposed, and the caps the accuracy state imposes. A change
to any of it is a new pack version, and every signal names the
version it was computed under — the verifier re-performs under
exactly that pack.

The decision table, as the pack states it (applied in order):

1. **Base call** from the pinned path. Let ``drift`` be the
   horizon P50 against the last observed modal price (spot), in
   percent, and ``band`` the horizon band width (P90 − P10) as a
   percent of P50.
   - ``drift ≥ rise bar`` and ``band < wide-band bar`` →
     ``buy_now``: the path is rising and the band is narrow
     enough to commit.
   - ``drift ≥ rise bar`` and ``band ≥ wide-band bar`` →
     ``phased``: rising, but the band is too wide for one
     commitment — buy in tranches.
   - ``drift ≤ fall bar`` → ``wait``: the path is falling; buy
     later and cheaper.
   - Otherwise, if a declared event with a positive claimed peak
     overlaps the horizon → ``phased``: phase in ahead of a
     named upward shock rather than chase it.
   - Otherwise, if ``band ≥ wide-band bar`` → ``phased``: a flat
     path under a wide band argues for tranches, not a single
     commitment.
   - Otherwise → ``wait``: a flat path in a narrow band gives no
     reason to buy ahead.
2. **Accuracy caps**, applied after the base call, in this
   order. A ``buy_now`` under a degraded accuracy attachment is
   capped to ``phased`` — a series whose measured error already
   breached the backtest pack's degraded bar never earns a
   strong buy. An unmeasured series (no attachment, or the
   attachment states unmeasured) is capped the same way: the
   desk has not earned the right to call it strong. Caps never
   strengthen a call and never touch ``wait``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

SIGNAL_VALUES: tuple[str, ...] = ("buy_now", "phased", "wait")

SCOPE_NOTE = (
    "signal only — no trade is placed; procurement execution is "
    "out of scope by design"
)


class SignalPack(BaseModel):
    version: str
    horizon_days: int = Field(
        description="The forecast horizon the call is judged at"
    )
    rise_threshold_pct: float = Field(
        description="Drift at or above this percent earns a rising call"
    )
    fall_threshold_pct: float = Field(
        description="Drift at or below this percent earns a wait call"
    )
    wide_band_threshold_pct: float = Field(
        description="Band width (P90-P10 as % of P50) at or above "
        "which one commitment is too exposed"
    )
    degraded_cap: str = Field(
        description="The strongest call a degraded series may carry"
    )
    unmeasured_cap: str = Field(
        description="The strongest call an unmeasured series may carry"
    )
    decision_table: str = Field(
        description="The base-call table, stated — the engine "
        "performs exactly this, in this order"
    )
    cap_rule: str = Field(
        description="The accuracy-cap rule, stated — applied after "
        "the base call, never strengthening"
    )


SIGNAL_PACK_V1 = SignalPack(
    version="2026.10.1",
    horizon_days=30,
    rise_threshold_pct=2.0,
    fall_threshold_pct=-2.0,
    wide_band_threshold_pct=25.0,
    degraded_cap="phased",
    unmeasured_cap="phased",
    decision_table=(
        "drift = (P50 at the horizon - spot) / spot * 100, band = "
        "(P90 - P10) / P50 * 100 at the horizon. In order: drift "
        ">= rise bar and band < wide-band bar -> buy_now; drift "
        ">= rise bar and band >= wide-band bar -> phased; drift "
        "<= fall bar -> wait; a declared event with a positive "
        "claimed peak overlapping the horizon -> phased; band >= "
        "wide-band bar -> phased; otherwise wait."
    ),
    cap_rule=(
        "After the base call: a buy_now whose pinned accuracy "
        "state is degraded is capped to the pack's degraded cap; "
        "a buy_now whose accuracy is unmeasured (or absent) is "
        "capped to the pack's unmeasured cap. Caps are recorded "
        "on the signal's face and never strengthen a call."
    ),
)


def load_signal_pack(version: str | None = None) -> SignalPack:
    """Load the signal pack, fail-closed.

    An unknown version is an error, never a silent fallback — a
    signal computed under one pack must never be quietly re-read
    under another.
    """
    if version is None or version == SIGNAL_PACK_V1.version:
        return SIGNAL_PACK_V1
    raise ValueError(f"unknown signal pack version: {version!r}")
