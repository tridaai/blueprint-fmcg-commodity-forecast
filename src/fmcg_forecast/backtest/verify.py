"""Re-performance verification for backtest + ledger artefacts.

Like the forecast verifier, this trusts nothing stored: a result's
sums and metrics are recomputed from its own scored days, a
record's figures are recomputed by re-running the aggregation over
the result artefacts of record, and both content addresses are
recomputed. Tampering with a stored path, a sum or a pooled figure
fails here even if the artefact still parses.
"""

from __future__ import annotations

from fmcg_forecast.backtest import metrics
from fmcg_forecast.backtest.pack import AccuracyPack
from fmcg_forecast.forecast.models import AccuracyRecord, BacktestResult

TOLERANCE = 5e-5  # derived figures are stored rounded to 4dp


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE


def verify_backtest_result(result: BacktestResult) -> list[str]:
    """Return the problems with one stored backtest result."""
    problems: list[str] = []
    if metrics.result_content_id(result) != result.result_id:
        problems.append(
            f"content id mismatch: stored {result.result_id}, recomputed "
            f"{metrics.result_content_id(result)} — the artefact was "
            "altered after the run"
        )
    rows = [(d.forecast_date, d.p10, d.p50, d.p90) for d in result.days]
    realised = {d.forecast_date: d.realised for d in result.days}
    _, sums = metrics.score_days(rows, realised)
    if sums["n_days"] != result.n_days or sums["covered_days"] != result.covered_days:
        problems.append(
            f"day counts do not re-perform: stored n={result.n_days} "
            f"covered={result.covered_days}, recomputed n={sums['n_days']} "
            f"covered={sums['covered_days']}"
        )
    for field in ("sum_err", "sum_abs_err", "sum_abs_pct", "mae", "mape", "bias", "coverage"):
        if not _close(sums[field], getattr(result, field)):
            problems.append(
                f"{field} does not re-perform: stored {getattr(result, field)}, "
                f"recomputed {sums[field]}"
            )
    dates = [d.forecast_date for d in result.days]
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        problems.append("scored days are not a strictly increasing date sequence")
    for day in result.days:
        if not (result.origin < day.forecast_date):
            problems.append(f"scored day {day.forecast_date} is not after the origin")
        if not (day.p10 <= day.p50 <= day.p90):
            problems.append(f"{day.forecast_date}: interval ordering broken")
    return problems


def verify_accuracy_record(
    record: AccuracyRecord,
    results: list[BacktestResult],
    pack: AccuracyPack,
) -> list[str]:
    """Re-perform the ledger aggregation and compare, field by field.

    ``results`` must be every stored result for the record's
    series x horizon; the aggregation itself selects the window.
    """
    problems: list[str] = []
    if metrics.record_content_id(record) != record.record_id:
        problems.append(
            f"content id mismatch: stored {record.record_id}, recomputed "
            f"{metrics.record_content_id(record)} — the record was "
            "altered after the ledger build"
        )
    if record.pack_version != pack.version:
        problems.append(
            f"record was built under pack {record.pack_version}, "
            f"cannot re-perform under {pack.version}"
        )
        return problems
    try:
        expected = metrics.aggregate_results(results, pack)
    except ValueError as exc:
        return problems + [f"aggregation cannot be re-performed: {exc}"]
    for field in (
        "commodity", "market", "horizon_days", "origins", "n_results",
        "n_days", "covered_days", "engine_version", "pack_version",
        "degraded_threshold_mape_pct", "degraded",
    ):
        if getattr(expected, field) != getattr(record, field):
            problems.append(
                f"{field} drifts from the result artefacts: ledger "
                f"{getattr(record, field)}, re-performed {getattr(expected, field)}"
            )
    for field in ("mae", "mape", "bias", "coverage"):
        if not _close(getattr(expected, field), getattr(record, field)):
            problems.append(
                f"{field} drifts from the result artefacts: ledger "
                f"{getattr(record, field)}, re-performed {getattr(expected, field)}"
            )
    if expected.record_id != record.record_id:
        problems.append(
            f"record id drifts: ledger {record.record_id}, "
            f"re-performed {expected.record_id}"
        )
    return problems
