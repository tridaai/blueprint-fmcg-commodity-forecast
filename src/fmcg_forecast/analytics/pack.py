"""The analytics pack — how the desk reads its own track record, as data.

F20-AM1's rules are stated here, versioned, never buried in code:
how an accuracy trend is windowed and judged, how a buy signal's
outcome is measured against what the price actually did, when an
event class's transmission sample is too small to read as
evidence, and which scored days count as a shock window. A change
to any of it is a new pack version, and every ops report names
the version it was computed under — the verifier re-performs
under exactly that pack, alongside the accuracy, signal and
event pack versions the report also names on its face.

Nothing in this pack lets an analytic assert what it did not
measure: a trend over too few origins is named insufficient, a
signal whose horizon has not landed in observed history is
pending and never graded, and a transmission class with a small
measurable sample is named small — anecdote, not evidence.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyticsPack(BaseModel):
    version: str
    trend_window_origins: int = Field(
        description="The trend pools the first and last this-many "
        "backtest results (by origin) of a series x horizon; a "
        "series with fewer than twice this many results has no "
        "trend to state and is named insufficient"
    )
    trend_epsilon_mape_pp: float = Field(
        description="A late-minus-early pooled MAPE delta inside "
        "+/- this many percentage points reads steady; beyond "
        "it, worsening or improving"
    )
    min_class_sample: int = Field(
        description="Minimum measurable events for an event "
        "class's transmission aggregates to read as evidence; "
        "below it the class is named a small sample"
    )
    trend_rule: str = Field(
        description="The accuracy-trend rule, stated — the "
        "engine performs exactly this"
    )
    signal_outcome_rule: str = Field(
        description="The signal-outcome rule, stated — measured "
        "against observed prices, never asserted"
    )
    transmission_rule: str = Field(
        description="The transmission-error rule, stated"
    )
    shock_window_rule: str = Field(
        description="The shock-window grading rule, stated"
    )


ANALYTICS_PACK_V1 = AnalyticsPack(
    version="2026.10.1",
    trend_window_origins=3,
    trend_epsilon_mape_pp=0.25,
    min_class_sample=3,
    trend_rule=(
        "Per series x horizon, over the stored backtest results "
        "by origin: the early window pools the first "
        "trend_window_origins results and the late window the "
        "last trend_window_origins, each pooled by the accuracy "
        "ledger's own rule (error sums pooled, metrics derived "
        "from the pooled sums, day-weighted). Direction is "
        "insufficient_history when the series holds fewer than "
        "twice the window in results; otherwise worsening when "
        "late MAPE minus early MAPE exceeds the pack's epsilon, "
        "improving when it falls short of minus the epsilon, "
        "and steady between. The current ledger record for the "
        "series x horizon rides on the row beside the trend, so "
        "the trend and the ledger of record can be read together."
    ),
    signal_outcome_rule=(
        "A signal is graded only when its horizon has landed in "
        "observed history: the realised price is the last "
        "observed modal price in (as_of, as_of + horizon_days], "
        "and realised drift is (realised - spot) / spot x 100 "
        "against the spot the signal itself pinned. The move is "
        "rose when realised drift reaches the signal pack's rise "
        "bar, fell when it reaches the fall bar, and flat "
        "between. A call is favourable when the move vindicates "
        "it under this stated rule: buy_now needs rose (the desk "
        "committed early and needed the rise); phased needs rose "
        "or flat (a fall past the fall bar means even the first "
        "tranche overpaid against waiting outright); wait needs "
        "fell or flat (waiting cost the desk nothing unless the "
        "price rose past the bar). A signal whose horizon has "
        "not landed — no observation inside its window — is "
        "pending: named with the reason, never graded. Grid "
        "outcomes are struck from raw engine runs at the "
        "accuracy pack's origins (the harness's basis) with the "
        "accuracy attachment pooled from earlier origins only, "
        "so no outcome is judged with knowledge its origin did "
        "not have."
    ),
    transmission_rule=(
        "Per event class, every registered event is measured by "
        "the events layer's seasonally-matched measurement. An "
        "event the measurement names not_measurable is excluded "
        "from the aggregates and named. Over the measurable "
        "events: the signed error is measured minus claimed log "
        "effect per event; the class carries the mean signed "
        "error, the mean absolute error, the mean ratio to "
        "claim and the verified/unverified counts. A class with "
        "fewer measurable events than the pack's minimum sample "
        "is named small_sample on its face — its aggregates are "
        "printed, and read as anecdote, not evidence; a class "
        "with none is named no_measurable_events."
    ),
    shock_window_rule=(
        "A scored day is a shock day for an event when it falls "
        "inside the event's window extended by its stated decay "
        "tail: window_start .. window_end + decay_days, or from "
        "window_start through the series' last observed day "
        "while the window is open-ended. Per event x market x "
        "horizon, the shock pool is every scored day of the "
        "series' stored results inside the window and the rest "
        "pool every scored day outside it; both pools derive "
        "their metrics from the pooled day rows by the backtest "
        "metrics' own formulas. A row with no shock days is "
        "named no_shock_window_days — the grid never graded "
        "this event — and a row with no rest days is named "
        "no_baseline_days; neither is presented as a grade."
    ),
)


def load_analytics_pack(version: str | None = None) -> AnalyticsPack:
    """Load the analytics pack, fail-closed.

    An unknown version is an error, never a silent fallback —
    a report computed under one pack must never be quietly
    re-read under another.
    """
    if version is None or version == ANALYTICS_PACK_V1.version:
        return ANALYTICS_PACK_V1
    raise ValueError(f"unknown analytics pack version: {version!r}")
