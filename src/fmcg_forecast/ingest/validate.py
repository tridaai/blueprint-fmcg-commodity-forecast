"""The one validation path every connector row travels.

A pure judgement: candidate row + the source it arrived
under + the batch's as-of + the pack → the pack reasons that
apply, in pack order. It touches no store, so the service and
the verifier run the identical judgement — the service to
decide a live batch, the verifier to re-perform a stored one
from the stored rows alone.

Checks cascade: a check is only evaluated when its inputs are
legible. An empty commodity is a malformed row, not also an
unknown one; a value that does not parse is malformed, not
also out of range. A planted bad row therefore trips exactly
the reasons it was planted to trip.

The two store-shaped reasons — an in-batch key conflict and a
conflict with an already-landed fact — are not judged here;
they need the batch and the store, and the service and
verifier each apply them over this function's verdicts.
"""

from __future__ import annotations

from datetime import date

from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.ingest.models import CandidateRow, SourceRegistration
from fmcg_forecast.ingest.pack import IngestPack


def judge_row(
    row: CandidateRow,
    *,
    source: SourceRegistration,
    as_of: date,
    pack: IngestPack,
    row_provenance_required: bool,
) -> list[str]:
    reasons: set[str] = set()

    parsed_date = row.parsed_date()
    parsed_value = row.parsed_value()
    if (
        not row.commodity.strip()
        or not row.market.strip()
        or not row.driver.strip()
        or not row.unit.strip()
        or parsed_date is None
        or parsed_value is None
    ):
        reasons.add("malformed_row")

    if row_provenance_required:
        if (
            not row.source_text.strip()
            or not row.as_of_text.strip()
            or row.source_text.strip() != source.source_id
            or row.as_of_text.strip() != as_of.isoformat()
        ):
            reasons.add("missing_provenance")

    spec = BY_NAME.get(row.commodity.strip())
    if row.commodity.strip() and spec is None:
        reasons.add("unknown_commodity")
    if spec is not None and row.market.strip():
        if row.market.strip() not in {m.market for m in spec.markets}:
            reasons.add("unknown_market")
    if spec is not None and row.driver.strip():
        if row.driver.strip() not in spec.drivers:
            reasons.add("driver_not_reported")
    if row.driver.strip() and row.driver.strip() not in source.drivers:
        reasons.add("driver_not_covered")

    if parsed_date is not None and parsed_date > as_of:
        reasons.add("future_date")

    rule = next(
        (r for r in pack.value_rules if r.driver == row.driver.strip()),
        None,
    )
    if parsed_value is not None and rule is not None:
        below = (
            parsed_value <= rule.min_value
            if rule.min_exclusive
            else parsed_value < rule.min_value
        )
        if below or parsed_value > rule.max_value:
            reasons.add("value_out_of_range")

    return [r for r in pack.quarantine_reasons if r in reasons]
