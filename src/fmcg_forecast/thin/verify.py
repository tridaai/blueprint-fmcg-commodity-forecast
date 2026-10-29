"""Re-performance verification for thin-data assessments.

The verifier trusts nothing stored. It recomputes the content
address, resolves the pinned forecast and every accuracy
record the tiers rest on, checks the forecast's pinned slices
against the ledger records of record, and then re-performs the
whole assessment from the store under the assessment's own
pack version and compares it field for field. A stored tier
above the re-performed tier is named for what it is: an
overstatement — a claim of confidence the series has not
earned.
"""

from __future__ import annotations

from fmcg_forecast.thin.engine import compute_assessment
from fmcg_forecast.thin.models import ThinAssessment, assessment_content_id
from fmcg_forecast.thin.pack import TIER_RANK, load_thin_data_pack
from fmcg_forecast.store import Store


def verify_assessment(store: Store, assessment: ThinAssessment) -> list[str]:
    problems: list[str] = []
    if assessment_content_id(assessment) != assessment.assessment_id:
        problems.append(
            f"content id mismatch: stored {assessment.assessment_id}, "
            f"recomputed {assessment_content_id(assessment)} — the "
            "artefact was altered after computation"
        )
    try:
        pack = load_thin_data_pack(assessment.pack_version)
    except ValueError as exc:
        problems.append(str(exc))
        return problems
    forecast = store.get_forecast(assessment.forecast_id)
    if forecast is None:
        problems.append(
            f"orphan assessment: pinned forecast {assessment.forecast_id} "
            "is not in the store — an assessment without its forecast "
            "cannot exist"
        )
        return problems
    if (forecast.commodity, forecast.market, forecast.as_of) != (
        assessment.commodity,
        assessment.market,
        assessment.as_of,
    ):
        problems.append(
            "pin mismatch: the assessment's series/as_of do not match "
            "the pinned forecast"
        )
    slices = {}
    if forecast.accuracy is not None:
        slices = {s.horizon_days: s for s in forecast.accuracy.per_horizon}
    for horizon in assessment.horizons:
        record_id = assessment.accuracy_record_ids.get(str(horizon.horizon_days))
        if record_id != horizon.accuracy_record_id:
            problems.append(
                f"horizon {horizon.horizon_days}: the record map names "
                f"{record_id} but the horizon names "
                f"{horizon.accuracy_record_id}"
            )
        slice_ = slices.get(horizon.horizon_days)
        if (slice_.record_id if slice_ is not None else None) != record_id:
            problems.append(
                f"horizon {horizon.horizon_days}: the forecast's pinned "
                f"slice rests on {slice_.record_id if slice_ is not None else None}, "
                f"not the assessment's {record_id}"
            )
        if record_id is not None:
            record = store.get_accuracy_record(
                assessment.commodity, assessment.market, horizon.horizon_days
            )
            if record is None or record.record_id != record_id:
                problems.append(
                    f"horizon {horizon.horizon_days}: accuracy record "
                    f"{record_id} does not resolve in the ledger"
                )
            elif slice_ is not None and (
                record.mape != slice_.mape or record.coverage != slice_.coverage
            ):
                problems.append(
                    f"horizon {horizon.horizon_days}: the pinned slice's "
                    "figures do not match the ledger record of record"
                )
    try:
        recomputed = compute_assessment(store, forecast, pack)
    except Exception as exc:  # the recompute itself refused
        problems.append(f"re-performance refused: {exc}")
        return problems
    stored_horizons = {h.horizon_days: h for h in assessment.horizons}
    for fresh in recomputed.horizons:
        stored = stored_horizons.get(fresh.horizon_days)
        if stored is None:
            problems.append(f"horizon {fresh.horizon_days}: missing from the stored assessment")
            continue
        if TIER_RANK[stored.tier] > TIER_RANK[fresh.tier]:
            problems.append(
                f"tier overstatement at the {fresh.horizon_days}-day "
                f"horizon: stored tier {stored.tier} claims confidence "
                f"the series has not earned — re-performance earns "
                f"{fresh.tier}"
            )
    if recomputed.model_dump(
        mode="json", exclude={"assessment_id"}
    ) != assessment.model_dump(mode="json", exclude={"assessment_id"}):
        problems.append(
            "re-performance mismatch: the stored assessment does not "
            "equal a fresh computation from the store and the pinned "
            "forecast, field for field"
        )
    return problems


def verify_tier_claim(
    store: Store, assessment: ThinAssessment, horizon_days: int, claimed_tier: str
) -> list[str]:
    """Grade one claim: a surface stating ``claimed_tier`` for
    this assessment's horizon. A claim above the earned tier is
    a contradiction, named."""
    if claimed_tier not in TIER_RANK:
        return [f"unknown tier {claimed_tier!r} — the pack's ladder is {', '.join(TIER_RANK)}"]
    horizon = next(
        (h for h in assessment.horizons if h.horizon_days == horizon_days), None
    )
    if horizon is None:
        return [f"the assessment carries no {horizon_days}-day horizon"]
    if TIER_RANK[claimed_tier] > TIER_RANK[horizon.tier]:
        return [
            f"tier overstatement: the claim states {claimed_tier} at "
            f"the {horizon_days}-day horizon, but the assessment "
            f"earns {horizon.tier} — a claim of confidence the "
            "series has not earned"
        ]
    return []
