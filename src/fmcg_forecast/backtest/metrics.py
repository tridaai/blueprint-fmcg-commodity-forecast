"""Backtest metrics + ledger aggregation — pure computation.

The formulas are stated here and nowhere else:

- a scored day is a forecast day carrying a realised observation;
  days without one (market holidays) are excluded, never imputed;
- per day, ``err = realised - p50``; a day is *covered* when
  ``p10 <= realised <= p90`` — counted exactly, day by day;
- a result's sums are the primitive record (``sum_err``,
  ``sum_abs_err``, ``sum_abs_pct``, ``covered_days``, ``n_days``),
  stored rounded to 6dp; the derived metrics are
  ``mae = sum_abs_err / n``, ``mape = 100 * sum_abs_pct / n``,
  ``bias = sum_err / n``, ``coverage = covered_days / n``, rounded
  to 4dp — always recomputed from the rounded sums, so a verifier
  re-performing from the artefact lands on the same figures;
- the ledger pools the sums of the most recent
  ``ledger_window_origins`` results (by origin date) for one
  series x horizon and derives the record's metrics from the
  pooled sums the same way. ``degraded`` is
  ``mape > degraded_mape_pct`` from the accuracy pack.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from fmcg_forecast.backtest.pack import AccuracyPack
from fmcg_forecast.forecast.models import (
    AccuracyRecord,
    BacktestDay,
    BacktestResult,
    Forecast,
)

SUM_DP = 6
METRIC_DP = 4


def _derive(sum_err: float, sum_abs_err: float, sum_abs_pct: float,
            covered_days: int, n_days: int) -> dict[str, float]:
    if n_days == 0:
        return {"mae": 0.0, "mape": 0.0, "bias": 0.0, "coverage": 0.0}
    return {
        "mae": round(sum_abs_err / n_days, METRIC_DP),
        "mape": round(100.0 * sum_abs_pct / n_days, METRIC_DP),
        "bias": round(sum_err / n_days, METRIC_DP),
        "coverage": round(covered_days / n_days, METRIC_DP),
    }


def score_days(
    days: list[tuple[date, float, float, float]],
    realised: dict[date, float],
) -> tuple[list[BacktestDay], dict[str, float]]:
    """Score (date, p10, p50, p90) rows against realised prices.

    Only days present in ``realised`` are scored. Returns the scored
    day rows and the sums + derived metrics over them.
    """
    scored: list[BacktestDay] = []
    sum_err = sum_abs_err = sum_abs_pct = 0.0
    covered = 0
    for day_date, p10, p50, p90 in days:
        if day_date not in realised:
            continue
        value = realised[day_date]
        err = value - p50
        sum_err += err
        sum_abs_err += abs(err)
        sum_abs_pct += abs(err) / value
        if p10 <= value <= p90:
            covered += 1
        scored.append(
            BacktestDay(
                forecast_date=day_date, p10=p10, p50=p50, p90=p90, realised=value
            )
        )
    sums = {
        "n_days": len(scored),
        "covered_days": covered,
        "sum_err": round(sum_err, SUM_DP),
        "sum_abs_err": round(sum_abs_err, SUM_DP),
        "sum_abs_pct": round(sum_abs_pct, SUM_DP),
    }
    derived = _derive(
        sums["sum_err"], sums["sum_abs_err"], sums["sum_abs_pct"],
        covered, len(scored),
    )
    return scored, {**sums, **derived}


def build_result(
    forecast: Forecast,
    horizon_days: int,
    realised: dict[date, float],
    pack: AccuracyPack,
) -> BacktestResult:
    """Score one engine run at one horizon into a result artefact."""
    rows = [
        (d.forecast_date, d.p10, d.p50, d.p90) for d in forecast.days[:horizon_days]
    ]
    scored, sums = score_days(rows, realised)
    result = BacktestResult(
        result_id="BT-pending",
        commodity=forecast.commodity,
        market=forecast.market,
        origin=forecast.as_of,
        horizon_days=horizon_days,
        forecast_id=forecast.forecast_id,
        engine_version=forecast.engine_version,
        pack_version=pack.version,
        days=scored,
        n_days=sums["n_days"],
        covered_days=sums["covered_days"],
        sum_err=sums["sum_err"],
        sum_abs_err=sums["sum_abs_err"],
        sum_abs_pct=sums["sum_abs_pct"],
        mae=sums["mae"],
        mape=sums["mape"],
        bias=sums["bias"],
        coverage=sums["coverage"],
    )
    result.result_id = result_content_id(result)
    return result


def result_content_id(result: BacktestResult) -> str:
    payload = result.model_dump(mode="json", exclude={"result_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "BT-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]


def aggregate_results(
    results: list[BacktestResult], pack: AccuracyPack
) -> AccuracyRecord:
    """Pool one series x horizon's recent results into a ledger record."""
    if not results:
        raise ValueError("cannot aggregate an empty result set")
    keys = {(r.commodity, r.market, r.horizon_days) for r in results}
    if len(keys) != 1:
        raise ValueError(f"aggregation mixes series/horizons: {sorted(keys)}")
    window = sorted(results, key=lambda r: r.origin)[-pack.ledger_window_origins:]
    sum_err = round(sum(r.sum_err for r in window), SUM_DP)
    sum_abs_err = round(sum(r.sum_abs_err for r in window), SUM_DP)
    sum_abs_pct = round(sum(r.sum_abs_pct for r in window), SUM_DP)
    covered = sum(r.covered_days for r in window)
    n_days = sum(r.n_days for r in window)
    derived = _derive(sum_err, sum_abs_err, sum_abs_pct, covered, n_days)
    first = window[0]
    record = AccuracyRecord(
        record_id="ACC-pending",
        commodity=first.commodity,
        market=first.market,
        horizon_days=first.horizon_days,
        origins=[r.origin for r in window],
        n_results=len(window),
        n_days=n_days,
        covered_days=covered,
        mae=derived["mae"],
        mape=derived["mape"],
        bias=derived["bias"],
        coverage=derived["coverage"],
        engine_version=first.engine_version,
        pack_version=pack.version,
        degraded_threshold_mape_pct=pack.degraded_mape_pct,
        degraded=derived["mape"] > pack.degraded_mape_pct,
    )
    record.record_id = record_content_id(record)
    return record


def record_content_id(record: AccuracyRecord) -> str:
    payload = record.model_dump(mode="json", exclude={"record_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "ACC-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]
