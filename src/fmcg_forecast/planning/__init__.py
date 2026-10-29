"""Coverage & exposure planning (R8, F20-PO3).

The desk states its own requirement — tonnes by month, per
commodity — and that statement is an artefact of a different
kind from everything else in this repo: it is not market data.
Plans are labelled desk-entered on every surface, and their
lineage terminates at a terminal fact class of its own
(``desk_entered``), never at an observation series — the R7
provenance walks keep the two apart by construction, and the
eval gate fails if a desk figure ever appears in market
provenance or a market figure ever terminates at the desk.

Against a plan, the planner computes — in code, re-performed by
its verifier — coverage days from the desk's stated opening
stock, the uncovered tonnes month by month, and the exposure
those tonnes carry at pinned forecast prices, plus the pack's
stated purchase options ranked only by the pack's stated
criteria. Where the desk has adopted a scenario (R6), an
assessment may price on the adopted fork instead: pinned,
badged scenario-based, never blended with the official view.
"""

from __future__ import annotations
