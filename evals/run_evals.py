"""Eval gate v1 — data integrity against the planted manifest.

Zero-tolerance counters, graded against the generator manifest (the
contract for everything planted):

- shock_band_violations: the planted tariff shock's measured effect
  on soybean prices outside its stated band, either market.
- ban_band_violations: the planted export ban's measured effect on
  basmati prices outside its stated band, either market.
- seasonality_missing: wheat arrivals show no harvest-season peak.
- missing_days_inside_coverage: a non-coffee series short of its
  stated operating days inside coverage.
- coffee_sparsity_violations: coffee rows inside the planted
  disruption window, a wrong reporting-day count, extra drivers, or
  any sign of zero-filling.
- truth_isolation_violations: the forecast package importing or
  naming the truth store / truth table.
- manifest_mismatches: stored events or trend breaks differing from
  the manifest.

Round 2 counters (forecast engine), also zero-tolerance:

- decomposition_sum_violations: forecast days whose baseline +
  contributions + events do not re-add to the stated total, or
  artefacts the re-performance verifier flags.
- contribution_sign_violations: the planted harvest-window arrivals
  surge failing to produce a negative arrivals coefficient and a
  negative 7-day arrivals contribution for wheat.
- coffee_gap_violations: coffee's missing drivers not named exactly,
  its sparsity multiplier failing to separate from wheat's by the
  stated factor, or its 30-day band not wider than wheat's.
- tamper_undetected: a stored forecast with an altered total that
  the verifier does not catch.
- sealed_window_acceptances: an engine run with as_of inside the
  sealed grading window that is not refused.
- commentary_figure_violations_accepted: a commentary draft stating
  a figure the artefact does not carry that gets stored anyway.
- events_slot_violations: the events slot non-zero on a plain run,
  or failing to apply (with the decomposition intact) when filled.

Round 3 counters (backtesting + accuracy ledger, Law 2), also
zero-tolerance:

- backtest_grid_errors: the harness storing anything but the pack's
  grid (405 results, 135 engine runs, exactly coffee's five
  unstatable origins skipped, 42 ledger records), or a re-run
  storing duplicates.
- metric_fixture_errors: the hand-computed metric fixtures (a
  four-day scored slice; a three-origin windowed aggregation)
  recomputed wrong.
- backtest_result_verify_failures: stored results the
  re-performance verifier flags, or a tampered result it misses.
- ledger_reperformance_failures: ledger records that do not
  re-perform from the result artefacts of record.
- degraded_flag_errors: a record whose degraded stamp disagrees
  with its MAPE vs the pack bar, a degraded set other than the
  planted noisy series (chili at Guntur, 30/90 days), or a fresh
  forecast whose pinned state disagrees with the ledger.
- degraded_flag_suppressed: any read path (including a caller
  asking for a "clean" view) returning the degraded forecast
  without its flag.
- unmeasured_unnamed: a forecast run before any backtest coverage
  whose accuracy is not explicitly named unmeasured.
- sealed_check_failures: the boundary dry-run against the sealed
  truth — a horizon with no scored days, MAPE at or above the
  stated 10% bound, or interval coverage below 0.80, for wheat or
  coffee. (Eval-only composition: the gate hands truth rows to the
  harness's scoring; no product code reads the truth store.)

Round 4 counters (sentiment, Law 3), also zero-tolerance:

- sentiment_extraction_errors: a stored extraction disagreeing
  with the planted intent anywhere in the 583-item corpus —
  direction, strength, score or aspects on a clear item, or a
  planted ambiguous/signalless item landing classified (or a
  clear item landing unclassified).
- sentiment_index_reperformance_failures: a stored weekly index
  that does not recompute exactly from the stored extractions.
- sentiment_contribution_errors: a forecast whose sentiment line
  is not in the planted state for its commodity — estimated for
  the five rich-corpus commodities, a named not-estimable line
  (zero everywhere, in missing_drivers) for groundnut and
  coffee — or whose decomposition fails re-performance.
- sentiment_claim_violations_accepted: a commentary draft whose
  sentiment claim is uncited or contradicts its cited items that
  gets stored anyway; or an honest draft missing its citations.
- sentiment_intent_isolation_violations: a scoring module
  (pack/extract/index/verify/service/models) importing the
  corpus or grading modules, or naming the intent table.

Round 5 counters (event registry + shock handling, Law 4), also
zero-tolerance:

- event_registry_errors: the historical seeding storing anything
  but the manifest's three planted shocks, mapped field-for-field
  (classes, channels, windows, claimed peaks, the drought's
  weather-channel derivation), or a re-seed duplicating a record.
- event_transmission_verification_errors: a planted event whose
  claimed transmission does not verify against the
  seasonally-matched measurement, a forged wild claim over the
  real tariff window (or a wrong-sign one) not flagged
  unverified on the event's face, or a future event reading as
  anything but not_measurable, named.
- event_forecast_line_errors: the hand-computed fixture forecast
  (wheat, +0.10 over 2026-01-10..19, decay 10, as of 2025-12-31)
  missing the event line at the stated magnitude on any day, a
  clear run carrying an adjustment, per-event lines that do not
  compose the day adjustments, or any decomposition failure.
- event_interval_widening_errors: a shocked forecast day whose
  log band width is not the plain run's width times the pack's
  stated factor, or an untouched day whose width moved.
- event_registration_errors: a declaration the registry accepts
  that it must refuse (placeholder declarer, channel outside the
  class, zero peak, inverted window, unknown basis/class/
  commodity).
- event_impact_errors: the tariff's what-happened view not
  measured, its mean effect outside the planted direction, or a
  future event's impact reading as measured.

Round 6 counters (scenario studio, Law 5), also zero-tolerance:

- scenario_parse_errors: a parse fixture whose lever set differs
  from the stated grammar's, a refusal fixture that parses, or a
  service-level refusal naming the wrong clause.
- scenario_bounds_errors: a lever at its pack bound refused, or
  a lever beyond its bound accepted.
- scenario_fork_errors: the fork stored as a desk forecast, a
  stored run the verifier flags, a base that does not apply the
  declared event, or a fork baseline that moved.
- scenario_diff_errors: per-day diff parts that do not
  re-perform to the stated driver totals or the P50 total.
- scenario_event_errors: an extension whose window end is not
  the source's plus the stated days, a scenario event written
  into the registry, or the registry record itself moved.
- scenario_adoption_errors: an adopted view before the act, a
  placeholder adopter accepted, a re-adoption not refused as a
  state error, a supersession link wrong, or the base forecast
  artefact differing by a byte after all scenario activity.

Run: uv run python evals/run_evals.py  (exit 0 = GATE: PASS)
"""

from __future__ import annotations

import ast
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fmcg_forecast.catalogue import BY_NAME  # noqa: E402
from fmcg_forecast.generator import _operating_days, generate_dataset  # noqa: E402
from fmcg_forecast.store import build_store  # noqa: E402
from fmcg_forecast.truth import build_truth_store  # noqa: E402
from fmcg_forecast.workflow import load_dataset  # noqa: E402


def mean_price(store, commodity, market, start, end) -> float:
    rows = store.series(commodity, market, "modal_price", start, end)
    return sum(r.value for r in rows) / len(rows)


def truth_isolation_violations() -> int:
    base = Path(__file__).resolve().parents[1] / "src" / "fmcg_forecast"
    violations = 0
    paths = (
        list((base / "forecast").rglob("*.py"))
        + list((base / "backtest").rglob("*.py"))
        + list((base / "events").rglob("*.py"))
        + list((base / "scenarios").rglob("*.py"))
    )
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "fmcg_forecast.truth" or alias.name.endswith(".truth"):
                        violations += 1
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "fmcg_forecast.truth" or module.endswith(".truth"):
                    violations += 1
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "truth_observations" in node.value:
                    violations += 1
    return violations


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fmcg-evals-"))
    store = build_store(str(tmp / "evals.db"))
    truth_store = build_truth_store(str(tmp / "evals.db"))
    data = generate_dataset()
    load_dataset(store, truth_store, data.manifest.seed)
    manifest = store.get_manifest()
    assert manifest is not None

    counters = {
        "shock_band_violations": 0,
        "ban_band_violations": 0,
        "seasonality_missing": 0,
        "missing_days_inside_coverage": 0,
        "coffee_sparsity_violations": 0,
        "truth_isolation_violations": 0,
        "manifest_mismatches": 0,
        "decomposition_sum_violations": 0,
        "contribution_sign_violations": 0,
        "coffee_gap_violations": 0,
        "tamper_undetected": 0,
        "sealed_window_acceptances": 0,
        "commentary_figure_violations_accepted": 0,
        "events_slot_violations": 0,
        "backtest_grid_errors": 0,
        "metric_fixture_errors": 0,
        "backtest_result_verify_failures": 0,
        "ledger_reperformance_failures": 0,
        "degraded_flag_errors": 0,
        "degraded_flag_suppressed": 0,
        "unmeasured_unnamed": 0,
        "sealed_check_failures": 0,
        "sentiment_extraction_errors": 0,
        "sentiment_index_reperformance_failures": 0,
        "sentiment_contribution_errors": 0,
        "sentiment_claim_violations_accepted": 0,
        "sentiment_intent_isolation_violations": 0,
        "event_registry_errors": 0,
        "event_transmission_verification_errors": 0,
        "event_forecast_line_errors": 0,
        "event_interval_widening_errors": 0,
        "event_registration_errors": 0,
        "event_impact_errors": 0,
        "scenario_parse_errors": 0,
        "scenario_bounds_errors": 0,
        "scenario_fork_errors": 0,
        "scenario_diff_errors": 0,
        "scenario_event_errors": 0,
        "scenario_adoption_errors": 0,
    }

    # --- planted events, measured seasonally-matched ---------------
    # Raw before/after windows are confounded by the harvest calendar
    # (the ban lands in the basmati arrivals surge), so the effect is
    # measured as a ratio of ratios: the event year's post/pre move
    # divided by the same calendar windows one year earlier. That
    # differences out seasonality and arrivals seasonality, leaving
    # trend + event + noise.
    def yoy_effect(commodity, market, start, pre_days, post_start_off, post_end):
        def window_ratio(year_shift_days):
            pre = mean_price(
                store, commodity, market,
                start - timedelta(days=pre_days + year_shift_days),
                start - timedelta(days=5 + year_shift_days),
            )
            post = mean_price(
                store, commodity, market,
                start + timedelta(days=post_start_off - year_shift_days * 0) - timedelta(days=year_shift_days),
                post_end - timedelta(days=year_shift_days),
            )
            return post / pre

        return window_ratio(0) / window_ratio(365)

    tariff = next(e for e in manifest.events if e.kind == "tariff_shock")
    for market in ("indore", "nagpur"):
        effect = yoy_effect(
            "soybean", market, tariff.start_date, 25, 5,
            tariff.start_date + timedelta(days=20),
        )
        if not (1.06 <= effect <= 1.24):
            counters["shock_band_violations"] += 1

    ban = next(e for e in manifest.events if e.kind == "export_ban")
    for market in ("delhi_khari_baoli", "karnal"):
        effect = yoy_effect(
            "basmati_rice", market, ban.start_date, 25, 5,
            ban.end_date - timedelta(days=10),
        )
        if not (0.83 <= effect <= 0.96):
            counters["ban_band_violations"] += 1
    # the ban must also show in the export flow itself
    ban_exports = store.series(
        "basmati_rice", "delhi_khari_baoli", "export_flow", ban.start_date, ban.end_date
    )
    normal_exports = store.series(
        "basmati_rice", "delhi_khari_baoli", "export_flow",
        ban.start_date - timedelta(days=40), ban.start_date - timedelta(days=10),
    )
    if (sum(r.value for r in ban_exports) / len(ban_exports)) > 0.25 * (
        sum(r.value for r in normal_exports) / len(normal_exports)
    ):
        counters["ban_band_violations"] += 1

    # --- seasonality (wheat arrivals, harvest vs lean) ---------------
    from datetime import date

    harvest = store.series("wheat", "delhi_khari_baoli", "arrivals", date(2024, 4, 1), date(2024, 6, 30))
    lean = store.series("wheat", "delhi_khari_baoli", "arrivals", date(2024, 10, 1), date(2024, 12, 31))
    ratio = (sum(r.value for r in harvest) / len(harvest)) / (sum(r.value for r in lean) / len(lean))
    if ratio < 1.25:
        counters["seasonality_missing"] += 1

    # --- coverage completeness (non-coffee) ---------------------------
    for cov in manifest.commodities:
        if cov.commodity == "coffee":
            continue
        spec = BY_NAME[cov.commodity]
        expected_days = len(_operating_days(spec, manifest.history_start, manifest.history_end))
        if cov.history_days_per_market != expected_days:
            counters["missing_days_inside_coverage"] += 1
        for market in cov.markets:
            for driver in cov.drivers:
                rows = store.series(cov.commodity, market, driver)
                if len(rows) != expected_days:
                    counters["missing_days_inside_coverage"] += 1

    # --- coffee sparsity, exactly as planted --------------------------
    coffee_cov = next(c for c in manifest.commodities if c.commodity == "coffee")
    coffee_spec = BY_NAME["coffee"]
    full_days = len(_operating_days(coffee_spec, manifest.history_start, manifest.history_end))
    expected_coffee_days = full_days - manifest.coffee_disruption_reporting_days_lost
    if coffee_cov.history_days_per_market != expected_coffee_days:
        counters["coffee_sparsity_violations"] += 1
    if coffee_cov.history_rows != expected_coffee_days * len(coffee_cov.drivers):
        counters["coffee_sparsity_violations"] += 1
    if set(coffee_cov.drivers) != {"modal_price", "arrivals", "weather_index"}:
        counters["coffee_sparsity_violations"] += 1
    if set(coffee_cov.missing_drivers) != {"stock_level", "import_flow", "export_flow"}:
        counters["coffee_sparsity_violations"] += 1
    in_window = store.series(
        "coffee", "bengaluru", "modal_price",
        manifest.coffee_disruption_start, manifest.coffee_disruption_end,
    )
    if in_window:
        counters["coffee_sparsity_violations"] += 1
    # zero-fill probe: a filled series would repeat the previous value
    # across the disruption boundary; the real series must jump dates.
    coffee_prices = store.series("coffee", "bengaluru", "modal_price")
    if len(coffee_prices) != expected_coffee_days:
        counters["coffee_sparsity_violations"] += 1

    # --- truth isolation ----------------------------------------------
    counters["truth_isolation_violations"] = truth_isolation_violations()
    if truth_store.count() != manifest.future_rows:
        counters["truth_isolation_violations"] += 1

    # --- manifest vs stored registry -----------------------------------
    stored_by_id = {e.event_id: e for e in store.list_events()}
    if set(stored_by_id) != {e.event_id for e in manifest.events}:
        counters["manifest_mismatches"] += 1
    for planted in manifest.events:
        stored = stored_by_id.get(planted.event_id)
        if stored is None or stored.magnitude != planted.magnitude or stored.start_date != planted.start_date:
            counters["manifest_mismatches"] += 1
    if len(manifest.trend_breaks) != 2:
        counters["manifest_mismatches"] += 1
    if manifest.history_digest != data.manifest.history_digest:
        counters["manifest_mismatches"] += 1
    counts = store.row_counts()
    if sum(counts.values()) != manifest.history_rows:
        counters["manifest_mismatches"] += 1

    # --- R2: the forecast engine --------------------------------------
    from datetime import date as _date

    from fmcg_forecast.forecast.engine import (
        EventAdjustment,
        SealedWindowRefusal,
        run_engine,
    )
    from fmcg_forecast.forecast.service import (
        CommentaryVerificationError,
        ForecastService,
    )
    from fmcg_forecast.forecast.verify import verify_forecast
    from fmcg_forecast.modelport import OfflineModel

    service = ForecastService(store, OfflineModel())
    wheat = service.run_forecast("wheat", "delhi_khari_baoli")
    coffee = service.run_forecast("coffee", "bengaluru")
    soybean = service.run_forecast("soybean", "indore")

    for forecast in (wheat, coffee, soybean):
        for day in forecast.days:
            parts = day.baseline + sum(day.contributions.values()) + day.events_adjustment
            if abs(parts - day.p50) > 0.011:
                counters["decomposition_sum_violations"] += 1
        counters["decomposition_sum_violations"] += len(verify_forecast(forecast))

    harvest = run_engine(store, manifest, "wheat", "delhi_khari_baoli", _date(2025, 4, 15))
    arrivals = next(line for line in harvest.lines if line.driver == "arrivals")
    if arrivals.coefficient >= 0:
        counters["contribution_sign_violations"] += 1
    if arrivals.at_horizon["7"] >= 0:
        counters["contribution_sign_violations"] += 1

    if coffee.missing_drivers != ["stock_level", "import_flow", "export_flow"]:
        counters["coffee_gap_violations"] += 1
    if coffee.method.sparsity.multiplier < 1.5 * wheat.method.sparsity.multiplier:
        counters["coffee_gap_violations"] += 1
    c30 = next(s for s in coffee.horizons_summary if s.horizon_days == 30)
    w30 = next(s for s in wheat.horizons_summary if s.horizon_days == 30)
    if (c30.p90 - c30.p10) / c30.p50 <= (w30.p90 - w30.p10) / w30.p50:
        counters["coffee_gap_violations"] += 1

    tampered = soybean.model_copy(deep=True)
    tampered.days[5].p50 += 250.0
    if not verify_forecast(tampered):
        counters["tamper_undetected"] += 1

    try:
        run_engine(store, manifest, "wheat", "indore", _date(2026, 2, 1))
        counters["sealed_window_acceptances"] += 1
    except SealedWindowRefusal:
        pass

    class _LyingModel:
        profile_name = "lying"

        def draft_commentary(self, *, subject, figures):
            return f"{subject}. P50 at 30 days (INR/quintal): 9999.99."

    lying = ForecastService(store, _LyingModel())
    target = lying.run_forecast("basmati_rice", "karnal")
    try:
        lying.draft_commentary(target.forecast_id)
        counters["commentary_figure_violations_accepted"] += 1
    except CommentaryVerificationError:
        pass
    if store.get_commentary(target.forecast_id) is not None:
        counters["commentary_figure_violations_accepted"] += 1

    if any(d.events_adjustment != 0.0 for d in wheat.days):
        counters["events_slot_violations"] += 1
    shocked = run_engine(
        store,
        manifest,
        "cumin",
        "unjha",
        _date(2025, 12, 31),
        event_adjustments=[EventAdjustment(event_id="EVT-TEST", path=[0.10] * 90)],
    )
    if shocked.days[0].events_adjustment <= 0:
        counters["events_slot_violations"] += 1
    counters["events_slot_violations"] += len(verify_forecast(shocked))

    # --- R3: backtesting + the accuracy ledger (Law 2) -----------------
    from fmcg_forecast.backtest import metrics as bt_metrics
    from fmcg_forecast.backtest.harness import run_all, score_sealed_boundary
    from fmcg_forecast.backtest.pack import load_accuracy_pack
    from fmcg_forecast.backtest.verify import (
        verify_accuracy_record,
        verify_backtest_result,
    )

    pack = load_accuracy_pack()

    # Unmeasured must be named BEFORE the harness runs: this forecast
    # is the first groundnut/gondal run on this store.
    pre = service.run_forecast("groundnut", "gondal")
    if (
        pre.accuracy is None
        or pre.accuracy.state != "unmeasured"
        or "unmeasured" not in pre.accuracy.note
        or any(s.state != "unmeasured" for s in pre.accuracy.per_horizon)
    ):
        counters["unmeasured_unnamed"] += 1

    # Metric fixtures, worked by hand (see tests/test_r3.py for the
    # arithmetic): four scored days against band (180, 200, 220).
    _, sums = bt_metrics.score_days(
        [
            (_date(2025, 1, 2), 180.0, 200.0, 220.0),
            (_date(2025, 1, 3), 180.0, 200.0, 220.0),
            (_date(2025, 1, 4), 180.0, 200.0, 220.0),
            (_date(2025, 1, 5), 180.0, 200.0, 220.0),
        ],
        {
            _date(2025, 1, 2): 210.0,
            _date(2025, 1, 3): 190.0,
            _date(2025, 1, 4): 200.0,
            _date(2025, 1, 5): 250.0,
        },
    )
    if not (
        sums["n_days"] == 4
        and sums["covered_days"] == 3
        and sums["sum_err"] == 50.0
        and sums["sum_abs_err"] == 70.0
        and sums["mae"] == 17.5
        and sums["bias"] == 12.5
        and sums["coverage"] == 0.75
        and sums["mape"] == round(100.0 * round(1 / 21 + 1 / 19 + 0.2, 6) / 4, 4)
    ):
        counters["metric_fixture_errors"] += 1

    report, records = run_all(store, pack)
    if report.results_stored != 405 or report.engine_runs != 135:
        counters["backtest_grid_errors"] += 1
    if len(report.skipped) != 5 or {s["commodity"] for s in report.skipped} != {"coffee"}:
        counters["backtest_grid_errors"] += 1
    if len(records) != 42:
        counters["backtest_grid_errors"] += 1
    report2, _ = run_all(store, pack)
    if report2.results_stored != 0 or report2.results_already_on_record != 405:
        counters["backtest_grid_errors"] += 1

    stored_results = store.list_backtest_results()
    if len(stored_results) != 405:
        counters["backtest_grid_errors"] += 1
    for result in stored_results:
        counters["backtest_result_verify_failures"] += len(
            verify_backtest_result(result)
        )
    tampered_result = stored_results[0].model_copy(deep=True)
    tampered_result.days[0].realised += 500.0
    if not verify_backtest_result(tampered_result):
        counters["backtest_result_verify_failures"] += 1

    for record in records:
        results = store.list_backtest_results(
            record.commodity, record.market, record.horizon_days
        )
        counters["ledger_reperformance_failures"] += len(
            verify_accuracy_record(record, results, pack)
        )
        if record.degraded != (record.mape > pack.degraded_mape_pct):
            counters["degraded_flag_errors"] += 1
    degraded_set = {
        (r.commodity, r.market, r.horizon_days) for r in records if r.degraded
    }
    if degraded_set != {("chili", "guntur", 30), ("chili", "guntur", 90)}:
        counters["degraded_flag_errors"] += 1

    chili = service.run_forecast("chili", "guntur")
    if chili.accuracy is None or chili.accuracy.state != "degraded":
        counters["degraded_flag_errors"] += 1
    else:
        for slice_ in chili.accuracy.per_horizon:
            record = store.get_accuracy_record("chili", "guntur", slice_.horizon_days)
            if record is None or slice_.record_id != record.record_id:
                counters["degraded_flag_errors"] += 1
            if slice_.state != ("degraded" if record and record.degraded else "measured"):
                counters["degraded_flag_errors"] += 1
    fresh_wheat = service.run_forecast("wheat", "indore")
    if fresh_wheat.accuracy is None or fresh_wheat.accuracy.state != "measured":
        counters["degraded_flag_errors"] += 1
    chili_commentary = service.draft_commentary(chili.forecast_id)
    if "Backtest accuracy state: degraded" not in chili_commentary.text:
        counters["degraded_flag_errors"] += 1

    from fastapi.testclient import TestClient

    from fmcg_forecast.api import create_app

    client = TestClient(create_app(store, OfflineModel()))
    for params in ({"view": "clean"}, {"accuracy": "off"}, {"flag": "none"}):
        r = client.get(f"/forecasts/{chili.forecast_id}", params=params)
        if r.status_code != 200 or r.json()["accuracy"]["state"] != "degraded":
            counters["degraded_flag_suppressed"] += 1
    r = client.get(f"/forecasts/{chili.forecast_id}/accuracy")
    if r.status_code != 200 or r.json()["accuracy"]["state"] != "degraded":
        counters["degraded_flag_suppressed"] += 1

    # The sealed-boundary dry run: the R2 section's wheat and coffee
    # forecasts sit exactly at the history/truth boundary; the gate
    # hands the truth rows to the harness's scoring (eval-only).
    for boundary_forecast in (wheat, coffee):
        truth_rows = truth_store.read_truth(
            boundary_forecast.commodity, boundary_forecast.market, "modal_price"
        )
        scores = score_sealed_boundary(boundary_forecast, truth_rows)
        for horizon, horizon_sums in scores.items():
            if horizon_sums["n_days"] == 0:
                counters["sealed_check_failures"] += 1
            if horizon_sums["mape"] >= 10.0:
                counters["sealed_check_failures"] += 1
            if horizon_sums["coverage"] < 0.80:
                counters["sealed_check_failures"] += 1

    # --- sentiment (R4, Law 3) --------------------------------------
    # The gate loads the corpus and its grading store itself: the
    # intent is grading-side truth, read here and in the loader
    # only — the isolation counter below proves the scoring
    # modules never touch it.
    from fmcg_forecast.sentiment.corpus import expected_reading
    from fmcg_forecast.sentiment.grading import build_sentiment_grading_store
    from fmcg_forecast.sentiment.index import compute_index
    from fmcg_forecast.sentiment.load import load_sentiment_corpus
    from fmcg_forecast.sentiment.pack import load_sentiment_pack
    from fmcg_forecast.sentiment.service import SentimentService

    grading_store = build_sentiment_grading_store(str(tmp / "evals.db"))
    load_sentiment_corpus(store, grading_store, manifest.seed)
    sentiment = SentimentService(store, OfflineModel())
    pipeline = sentiment.run_pipeline()
    if pipeline["items"] != 583 or pipeline["unclassified"] != 98:
        counters["sentiment_extraction_errors"] += 1

    for extraction in sentiment.list_extractions():
        intent = grading_store.get_intent(extraction.item_id)
        expected = expected_reading(intent)
        if extraction.status != expected["status"]:
            counters["sentiment_extraction_errors"] += 1
        elif expected["status"] == "classified" and (
            extraction.direction != expected["direction"]
            or extraction.strength != expected["strength"]
            or extraction.score != expected["score"]
            or extraction.aspects != expected["aspects"]
        ):
            counters["sentiment_extraction_errors"] += 1

    counters["sentiment_index_reperformance_failures"] += len(
        sentiment.verify_stored()["problems"]
    )
    sentiment_pack = load_sentiment_pack()
    for commodity in ("wheat", "basmati_rice", "soybean", "groundnut", "chili", "cumin", "coffee"):
        extractions = sentiment.list_extractions(commodity)
        for index in sentiment.list_indices(commodity):
            recomputed = compute_index(
                commodity, index.week_start, extractions, sentiment_pack
            )
            if (
                recomputed is None
                or recomputed.value != index.value
                or recomputed.index_id != index.index_id
            ):
                counters["sentiment_index_reperformance_failures"] += 1

    wired = ForecastService(
        store,
        OfflineModel(),
        sentiment_provider=sentiment.forecast_input,
        sentiment_claim_verifier=sentiment.verify_claims,
    )
    estimable = {
        "wheat": "delhi_khari_baoli",
        "basmati_rice": "delhi_khari_baoli",
        "soybean": "indore",
        "chili": "guntur",
        "cumin": "unjha",
    }
    not_estimable = {"groundnut": "rajkot", "coffee": "bengaluru"}
    for commodity, market in estimable.items():
        graded_forecast = wired.run_forecast(commodity, market)
        line = next(
            (l for l in graded_forecast.lines if l.driver == "sentiment"), None
        )
        if (
            line is None
            or line.input_summary.get("state") != "estimated"
            or line.coefficient is None
        ):
            counters["sentiment_contribution_errors"] += 1
        counters["sentiment_contribution_errors"] += len(
            verify_forecast(graded_forecast)
        )
    for commodity, market in not_estimable.items():
        graded_forecast = wired.run_forecast(commodity, market)
        line = next(
            (l for l in graded_forecast.lines if l.driver == "sentiment"), None
        )
        if (
            line is None
            or line.input_summary.get("state") != "not_estimable"
            or line.coefficient is not None
            or any(v != 0.0 for v in line.contribution_path_inr)
            or "sentiment_not_estimable" not in graded_forecast.missing_drivers
        ):
            counters["sentiment_contribution_errors"] += 1
        counters["sentiment_contribution_errors"] += len(
            verify_forecast(graded_forecast)
        )

    honest_forecast = wired.run_forecast("wheat", "kanpur")
    honest = wired.draft_commentary(honest_forecast.forecast_id)
    honest_line = next(
        l for l in honest_forecast.lines if l.driver == "sentiment"
    )
    for item_id in honest_line.input_summary["cited_item_ids"]:
        if item_id not in honest.text:
            counters["sentiment_claim_violations_accepted"] += 1

    wheat_line_forecast = wired.run_forecast("wheat", "indore")
    wheat_line = next(
        l for l in wheat_line_forecast.lines if l.driver == "sentiment"
    )
    cited_ids = ", ".join(wheat_line.input_summary["cited_item_ids"])
    wrong_word = (
        "supportive"
        if wheat_line.input_summary["latest_index_value"] < 0
        else "headwind"
    )

    class _UncitedClaimModel(OfflineModel):
        profile_name = "eval-uncited"

        def draft_commentary(self, *, subject, figures):
            return f"{subject}. Market sentiment reads supportive this month."

    class _WrongDirectionModel(OfflineModel):
        profile_name = "eval-wrong-direction"

        def draft_commentary(self, *, subject, figures):
            return (
                f"{subject}. Sentiment reading (direction per cited "
                f"items): {wrong_word} — items {cited_ids}."
            )

    for probe_model, probe_series in (
        (_UncitedClaimModel(), ("soybean", "nagpur")),
        (_WrongDirectionModel(), ("wheat", "indore")),
    ):
        probe_service = ForecastService(
            store,
            probe_model,
            sentiment_provider=sentiment.forecast_input,
            sentiment_claim_verifier=sentiment.verify_claims,
        )
        probe_forecast = probe_service.run_forecast(*probe_series)
        try:
            probe_service.draft_commentary(probe_forecast.forecast_id)
            counters["sentiment_claim_violations_accepted"] += 1
        except CommentaryVerificationError:
            pass

    sentiment_base = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "fmcg_forecast"
        / "sentiment"
    )
    for module_name in ("pack.py", "extract.py", "index.py", "verify.py", "service.py", "models.py"):
        module_text = (sentiment_base / module_name).read_text(encoding="utf-8")
        if "sentiment_intent" in module_text:
            counters["sentiment_intent_isolation_violations"] += 1
        module_tree = ast.parse(module_text)
        for node in ast.walk(module_tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for imported in names:
                if imported.endswith(".corpus") or imported.endswith(".grading"):
                    counters["sentiment_intent_isolation_violations"] += 1
                if imported in ("corpus", "grading"):
                    counters["sentiment_intent_isolation_violations"] += 1

    # --- events (R5, Law 4) ---------------------------------------
    import math as _math

    from fmcg_forecast.events.pack import load_event_pack
    from fmcg_forecast.events.service import EventService, EventValidationError
    from fmcg_forecast.events.verify import verify_market_event

    event_pack = load_event_pack()
    event_service = EventService(store)
    seeded = event_service.seed_historical(manifest)
    if len(seeded["seeded"]) != 3 or seeded["total_on_record"] != 3:
        counters["event_registry_errors"] += 1
    reseeded = event_service.seed_historical(manifest)
    if reseeded["seeded"] != [] or len(event_service.list_events()) != 3:
        counters["event_registry_errors"] += 1
    by_source = {e.source_record_id: e for e in event_service.list_events()}
    tariff_ev = by_source.get("EVT-2025-TARIFF-SOYBEAN")
    ban_ev = by_source.get("EVT-2024-BAN-BASMATI")
    drought_ev = by_source.get("ANOMALY-CHILI-2025")
    if tariff_ev is None or ban_ev is None or drought_ev is None:
        counters["event_registry_errors"] += 1
    else:
        if not (
            tariff_ev.event_class == "tariff_change"
            and tariff_ev.transmission.channel == "import_flow"
            and tariff_ev.transmission.peak_log_price_effect == tariff.magnitude
            and tariff_ev.window_start == tariff.start_date
            and tariff_ev.window_end == tariff.end_date
            and tariff_ev.decay_days == tariff.decay_days
        ):
            counters["event_registry_errors"] += 1
        if not (
            ban_ev.event_class == "export_restriction"
            and ban_ev.transmission.channel == "export_flow"
            and ban_ev.transmission.driver_effect == 0.05
            and ban_ev.transmission.peak_log_price_effect == ban.magnitude
            and ban_ev.window_start == ban.start_date
            and ban_ev.window_end == ban.end_date
        ):
            counters["event_registry_errors"] += 1
        if not (
            drought_ev.event_class == "weather_shock"
            and drought_ev.transmission.channel == "weather_index"
            and drought_ev.transmission.driver_effect == -0.6
            and abs(drought_ev.transmission.peak_log_price_effect - 0.036) < 1e-9
            and drought_ev.direction == 1
        ):
            counters["event_registry_errors"] += 1
        for planted_ev in (tariff_ev, ban_ev, drought_ev):
            counters["event_registry_errors"] += len(
                verify_market_event(planted_ev, event_pack)
            )
    counters["event_registry_errors"] += len(
        event_service.verify_registry()["problems"]
    )

    # Claimed transmissions vs the seasonally-matched measurement:
    # the planted three verify; a wild claim and a wrong-sign claim
    # over the real tariff window are flagged unverified, on the
    # event's face as well as at the dedicated read.
    for planted_ev, lo, hi in ((tariff_ev, 1.06, 1.24), (ban_ev, 0.83, 0.96)):
        verdict = event_service.verify_event(planted_ev.event_id)
        if verdict.status != "verified" or not (lo <= verdict.measured_ratio <= hi):
            counters["event_transmission_verification_errors"] += 1
    if event_service.verify_event(drought_ev.event_id).status != "verified":
        counters["event_transmission_verification_errors"] += 1

    declaration = dict(
        commodity="soybean",
        window_start=tariff.start_date,
        window_end=tariff.end_date,
        basis="desk_estimate",
        decay_days=45,
        declared_by="eval.desk",
        declared_on=_date(2025, 8, 1),
    )
    forged = event_service.register_event(
        **declaration,
        event_class="tariff_change",
        channel="import_flow",
        peak_log_price_effect=0.60,
        basis_detail="A wild claim over the real tariff window",
        description="Forged tariff claim for the eval probe",
    )
    if event_service.verify_event(forged.event_id).status != "unverified":
        counters["event_transmission_verification_errors"] += 1
    if (
        event_service.event_view(forged.event_id)["verification"]["status"]
        != "unverified"
    ):
        counters["event_transmission_verification_errors"] += 1
    wrong_sign = event_service.register_event(
        **declaration,
        event_class="demand_shock",
        channel="modal_price",
        peak_log_price_effect=-0.16,
        basis_detail="A claim against the measured direction",
        description="Wrong-sign claim over the tariff window",
    )
    if event_service.verify_event(wrong_sign.event_id).status != "unverified":
        counters["event_transmission_verification_errors"] += 1
    future = event_service.register_event(
        event_class="demand_shock",
        commodity="cumin",
        window_start=_date(2026, 6, 1),
        window_end=_date(2026, 6, 30),
        channel="modal_price",
        peak_log_price_effect=0.05,
        basis="desk_estimate",
        basis_detail="A declared future shock for the eval probe",
        decay_days=5,
        description="Declared future shock for the eval probe",
        declared_by="eval.desk",
        declared_on=_date(2026, 1, 3),
    )
    if event_service.verify_event(future.event_id).status != "not_measurable":
        counters["event_transmission_verification_errors"] += 1

    # The hand-computed fixture forecast: wheat, +0.10 declared
    # over 2026-01-10..19 with decay 10, run as of 2025-12-31, so
    # the window opens on forecast day 10.
    wired_events = ForecastService(
        store, OfflineModel(), events_provider=event_service.forecast_adjustments
    )
    clear = wired_events.run_forecast("wheat", "delhi_khari_baoli", _date(2025, 12, 31))
    if (
        any(d.events_adjustment != 0.0 for d in clear.days)
        or wired_events.events_view(clear.forecast_id)["state"] != "clear"
    ):
        counters["event_forecast_line_errors"] += 1
    fixture = event_service.register_event(
        event_class="demand_shock",
        commodity="wheat",
        window_start=_date(2026, 1, 10),
        window_end=_date(2026, 1, 19),
        channel="modal_price",
        peak_log_price_effect=0.10,
        basis="desk_estimate",
        basis_detail="Hand-computed fixture for the eval gate",
        decay_days=10,
        description="Hand-computed fixture event",
        declared_by="eval.desk",
        declared_on=_date(2026, 1, 3),
    )
    shocked_fc = wired_events.run_forecast(
        "wheat", "delhi_khari_baoli", _date(2025, 12, 31)
    )
    fixture_view = wired_events.events_view(shocked_fc.forecast_id)
    if (
        fixture_view["state"] != "shocked"
        or fixture_view["events_applied"] != [fixture.event_id]
    ):
        counters["event_forecast_line_errors"] += 1
    else:
        fixture_path = fixture_view["events"][0]["input_path"]
        for idx, want in (
            (0, 0.0), (9, 0.0333), (10, 0.0667), (11, 0.10),
            (18, 0.10), (19, 0.09), (27, 0.01), (28, 0.0),
        ):
            if abs(fixture_path[idx] - want) > 1e-9:
                counters["event_forecast_line_errors"] += 1
        if any(v != 0.0 for v in fixture_path[28:]):
            counters["event_forecast_line_errors"] += 1
    counters["event_forecast_line_errors"] += len(verify_forecast(shocked_fc))
    for day in shocked_fc.days:
        parts = day.baseline + sum(day.contributions.values()) + day.events_adjustment
        if abs(parts - day.p50) > 0.011:
            counters["event_forecast_line_errors"] += 1

    # Interval widening, exactly per pack: a shocked day's log band
    # width is the plain run's times the stated factor; an
    # untouched day's width does not move.
    plain = run_engine(store, manifest, "wheat", "delhi_khari_baoli", _date(2025, 12, 31))
    probe_path = [0.05 if 9 <= i <= 27 else 0.0 for i in range(90)]
    widened = run_engine(
        store,
        manifest,
        "wheat",
        "delhi_khari_baoli",
        _date(2025, 12, 31),
        event_adjustments=[
            EventAdjustment(
                event_id="EVT-EVAL-WIDEN",
                path=probe_path,
                interval_widening=event_pack.interval_widening_factor,
            )
        ],
    )
    for idx, want in ((11, event_pack.interval_widening_factor), (60, 1.0)):
        width_ratio = _math.log(
            widened.days[idx].p90 / widened.days[idx].p50
        ) / _math.log(plain.days[idx].p90 / plain.days[idx].p50)
        if abs(width_ratio / want - 1.0) > 0.01:
            counters["event_interval_widening_errors"] += 1

    # Registration refusals.
    refusal_base = dict(
        event_class="demand_shock",
        commodity="wheat",
        window_start=_date(2026, 3, 1),
        window_end=_date(2026, 3, 10),
        channel="modal_price",
        peak_log_price_effect=0.05,
        basis="desk_estimate",
        basis_detail="eval probe",
        decay_days=5,
        description="eval probe",
        declared_by="eval.desk",
        declared_on=_date(2026, 1, 3),
    )
    for refusal in (
        {**refusal_base, "declared_by": "unknown"},
        {**refusal_base, "channel": "weather_index"},
        {**refusal_base, "peak_log_price_effect": 0.0},
        {**refusal_base, "window_end": _date(2026, 2, 1)},
        {**refusal_base, "basis": "model_said_so"},
        {**refusal_base, "event_class": "price_control"},
        {**refusal_base, "commodity": "rice_crude"},
    ):
        try:
            event_service.register_event(**refusal)
            counters["event_registration_errors"] += 1
        except EventValidationError:
            pass

    # The what-happened view.
    tariff_impact = event_service.impact(tariff_ev.event_id, "indore")
    if (
        tariff_impact.state != "measured"
        or not (1.0 < tariff_impact.mean_price_ratio < 1.25)
        or tariff_impact.peak_log_effect <= 0.10
    ):
        counters["event_impact_errors"] += 1
    ban_impact = event_service.impact(ban_ev.event_id, "delhi_khari_baoli")
    if ban_impact.state != "measured" or ban_impact.mean_price_ratio >= 1.0:
        counters["event_impact_errors"] += 1
    if event_service.impact(future.event_id, "unjha").state != "not_measurable":
        counters["event_impact_errors"] += 1

    # --- the scenario studio (R6, Law 5) ----------------------------
    import sqlite3 as _sqlite3
    from datetime import timedelta as _timedelta

    from fmcg_forecast.forecast.service import ForecastService as _ForecastService
    from fmcg_forecast.modelport import OfflineModel as _OfflineModel
    from fmcg_forecast.scenarios.diff import compute_diff as scenario_compute_diff
    from fmcg_forecast.scenarios.models import LeverApplication
    from fmcg_forecast.scenarios.pack import load_scenario_pack
    from fmcg_forecast.scenarios.parse import (
        ParseRefusal as ScenarioParseRefusal,
    )
    from fmcg_forecast.scenarios.parse import (
        parse_request_text as scenario_parse_text,
    )
    from fmcg_forecast.scenarios.service import (
        AdoptionStateError,
        AdoptionValidationError,
        ScenarioParseError,
        ScenarioService,
        ScenarioValidationError,
    )

    scenario_pack = load_scenario_pack()
    scenario_forecast_service = _ForecastService(
        store,
        _OfflineModel(),
        sentiment_provider=sentiment.forecast_input,
        sentiment_claim_verifier=sentiment.verify_claims,
        events_provider=event_service.forecast_adjustments,
    )
    scenario_service = ScenarioService(
        store,
        _OfflineModel(),
        scenario_forecast_service,
        event_service,
        sentiment_provider=sentiment.forecast_input,
    )
    eval_tariff = event_service.register_event(
        event_class="tariff_change",
        commodity="soybean",
        window_start=_date(2026, 2, 1),
        window_end=_date(2026, 2, 28),
        channel="import_flow",
        peak_log_price_effect=0.08,
        basis="announced_measure",
        basis_detail="Import duty on oilseeds raised by 10 "
        "percentage points in a ministry notification",
        decay_days=20,
        description="Import tariff increase on oilseeds for February",
        declared_by="eval.desk",
        declared_on=_date(2026, 1, 2),
    )
    scenario_base = scenario_forecast_service.run_forecast("soybean", "indore")
    if eval_tariff.event_id not in scenario_base.method.events_applied:
        counters["scenario_fork_errors"] += 1

    def _raw_base_payload() -> tuple[str, str] | None:
        conn = _sqlite3.connect(str(tmp / "evals.db"))
        try:
            return conn.execute(
                "SELECT payload, status FROM forecasts WHERE forecast_id = ?",
                (scenario_base.forecast_id,),
            ).fetchone()
        finally:
            conn.close()

    base_payload_before = _raw_base_payload()

    # Parse fixtures: exact lever sets, and refusals that name the part.
    ctx = [{"event_id": eval_tariff.event_id, "event_class": "tariff_change"}]
    good_fixtures = {
        "what if arrivals drop 10% and the tariff stays another month?": [
            ("arrivals_shift_pct", -10.0, None, None),
            ("event_extension", None, eval_tariff.event_id, 30),
        ],
        "stock cover falls by 12 days": [
            ("stock_cover_days", -12.0, None, None)
        ],
        "imports rise 20%": [("trade_flow_shift_pct", 20.0, None, None)],
        "weather index deviation of -0.3": [
            ("weather_deviation", -0.3, None, None)
        ],
        "sentiment to -0.8": [("sentiment_override", -0.8, None, None)],
        "a new tariff pushes prices up by 8% for 30 days": [
            ("hypothetical_event", 8.0, None, None)
        ],
    }
    for text, expected in good_fixtures.items():
        try:
            levers = scenario_parse_text(text, events=ctx, pack=scenario_pack)
            got = [
                (l.lever, l.value, l.event_id, l.extra_days) for l in levers
            ]
            if got != expected:
                counters["scenario_parse_errors"] += 1
        except ScenarioParseRefusal:
            counters["scenario_parse_errors"] += 1
    for text in (
        "what if the monsoon fails completely?",
        "arrivals drop 10% and arrivals rise 5%",
        "prices triple overnight",
        "the banana stays another month",
    ):
        try:
            scenario_parse_text(text, events=ctx, pack=scenario_pack)
            counters["scenario_parse_errors"] += 1
        except ScenarioParseRefusal:
            pass
    try:
        scenario_service.parse_request(
            "soybean",
            "indore",
            "what if the monsoon fails completely?",
            base_forecast_id=scenario_base.forecast_id,
        )
        counters["scenario_parse_errors"] += 1
    except ScenarioParseError as refusal:
        if refusal.clause != "the monsoon fails completely":
            counters["scenario_parse_errors"] += 1

    # Bounds: each lever at its bound validates, beyond it refuses.
    bound_probes = [
        ("arrivals_shift_pct", 40.0, 41.0),
        ("arrivals_shift_pct", -40.0, -41.0),
        ("stock_cover_days", 30.0, 31.0),
        ("trade_flow_shift_pct", 60.0, 61.0),
        ("weather_deviation", 0.5, 0.6),
        ("sentiment_override", -1.0, -1.1),
    ]
    for lever_name, at_bound, beyond in bound_probes:
        try:
            scenario_service.validate_levers(
                [LeverApplication(lever=lever_name, value=at_bound)]
            )
        except ScenarioValidationError:
            counters["scenario_bounds_errors"] += 1
        try:
            scenario_service.validate_levers(
                [LeverApplication(lever=lever_name, value=beyond)]
            )
            counters["scenario_bounds_errors"] += 1
        except ScenarioValidationError:
            pass

    # The fork: pinned, identity-exact, base untouched.
    scenario_request = scenario_service.parse_request(
        "soybean",
        "indore",
        "what if arrivals drop 10% and the tariff stays another month?",
        base_forecast_id=scenario_base.forecast_id,
    )
    scenario_run = scenario_service.run_scenario(
        scenario_request.request_id,
        scenario_base.forecast_id,
        "eval.desk",
        _date(2026, 1, 3),
    )
    if scenario_run.status != "draft":
        counters["scenario_fork_errors"] += 1
    if store.get_forecast(scenario_run.fork_forecast_id) is not None:
        counters["scenario_fork_errors"] += 1
    if scenario_service.verify_stored(scenario_run.scenario_id):
        counters["scenario_fork_errors"] += 1
    for base_day, fork_day in zip(
        scenario_base.days, scenario_run.fork.days
    ):
        if base_day.baseline != fork_day.baseline:
            counters["scenario_fork_errors"] += 1
            break

    # The diff: per-day integer-paise identity, totals exact.
    diff, diff_problems = scenario_compute_diff(
        scenario_run.scenario_id, scenario_base, scenario_run.fork
    )
    if diff_problems:
        counters["scenario_diff_errors"] += 1
    totals_paise = {
        driver: sum(
            round(day.contributions[driver] * 100) for day in diff.days
        )
        for driver in (
            "arrivals",
            "stock_level",
            "trade_flow",
            "weather_index",
            "sentiment",
        )
    }
    for driver, paise in totals_paise.items():
        if round(diff.driver_totals[driver] * 100) != paise:
            counters["scenario_diff_errors"] += 1
    events_paise = sum(round(d.events_adjustment * 100) for d in diff.days)
    if round(diff.events_total * 100) != events_paise:
        counters["scenario_diff_errors"] += 1
    if round(diff.p50_total * 100) != sum(totals_paise.values()) + events_paise:
        counters["scenario_diff_errors"] += 1

    # Scenario events stay scenario-local; the registry never moves.
    if len(scenario_run.scenario_events) != 1:
        counters["scenario_event_errors"] += 1
    else:
        extended_ev = scenario_run.scenario_events[0]
        if extended_ev.window_end != eval_tariff.window_end + _timedelta(days=30):
            counters["scenario_event_errors"] += 1
        if store.get_market_event(extended_ev.event_id) is not None:
            counters["scenario_event_errors"] += 1
        if event_service.get_event(
            eval_tariff.event_id
        ).window_end != eval_tariff.window_end:
            counters["scenario_event_errors"] += 1

    # The adoption gate.
    if scenario_service.adopted_view("soybean", "indore")["state"] != "none":
        counters["scenario_adoption_errors"] += 1
    try:
        scenario_service.adopt(
            scenario_run.scenario_id,
            "unknown",
            "Head of Trading Desk",
            _date(2026, 1, 4),
        )
        counters["scenario_adoption_errors"] += 1
    except AdoptionValidationError:
        pass
    act = scenario_service.adopt(
        scenario_run.scenario_id,
        "eval.desk.head",
        "Head of Trading Desk",
        _date(2026, 1, 4),
    )
    if act.supersedes_scenario_id is not None:
        counters["scenario_adoption_errors"] += 1
    adopted = scenario_service.adopted_view("soybean", "indore")
    if (
        adopted["state"] != "adopted"
        or adopted["scenario"]["view_kind"] != "adopted_scenario"
    ):
        counters["scenario_adoption_errors"] += 1
    try:
        scenario_service.adopt(
            scenario_run.scenario_id,
            "eval.desk.head",
            "Head of Trading Desk",
            _date(2026, 1, 5),
        )
        counters["scenario_adoption_errors"] += 1
    except AdoptionStateError:
        pass
    second_request = scenario_service.create_request(
        "soybean",
        "indore",
        [LeverApplication(lever="arrivals_shift_pct", value=-15.0)],
    )
    second_run = scenario_service.run_scenario(
        second_request.request_id,
        scenario_base.forecast_id,
        "eval.desk",
        _date(2026, 1, 3),
    )
    act2 = scenario_service.adopt(
        second_run.scenario_id,
        "eval.desk.head",
        "Head of Trading Desk",
        _date(2026, 1, 6),
    )
    if act2.supersedes_scenario_id != scenario_run.scenario_id:
        counters["scenario_adoption_errors"] += 1
    if scenario_service.get_scenario(scenario_run.scenario_id).status != (
        "superseded"
    ):
        counters["scenario_adoption_errors"] += 1

    # After all scenario activity, the base artefact is byte-identical.
    if _raw_base_payload() != base_payload_before:
        counters["scenario_adoption_errors"] += 1
    if scenario_forecast_service.get_forecast(scenario_base.forecast_id).status != "draft":
        counters["scenario_adoption_errors"] += 1

    print("Round 6 evals — FMCG commodity forecast (R1 data integrity + R2 forecast engine + R3 backtesting/ledger + R4 sentiment + R5 event registry + R6 scenario studio)")
    for name, value in counters.items():
        print(f"  {name}: {value} (required 0)")
    failed = [n for n, v in counters.items() if v != 0]
    if failed:
        print("GATE: FAIL")
        for name in failed:
            print(f"  - {name} = {counters[name]}")
        return 1
    print("GATE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
