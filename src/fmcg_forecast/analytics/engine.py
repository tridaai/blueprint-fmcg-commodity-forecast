"""The analytics engine — the track record, computed in code.

Pure computation over the artefacts of record, in four sections:

- **Trends** pool the stored backtest results by the accuracy
  ledger's own pooling (error sums pooled, metrics derived from
  the pooled sums) — the early window against the late window,
  never a mean of per-origin means.
- **Signal outcomes** strike the signal the desk would have seen
  at each accuracy-grid origin — a raw engine run (the harness's
  basis) carrying the accuracy attachment pooled from earlier
  origins only — and grade it, and every stored desk signal,
  against the last observed price inside its horizon. A horizon
  that has not landed is pending, named, never graded.
- **Transmission error** reads the events layer's own
  seasonally-matched measurement per registered event and
  aggregates per class, with the sample size on the face.
- **Shock windows** split each series x horizon's stored scored
  days at the event's window (plus its decay tail) and pool
  both sides by the backtest metrics' own day formulas.

Nothing here narrates a number it did not compute, and nothing
reads the sealed truth: realised prices are observed history,
the same rows every other surface reads.
"""

from __future__ import annotations

from datetime import timedelta

from fmcg_forecast.analytics.models import (
    AccuracyTrendRow,
    OpsReport,
    OriginSignalSkip,
    ShockWindowRow,
    SignalOutcomeRow,
    TransmissionClassRow,
    report_content_id,
)
from fmcg_forecast.analytics.pack import AnalyticsPack, load_analytics_pack
from fmcg_forecast.backtest import metrics
from fmcg_forecast.backtest.harness import monthly_origins
from fmcg_forecast.backtest.pack import AccuracyPack, load_accuracy_pack
from fmcg_forecast.catalogue import BY_NAME, COMMODITIES
from fmcg_forecast.events.measure import measure_event_effect
from fmcg_forecast.events.models import EVENT_CLASSES
from fmcg_forecast.events.pack import EventPack, load_event_pack
from fmcg_forecast.forecast.engine import (
    ForecastError,
    forecast_content_id,
    run_engine,
)
from fmcg_forecast.forecast.models import (
    AccuracyAttachment,
    BacktestResult,
    HorizonAccuracy,
)
from fmcg_forecast.signals.engine import compute_signal
from fmcg_forecast.signals.models import BuySignal
from fmcg_forecast.signals.pack import SignalPack, load_signal_pack
from fmcg_forecast.store import Store


class AnalyticsError(RuntimeError):
    """The ops report cannot be computed from the store as it stands."""


# --- pooling ---------------------------------------------------------------


def _pool_results(results: list[BacktestResult]) -> dict:
    """Pool stored results by the ledger's rule: sums, then derive."""
    sum_err = round(sum(r.sum_err for r in results), metrics.SUM_DP)
    sum_abs_err = round(sum(r.sum_abs_err for r in results), metrics.SUM_DP)
    sum_abs_pct = round(sum(r.sum_abs_pct for r in results), metrics.SUM_DP)
    covered = sum(r.covered_days for r in results)
    n_days = sum(r.n_days for r in results)
    derived = metrics._derive(sum_err, sum_abs_err, sum_abs_pct, covered, n_days)
    return {"n_days": n_days, "covered_days": covered, **derived}


def _pool_days(results: list[BacktestResult], keep) -> dict:
    """Pool the scored days of ``results`` selected by ``keep(date)``.

    The day rows on the result artefacts are the primitive
    record; the metrics are re-derived from them by the
    backtest metrics' own scoring, so a shock pool and the
    ledger can never disagree about a day's error.
    """
    rows = []
    realised = {}
    for result in results:
        for day in result.days:
            if keep(day.forecast_date):
                rows.append((day.forecast_date, day.p10, day.p50, day.p90))
                realised[day.forecast_date] = day.realised
    _, sums = metrics.score_days(rows, realised)
    return sums


# --- accuracy trends ---------------------------------------------------------


def _trend_row(
    store: Store,
    commodity: str,
    market: str,
    horizon_days: int,
    pack: AnalyticsPack,
) -> AccuracyTrendRow:
    results = sorted(
        store.list_backtest_results(commodity, market, horizon_days),
        key=lambda r: r.origin,
    )
    record = store.get_accuracy_record(commodity, market, horizon_days)
    base = {
        "commodity": commodity,
        "market": market,
        "horizon_days": horizon_days,
        "n_results": len(results),
        "origins": [r.origin for r in results],
        "ledger_record_id": record.record_id if record else None,
        "ledger_mape": record.mape if record else None,
        "ledger_degraded": record.degraded if record else None,
    }
    window = pack.trend_window_origins
    if len(results) < 2 * window:
        return AccuracyTrendRow(
            **base,
            early_origins=[],
            late_origins=[],
            early_mape=None,
            late_mape=None,
            early_coverage=None,
            late_coverage=None,
            delta_mape_pp=None,
            delta_coverage=None,
            direction="insufficient_history",
            reason=(
                f"{len(results)} stored result(s) — the trend "
                f"needs at least {2 * window} (two windows of "
                f"{window}) before early and late can be told "
                "apart; the series' history is named insufficient "
                "rather than a trend being asserted over it"
            ),
        )
    early = _pool_results(results[:window])
    late = _pool_results(results[-window:])
    delta_mape = round(late["mape"] - early["mape"], metrics.METRIC_DP)
    delta_cov = round(late["coverage"] - early["coverage"], metrics.METRIC_DP)
    if delta_mape > pack.trend_epsilon_mape_pp:
        direction = "worsening"
        reading = "beyond the pack's epsilon — the series is getting less accurate"
    elif delta_mape < -pack.trend_epsilon_mape_pp:
        direction = "improving"
        reading = "beyond the pack's epsilon — the series is getting more accurate"
    else:
        direction = "steady"
        reading = "inside the pack's epsilon — no trend the evidence separates from noise"
    return AccuracyTrendRow(
        **base,
        early_origins=[r.origin for r in results[:window]],
        late_origins=[r.origin for r in results[-window:]],
        early_mape=early["mape"],
        late_mape=late["mape"],
        early_coverage=early["coverage"],
        late_coverage=late["coverage"],
        delta_mape_pp=delta_mape,
        delta_coverage=delta_cov,
        direction=direction,  # type: ignore[arg-type]
        reason=(
            f"late pooled MAPE {late['mape']}% against early "
            f"{early['mape']}% (delta {delta_mape:+.4f} pp) reads "
            f"{direction}: {reading}"
        ),
    )


# --- signal outcomes ---------------------------------------------------------


def _asof_attachment(
    store: Store, commodity: str, market: str, origin, accuracy_pack: AccuracyPack
) -> AccuracyAttachment:
    """The accuracy attachment as of ``origin``: earlier origins only.

    Mirrors the forecast service's attachment, but the pool for
    each horizon is the stored results with origin strictly
    before this one — a signal struck at an origin is judged
    with exactly the track record that stood when it was struck,
    never with the future it was predicting.
    """
    per_horizon: list[HorizonAccuracy] = []
    pack_version: str | None = None
    threshold: float | None = None
    for horizon in accuracy_pack.horizons_days:
        prior = [
            r
            for r in store.list_backtest_results(commodity, market, horizon)
            if r.origin < origin
        ]
        if not prior:
            per_horizon.append(
                HorizonAccuracy(
                    horizon_days=horizon,
                    state="unmeasured",
                    record_id=None,
                    n_origins=0,
                    mae=None,
                    mape=None,
                    bias=None,
                    coverage=None,
                )
            )
            continue
        record = metrics.aggregate_results(
            sorted(prior, key=lambda r: r.origin), accuracy_pack
        )
        pack_version = record.pack_version
        threshold = record.degraded_threshold_mape_pct
        per_horizon.append(
            HorizonAccuracy(
                horizon_days=horizon,
                state="degraded" if record.degraded else "measured",
                record_id=record.record_id,
                n_origins=record.n_results,
                mae=record.mae,
                mape=record.mape,
                bias=record.bias,
                coverage=record.coverage,
            )
        )
    degraded_at = [s.horizon_days for s in per_horizon if s.state == "degraded"]
    measured_at = [s.horizon_days for s in per_horizon if s.state != "unmeasured"]
    unmeasured_at = [s.horizon_days for s in per_horizon if s.state == "unmeasured"]
    if degraded_at:
        state = "degraded"
        horizons = "/".join(str(h) for h in degraded_at)
        note = (
            f"degraded at the {horizons}-day horizon(s): pooled "
            f"backtest MAPE above the accuracy pack's stated "
            f"{threshold}% bar (pack {pack_version}) — pooled "
            f"from origins before {origin.isoformat()} only"
        )
    elif not measured_at:
        state = "unmeasured"
        note = (
            f"accuracy unmeasured as of {origin.isoformat()}: no "
            "earlier backtest origin stands for this series yet"
        )
    else:
        state = "measured"
        note = (
            f"measured over the backtest origins before "
            f"{origin.isoformat()} (pack {pack_version})"
        )
        if unmeasured_at:
            horizons = "/".join(str(h) for h in unmeasured_at)
            note += f"; no earlier coverage at the {horizons}-day horizon(s) yet"
    return AccuracyAttachment(
        state=state,  # type: ignore[arg-type]
        pack_version=pack_version,
        per_horizon=per_horizon,
        note=note,
    )


def _judge_outcome(
    value: str, realised_drift_pct: float, signal_pack: SignalPack
) -> tuple[str, bool]:
    """The pack's outcome rule: the move, and whether it vindicates."""
    if realised_drift_pct >= signal_pack.rise_threshold_pct:
        move = "rose"
    elif realised_drift_pct <= signal_pack.fall_threshold_pct:
        move = "fell"
    else:
        move = "flat"
    if value == "buy_now":
        favourable = move == "rose"
    elif value == "phased":
        favourable = move in ("rose", "flat")
    else:  # wait
        favourable = move in ("fell", "flat")
    return move, favourable


def _outcome_row(
    store: Store,
    population: str,
    signal: BuySignal,
    signal_pack: SignalPack,
) -> SignalOutcomeRow:
    base = {
        "population": population,
        "commodity": signal.commodity,
        "market": signal.market,
        "as_of": signal.as_of,
        "signal_id": signal.signal_id,
        "forecast_id": signal.forecast_id,
        "value": signal.value,
        "base_value": signal.base_value,
        "caps_applied": list(signal.caps_applied),
        "accuracy_state": signal.accuracy_state,
        "spot_inr": signal.spot_inr,
        "spot_date": signal.spot_date,
        "predicted_drift_pct": signal.drift_pct,
    }
    horizon_end = signal.as_of + timedelta(days=signal.horizon_days)
    rows = store.series(
        signal.commodity,
        signal.market,
        "modal_price",
        signal.as_of + timedelta(days=1),
        horizon_end,
    )
    if not rows:
        all_rows = store.series(signal.commodity, signal.market, "modal_price")
        last_seen = (
            all_rows[-1].obs_date.isoformat()
            if all_rows
            else "no observation at all"
        )
        return SignalOutcomeRow(
            **base,
            state="pending",
            reason=(
                f"the {signal.horizon_days}-day horizon ends "
                f"{horizon_end.isoformat()} and no observation "
                f"stands inside it (the series' last observed "
                f"day is {last_seen}) — the outcome is not yet "
                "measurable and is named pending, never graded"
            ),
            realised_date=None,
            realised_inr=None,
            realised_drift_pct=None,
            drift_error_pct=None,
            move=None,
            favourable=None,
        )
    realised = rows[-1]
    realised_drift = round(
        (float(realised.value) - signal.spot_inr) / signal.spot_inr * 100, 4
    )
    move, favourable = _judge_outcome(signal.value, realised_drift, signal_pack)
    return SignalOutcomeRow(
        **base,
        state="graded",
        reason=None,
        realised_date=realised.obs_date,
        realised_inr=float(realised.value),
        realised_drift_pct=realised_drift,
        drift_error_pct=round(realised_drift - signal.drift_pct, 4),
        move=move,  # type: ignore[arg-type]
        favourable=favourable,
    )


def _grid_outcomes(
    store: Store,
    manifest,
    accuracy_pack: AccuracyPack,
    signal_pack: SignalPack,
) -> tuple[list[SignalOutcomeRow], list[OriginSignalSkip]]:
    rows: list[SignalOutcomeRow] = []
    skips: list[OriginSignalSkip] = []
    for spec in COMMODITIES:
        for market_spec in spec.markets:
            for origin in monthly_origins(accuracy_pack):
                try:
                    forecast = run_engine(
                        store,
                        manifest,
                        spec.commodity,
                        market_spec.market,
                        origin,
                        via_backtest=True,
                    )
                except ForecastError as exc:
                    skips.append(
                        OriginSignalSkip(
                            commodity=spec.commodity,
                            market=market_spec.market,
                            origin=origin,
                            reason=str(exc),
                        )
                    )
                    continue
                forecast.accuracy = _asof_attachment(
                    store, spec.commodity, market_spec.market, origin, accuracy_pack
                )
                forecast.forecast_id = forecast_content_id(forecast)
                signal = compute_signal(store, forecast, signal_pack)
                rows.append(
                    _outcome_row(store, "backtest_grid", signal, signal_pack)
                )
    return rows, skips


# --- transmission error -------------------------------------------------------


def _transmission_rows(
    store: Store, pack: AnalyticsPack, event_pack: EventPack
) -> list[TransmissionClassRow]:
    events = store.list_market_events()
    rows: list[TransmissionClassRow] = []
    for event_class in EVENT_CLASSES:
        members = [e for e in events if e.event_class == event_class]
        measured = []
        not_measurable_ids: list[str] = []
        for event in members:
            verdict = measure_event_effect(store, event, event_pack)
            if verdict.status == "not_measurable" or verdict.measured_log_effect is None:
                not_measurable_ids.append(event.event_id)
            else:
                measured.append((event, verdict))
        signed = [
            round(v.measured_log_effect - e.transmission.peak_log_price_effect, 4)
            for e, v in measured
        ]
        ratios = [v.ratio_to_claim for _, v in measured if v.ratio_to_claim is not None]
        n_measurable = len(measured)
        if n_measurable == 0:
            sample_state = "no_measurable_events"
            note = (
                "no measurable event of this class stands in the "
                "registry — nothing here is evidence about the "
                "class's transmissions"
            )
        elif n_measurable < pack.min_class_sample:
            sample_state = "small_sample"
            note = (
                f"small sample: {n_measurable} measurable event(s) "
                f"against the pack's stated minimum of "
                f"{pack.min_class_sample} — the aggregates are "
                "printed and read as anecdote, not evidence"
            )
        else:
            sample_state = "evidence"
            note = (
                f"{n_measurable} measurable events meet the pack's "
                f"stated minimum sample of {pack.min_class_sample}"
            )
        rows.append(
            TransmissionClassRow(
                event_class=event_class,
                event_ids=[e.event_id for e in members],
                measurable_event_ids=[e.event_id for e, _ in measured],
                not_measurable_event_ids=not_measurable_ids,
                n_events=len(members),
                n_measurable=n_measurable,
                verified_count=sum(
                    1 for _, v in measured if v.status == "verified"
                ),
                unverified_count=sum(
                    1 for _, v in measured if v.status == "unverified"
                ),
                mean_signed_error=(
                    round(sum(signed) / len(signed), 4) if signed else None
                ),
                mean_abs_error=(
                    round(sum(abs(s) for s in signed) / len(signed), 4)
                    if signed
                    else None
                ),
                mean_ratio_to_claim=(
                    round(sum(ratios) / len(ratios), 4) if ratios else None
                ),
                sample_state=sample_state,  # type: ignore[arg-type]
                note=note,
            )
        )
    return rows


# --- shock windows --------------------------------------------------------------


def _shock_rows(
    store: Store, accuracy_pack: AccuracyPack
) -> list[ShockWindowRow]:
    rows: list[ShockWindowRow] = []
    for event in store.list_market_events():
        spec = BY_NAME[event.commodity]
        for market_spec in spec.markets:
            market = market_spec.market
            price_rows = store.series(event.commodity, market, "modal_price")
            last_observed = price_rows[-1].obs_date if price_rows else event.window_start
            if event.window_end is not None:
                shock_end = event.window_end + timedelta(days=event.decay_days)
            else:
                shock_end = last_observed
            for horizon in accuracy_pack.horizons_days:
                results = store.list_backtest_results(
                    event.commodity, market, horizon
                )
                shock = _pool_days(
                    results,
                    lambda d: event.window_start <= d <= shock_end,
                )
                rest = _pool_days(
                    results,
                    lambda d: not (event.window_start <= d <= shock_end),
                )
                n_results_shock = sum(
                    1
                    for r in results
                    if any(
                        event.window_start <= day.forecast_date <= shock_end
                        for day in r.days
                    )
                )
                if shock["n_days"] == 0:
                    state = "no_shock_window_days"
                    reason = (
                        "no scored day of this series x horizon "
                        "falls inside the event's window — the "
                        "grid never graded this event here, and "
                        "the row names that rather than reporting "
                        "a grade"
                    )
                elif rest["n_days"] == 0:
                    state = "no_baseline_days"
                    reason = (
                        "every scored day of this series x "
                        "horizon falls inside the event's window "
                        "— there is no outside-window baseline to "
                        "grade the shock against"
                    )
                else:
                    state = "graded"
                    reason = (
                        f"shock days pool to MAPE {shock['mape']}% "
                        f"against {rest['mape']}% outside the "
                        "window, from the stored scored days alone"
                    )
                rows.append(
                    ShockWindowRow(
                        event_id=event.event_id,
                        event_class=event.event_class,
                        commodity=event.commodity,
                        market=market,
                        horizon_days=horizon,
                        window_start=event.window_start,
                        window_end=event.window_end,
                        shock_end=shock_end,
                        state=state,  # type: ignore[arg-type]
                        reason=reason,
                        n_results_shock=n_results_shock,
                        shock_n_days=shock["n_days"],
                        shock_mape=shock["mape"] if shock["n_days"] else None,
                        shock_coverage=(
                            shock["coverage"] if shock["n_days"] else None
                        ),
                        rest_n_days=rest["n_days"],
                        rest_mape=rest["mape"] if rest["n_days"] else None,
                        rest_coverage=(
                            rest["coverage"] if rest["n_days"] else None
                        ),
                        delta_mape_pp=(
                            round(shock["mape"] - rest["mape"], metrics.METRIC_DP)
                            if state == "graded"
                            else None
                        ),
                    )
                )
    rows.sort(key=lambda r: (r.event_id, r.market, r.horizon_days))
    return rows


# --- the report ------------------------------------------------------------------


def compute_report(
    store: Store,
    analytics_pack: AnalyticsPack | None = None,
    accuracy_pack: AccuracyPack | None = None,
    signal_pack: SignalPack | None = None,
    event_pack: EventPack | None = None,
) -> OpsReport:
    """Compute the ops report from the store's artefacts of record."""
    analytics_pack = analytics_pack or load_analytics_pack()
    accuracy_pack = accuracy_pack or load_accuracy_pack()
    signal_pack = signal_pack or load_signal_pack()
    event_pack = event_pack or load_event_pack()
    manifest = store.get_manifest()
    if manifest is None:
        raise AnalyticsError("dataset not loaded; run the ingest workflow first")

    trends = [
        _trend_row(store, spec.commodity, market_spec.market, horizon, analytics_pack)
        for spec in COMMODITIES
        for market_spec in spec.markets
        for horizon in accuracy_pack.horizons_days
    ]
    grid_rows, skips = _grid_outcomes(store, manifest, accuracy_pack, signal_pack)
    desk_rows = [
        _outcome_row(store, "desk", signal, signal_pack)
        for signal in store.list_buy_signals()
    ]
    outcomes = sorted(
        grid_rows + desk_rows,
        key=lambda r: (r.population, r.commodity, r.market, r.as_of, r.signal_id),
    )
    transmission = _transmission_rows(store, analytics_pack, event_pack)
    report = OpsReport(
        report_id="OPS-pending",
        analytics_pack_version=analytics_pack.version,
        accuracy_pack_version=accuracy_pack.version,
        signal_pack_version=signal_pack.version,
        event_pack_version=event_pack.version,
        history_start=manifest.history_start,
        history_end=manifest.history_end,
        n_backtest_results=len(store.list_backtest_results()),
        trends=trends,
        signal_outcomes=outcomes,
        origin_signal_skips=skips,
        transmission=transmission,
        shock_windows=_shock_rows(store, accuracy_pack),
        small_sample_classes=[
            row.event_class
            for row in transmission
            if row.sample_state != "evidence"
        ],
    )
    return report.model_copy(update={"report_id": report_content_id(report)})
