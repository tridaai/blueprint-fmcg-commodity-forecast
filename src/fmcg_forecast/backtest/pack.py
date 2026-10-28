"""The accuracy pack — the backtest grid and the ledger rules, as data.

Law 2's numbers are stated here, versioned, never buried in code:
which origins the harness runs, which horizons it scores, how many
recent origins the ledger pools, and the MAPE bar a series must
stay under to avoid the degraded flag. A change to any of these is
a new pack version, and every result and record carries the
version it was built under.

The grid is deliberately bounded: monthly origins through 2025
(the last origin whose 90-day realised path still lands inside
observed history), three horizons, every catalogue series —
135 engine runs, 405 scored results. Coffee, the thin-data series,
cannot state the engine's method until mid-2025 (it needs 250
reporting days), so its early origins are recorded as skips with
the refusal named, never silently dropped from the grid.

The degraded bar — pooled MAPE above 5.0% — is the desk's stated
accuracy standard. On the planted dataset it separates exactly the
noisiest series (chili at Guntur, over its planted drought: 5.16%
at 30 days, 5.06% at 90) from the rest of the book (next worst:
4.76%).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class AccuracyPack(BaseModel):
    version: str
    origin_rule: str = Field(description="How origins are enumerated")
    origins_start: date
    origins_end: date
    horizons_days: list[int]
    ledger_window_origins: int = Field(
        description="The ledger pools the most recent N origins per "
        "series x horizon"
    )
    degraded_mape_pct: float = Field(
        description="A series x horizon whose pooled MAPE exceeds this "
        "is stamped degraded on its accuracy record"
    )
    aggregation: str = Field(description="The ledger aggregation rule, stated")


ACCURACY_PACK_V1 = AccuracyPack(
    version="2026.10.1",
    origin_rule="first-of-month",
    origins_start=date(2025, 1, 1),
    origins_end=date(2025, 10, 1),
    horizons_days=[7, 30, 90],
    ledger_window_origins=6,
    degraded_mape_pct=5.0,
    aggregation=(
        "pool the error sums of the most recent ledger_window_origins "
        "results by origin; metrics derive from the pooled sums "
        "(day-weighted, never a mean of per-origin means)"
    ),
)


def load_accuracy_pack(version: str | None = None) -> AccuracyPack:
    """Fail-closed loader: only the shipped pack exists in R3.

    An unknown version is an error, never a silent fallback — a
    result must name the pack it was actually scored under.
    """
    if version is None or version == ACCURACY_PACK_V1.version:
        return ACCURACY_PACK_V1
    raise ValueError(f"unknown accuracy pack version: {version!r}")
