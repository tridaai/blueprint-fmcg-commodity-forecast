"""Buy-window signals (R8, F20-PO2).

One series, one computed call — ``buy_now`` / ``phased`` /
``wait`` — derived in code from the series' pinned head forecast
under the versioned signal pack: the 30-day path against spot,
the interval width, the pinned accuracy state and the declared
events whose windows overlap the horizon. The reasoning lines
ride on the signal's face — which inputs, which thresholds, what
decided it — and the verifier re-performs the whole computation
from the forecast artefact and the store, so a signal cannot
drift from what decided it.

The hard rules live in the pack and are graded by the eval gate:
a degraded series never produces a strong buy (its cap is stated
in the pack), an unmeasured series is capped the same way, and a
series inside a declared shock window carries that event named
on the signal. A signal is advice-shaped arithmetic only — no
trade is ever placed; procurement execution is out of scope by
design, and every artefact says so.

Truth isolation (as everywhere in this repo): this package reads
observations and artefacts through the store port only — never
the truth store.
"""
