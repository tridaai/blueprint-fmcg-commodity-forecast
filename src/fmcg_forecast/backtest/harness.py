"""The backtest harness: rolling origins in, accuracy ledger out.

One workflow, shared by the API, the demo and the eval gate:

1. **Run** — for every (commodity x market) series in the
   catalogue and every origin in the accuracy pack, run the engine
   at that origin through its ``via_backtest`` seam and score the
   run at each pack horizon against the realised prices in the
   observations table. Origins the engine refuses (a series that
   cannot yet state the method — coffee before mid-2025) are
   recorded as skips with the refusal named. Runs are idempotent:
   results are content-addressed, and a result already on record
   is not re-inserted.
2. **Aggregate** — rebuild the ledger: one accuracy record per
   series x horizon, pooled from the stored results by the pack's
   stated rule, stamped degraded or not against the pack's bar.

Backtest origin runs are harness artefacts: their decompositions
are re-performable from (series, origin) and their content
addresses are recorded on the results as provenance, but they are
not entered in the desk's forecast record — the forecasts table
holds the forecasts a desk actually made.

Sealed boundary: the harness never reads the truth store. The one
boundary check — a forecast at the last history day scored against
the sealed future — is composed by the eval gate, which hands the
truth rows to :func:`score_sealed_boundary`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from fmcg_forecast.backtest import metrics
from fmcg_forecast.backtest.pack import AccuracyPack, load_accuracy_pack
from fmcg_forecast.catalogue import COMMODITIES
from fmcg_forecast.forecast.engine import ForecastError, run_engine
from fmcg_forecast.forecast.models import AccuracyRecord, Forecast
from fmcg_forecast.models import Observation

log = logging.getLogger("fmcg.backtest")


@dataclass
class BacktestRunReport:
    results_stored: int = 0
    results_already_on_record: int = 0
    engine_runs: int = 0
    skipped: list[dict] = field(default_factory=list)


def monthly_origins(pack: AccuracyPack) -> list[date]:
    """The pack's origin grid: first-of-month, start..end inclusive."""
    origins: list[date] = []
    cursor = pack.origins_start
    while cursor <= pack.origins_end:
        origins.append(cursor)
        year, month = (cursor.year, cursor.month + 1) if cursor.month < 12 else (cursor.year + 1, 1)
        cursor = date(year, month, 1)
    return origins


def run_backtests(store, pack: AccuracyPack | None = None) -> BacktestRunReport:
    """Run the pack's grid over observed history; store the results."""
    pack = pack or load_accuracy_pack()
    manifest = store.get_manifest()
    if manifest is None:
        raise ForecastError("dataset not loaded; run the ingest workflow first")
    origins = monthly_origins(pack)
    max_horizon = max(pack.horizons_days)
    report = BacktestRunReport()
    for spec in COMMODITIES:
        for market_spec in spec.markets:
            realised_all = {
                r.obs_date: float(r.value)
                for r in store.series(spec.commodity, market_spec.market, "modal_price")
            }
            for origin in origins:
                try:
                    forecast = run_engine(
                        store, manifest, spec.commodity, market_spec.market,
                        origin, via_backtest=True,
                    )
                except ForecastError as exc:
                    report.skipped.append(
                        {
                            "commodity": spec.commodity,
                            "market": market_spec.market,
                            "origin": origin.isoformat(),
                            "reason": str(exc),
                        }
                    )
                    continue
                report.engine_runs += 1
                realised = {
                    d: v
                    for d, v in realised_all.items()
                    if origin < d <= origin + timedelta(days=max_horizon)
                }
                for horizon in pack.horizons_days:
                    result = metrics.build_result(forecast, horizon, realised, pack)
                    if store.get_backtest_result(result.result_id) is not None:
                        report.results_already_on_record += 1
                        continue
                    store.insert_backtest_result(result)
                    report.results_stored += 1
    log.info(
        "backtests: stored=%s existing=%s engine_runs=%s skipped=%s",
        report.results_stored,
        report.results_already_on_record,
        report.engine_runs,
        len(report.skipped),
    )
    return report


def rebuild_ledger(
    store, pack: AccuracyPack | None = None
) -> list[AccuracyRecord]:
    """Re-perform the ledger from the result artefacts of record."""
    pack = pack or load_accuracy_pack()
    records: list[AccuracyRecord] = []
    for spec in COMMODITIES:
        for market_spec in spec.markets:
            for horizon in pack.horizons_days:
                results = store.list_backtest_results(
                    spec.commodity, market_spec.market, horizon
                )
                if not results:
                    continue
                record = metrics.aggregate_results(results, pack)
                store.save_accuracy_record(record)
                records.append(record)
    return records


def run_all(
    store, pack: AccuracyPack | None = None
) -> tuple[BacktestRunReport, list[AccuracyRecord]]:
    """The full harness workflow: run the grid, then rebuild the ledger."""
    pack = pack or load_accuracy_pack()
    report = run_backtests(store, pack)
    records = rebuild_ledger(store, pack)
    return report, records


def score_sealed_boundary(
    forecast: Forecast, truth_rows: list[Observation]
) -> dict[int, dict]:
    """Score a boundary forecast against rows handed in by a grader.

    Eval-only composition: the caller (the eval gate) reads the
    sealed truth and passes its price rows here; this function —
    and this whole package — never touches the truth store itself.
    Returns the same sums + metrics the harness computes, per
    horizon, unstored.
    """
    realised = {
        r.obs_date: float(r.value) for r in truth_rows if r.driver == "modal_price"
    }
    out: dict[int, dict] = {}
    for horizon in (7, 30, 90):
        rows = [
            (d.forecast_date, d.p10, d.p50, d.p90)
            for d in forecast.days[:horizon]
        ]
        _, sums = metrics.score_days(rows, realised)
        out[horizon] = sums
    return out
