"""The monitoring engine: pure folds over records,
batches and the registry.

Every figure a board carries is computed here, from the
artefacts alone, under the monitoring pack — the service
strikes what this module computes and the verifier
recomputes it the same way. Three folds:

- **pricing**: estimated tokens from a character count
  by the pack's stated estimator (ceil(chars / 4) over
  the canonical payload), and a cost from token counts
  by the profile's reference rate — exact integer
  arithmetic in nano-USD, the multiplication done
  before the division so nothing is rounded twice, and
  None for an unrated profile, never zero;
- **usage**: run records grouped by (profile, purpose),
  counts and token sums exact, each row's cost the exact
  sum of its records' costs (None when the row's profile
  is unrated);
- **freshness**: per registered source, the batches at
  or before the board's as-of folded into job totals,
  and the last LOADED batch judged against the pack's
  window for the source's cadence. A refused batch is
  job history, not freshness: a feed whose latest
  delivery was refused whole has not fed the store, and
  its freshness still reads from its last loaded batch.
  A cadence the pack states no window for (a one-off
  bootstrap) reads one_off — it owes nothing and can
  breach nothing.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from fmcg_forecast.ingest.models import IngestBatch, SourceRegistration
from fmcg_forecast.monitoring.models import (
    FreshnessRow,
    MonitoringBoard,
    RunRecord,
    UsageRow,
    board_content_id,
)
from fmcg_forecast.monitoring.pack import (
    COST_BASIS_RATED,
    COST_BASIS_UNRATED,
    MonitoringPack,
    rate_for,
    window_for,
)


def estimate_tokens(chars: int, pack: MonitoringPack) -> int:
    """The pack's stated estimator: ceil(chars / chars_per_token)."""
    if chars <= 0:
        return 0
    return math.ceil(chars / pack.chars_per_token)


def price_call(
    profile: str,
    request_tokens: int,
    response_tokens: int,
    pack: MonitoringPack,
) -> tuple[int | None, str]:
    """Price one call: (cost nano-USD, basis).

    An unrated or unknown profile prices as None under
    the unrated basis — the ledger never invents a rate
    the pack does not state. Rated arithmetic is exact:
    tokens x rate-per-million, summed over request and
    response, divided once by a million.
    """
    rate = rate_for(pack, profile)
    if rate is None or not rate.rated:
        return None, COST_BASIS_UNRATED
    nano = (
        request_tokens * rate.input_nano_usd_per_million
        + response_tokens * rate.output_nano_usd_per_million
    ) / 1_000_000
    return int(round(nano)), COST_BASIS_RATED


def build_usage(records: list[RunRecord], pack: MonitoringPack) -> list[UsageRow]:
    """Fold run records into profile x purpose rows."""
    grouped: dict[tuple[str, str], list[RunRecord]] = {}
    for record in records:
        grouped.setdefault((record.profile, record.purpose), []).append(record)
    rows: list[UsageRow] = []
    for (profile, purpose), calls in sorted(grouped.items()):
        rate = rate_for(pack, profile)
        rated = rate is not None and rate.rated
        rows.append(
            UsageRow(
                profile=profile,
                purpose=purpose,
                n_calls=len(calls),
                request_tokens=sum(c.request_tokens for c in calls),
                response_tokens=sum(c.response_tokens for c in calls),
                cost_nano_usd=(
                    sum(c.cost_nano_usd or 0 for c in calls) if rated else None
                ),
            )
        )
    return rows


def _aware(moment: datetime) -> datetime:
    """Read a stored instant as UTC when it carries no zone.

    Artefacts struck by earlier rounds may carry naive
    datetimes (the demo's ingest beats among them); the
    fold reads them as UTC rather than refusing to
    compare them against a stated as-of.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _age_hours(last: datetime, as_of: datetime) -> float:
    return round(
        (_aware(as_of) - _aware(last)).total_seconds() / 3600.0, 1
    )


def build_freshness_row(
    source: SourceRegistration,
    batches: list[IngestBatch],
    as_of: datetime,
    pack: MonitoringPack,
) -> FreshnessRow:
    """One source's job totals and freshness verdict at an as-of.

    ``batches`` is every batch on record for the source;
    the fold itself applies the as-of, so a board never
    reads a batch that had not arrived when it was struck.
    """
    window = window_for(pack, source.cadence)
    max_age = window.max_age_hours if window else None
    mine = sorted(
        (
            b
            for b in batches
            if b.source_id == source.source_id
            and _aware(b.received_at) <= _aware(as_of)
        ),
        key=lambda b: (_aware(b.received_at), b.batch_id),
    )
    loaded = [b for b in mine if b.status == "loaded"]
    totals = dict(
        n_batches=len(mine),
        n_refused=sum(1 for b in mine if b.status == "refused"),
        rows_received=sum(b.rows_received for b in mine),
        rows_loaded=sum(b.rows_loaded for b in mine),
        rows_quarantined=sum(b.rows_quarantined for b in mine),
    )
    if not loaded:
        if max_age is None and window is not None:
            state, note = (
                "one_off",
                "a one-off source: it owes no window, and no "
                "batch has loaded under it yet",
            )
        else:
            state, note = (
                "never_loaded",
                "no batch has ever loaded from this source — "
                "named here because an absent feed must read "
                "as a gap, not as silence",
            )
        return FreshnessRow(
            source_id=source.source_id,
            display=source.display,
            owner=source.owner,
            cadence=source.cadence,
            state=state,
            max_age_hours=max_age,
            last_batch_id=None,
            last_received_at=None,
            last_as_of=None,
            age_hours=None,
            note=note,
            **totals,
        )
    last = loaded[-1]
    age = _age_hours(last.received_at, as_of)
    if max_age is None and window is None:
        state = "one_off"
        note = (
            f"the pack states no freshness window for cadence "
            f"{source.cadence!r} — the source owes nothing the "
            f"board can judge; its last loaded batch landed "
            f"{age} hours before the board's as-of"
        )
    elif max_age is None:
        state = "one_off"
        note = (
            "a one-off source: it owes no window; its last "
            f"loaded batch landed {age} hours before the "
            "board's as-of"
        )
    elif age <= max_age:
        state = "fresh"
        note = (
            f"last loaded batch is {age} hours old, inside "
            f"the {max_age}-hour window its cadence is owed"
        )
    else:
        state = "late"
        note = (
            f"BREACH: last loaded batch is {age} hours old, "
            f"past the {max_age}-hour window its cadence is "
            f"owed — the feed owned by {source.owner} is late"
        )
    return FreshnessRow(
        source_id=source.source_id,
        display=source.display,
        owner=source.owner,
        cadence=source.cadence,
        state=state,
        max_age_hours=max_age,
        last_batch_id=last.batch_id,
        last_received_at=last.received_at,
        last_as_of=last.as_of,
        age_hours=age,
        note=note,
        **totals,
    )


def build_board(
    *,
    struck_at: datetime,
    records: list[RunRecord],
    registrations: list[SourceRegistration],
    batches: list[IngestBatch],
    ingest_pack_version: str,
    pack: MonitoringPack,
) -> MonitoringBoard:
    """Strike a board: the folds, and nothing authored."""
    folded_records = sorted(
        (r for r in records if _aware(r.called_at) <= _aware(struck_at)),
        key=lambda r: (_aware(r.called_at), r.run_id),
    )
    usage = build_usage(folded_records, pack)
    rated_calls = sum(
        1 for r in folded_records if r.cost_basis == COST_BASIS_RATED
    )
    freshness = [
        build_freshness_row(source, batches, struck_at, pack)
        for source in sorted(registrations, key=lambda s: s.source_id)
    ]
    board = MonitoringBoard(
        board_id="",
        struck_at=struck_at,
        monitoring_pack_version=pack.version,
        ingest_pack_version=ingest_pack_version,
        usage=usage,
        total_calls=len(folded_records),
        total_request_tokens=sum(r.request_tokens for r in folded_records),
        total_response_tokens=sum(r.response_tokens for r in folded_records),
        rated_calls=rated_calls,
        unrated_calls=len(folded_records) - rated_calls,
        total_cost_nano_usd=sum(
            r.cost_nano_usd or 0
            for r in folded_records
            if r.cost_basis == COST_BASIS_RATED
        ),
        freshness=freshness,
        breaches=[row.source_id for row in freshness if row.state == "late"],
        never_loaded=[
            row.source_id for row in freshness if row.state == "never_loaded"
        ],
    )
    return board.model_copy(update={"board_id": board_content_id(board)})
