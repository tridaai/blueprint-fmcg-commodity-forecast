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

Round 7 counters (prompt-to-dashboard, Law 6), also zero-tolerance:

- dashboard_lineage_errors: a rendered figure on an assembled
  dashboard whose lineage walk is empty, never terminates at a
  stored fact, or does not pass through its own artefact — or
  a stored assembly the verifier flags.
- dashboard_gap_suppression_errors: a clause the catalogue
  cannot state that does not become a named gap panel on the
  spec and a rendered gap on the page, an unrun series rendered
  as anything but a gap, or a scenario panel appearing when
  the prompt named no scenario.
- dashboard_rerun_diff_errors: an identical re-assembly that
  mints a new artefact, a gap->rendered flip after the missing
  forecast lands that the re-run diff misses, or an events
  binding change the diff misses.
- dashboard_board_errors: the morning board missing the
  degraded chili/Guntur row, coffee's named-gap row, or the
  active February tariff row; a row whose artefact does not
  resolve in the store; a clean series (wheat/Delhi) appearing
  among the degraded or data-gap rows; or a board rebuild that
  is not the same artefact.

Round 8 counters (buy-window signals + coverage planning,
F20-PO2/PO3), also zero-tolerance:

- signal_degraded_strong_errors: a signal whose pinned accuracy
  state is degraded (or unmeasured) carrying a buy_now call —
  the signal pack caps both at phased, by rule.
- signal_reperformance_errors: a stored signal the verifier
  flags on re-performance from its pinned forecast and the
  store, a hand-computed fixture (rising / degraded) whose
  engine output differs from the stated expectation, or a
  signal board row whose artefact does not resolve.
- planning_exposure_errors: a stored assessment the verifier
  flags on re-performance (coverage, month pricing, exposure,
  option costs), a tampered exposure figure the verifier
  accepts, or a scenario-basis assessment that is not pinned
  to the adopted run's fork.
- planning_provenance_errors: a desk figure whose walk is not
  exactly the desk-entered terminal fact, a market figure whose
  walk contains a desk-entered fact, a mixed figure without
  exactly one, or a desk-entered fact appearing anywhere in a
  dashboard's provenance appendix (market provenance).
- planning_ranking_errors: an assessment whose options are not
  in the planning pack's ranking order (expected cost, then
  adverse cost, then name) with ranks 1..n.
- board_foreign_series_errors: the morning board failing to
  name a stored artefact from a series outside the catalogue
  (the fixture series' draft forecasts) as a pending-gate row
  badged not_in_catalogue — the board reads the whole record,
  so a foreign series is a named row, never a crash and never
  a silent drop.

Round 9 counters (alerting, subscriptions and escalation,
F20-AL1/AL2/AL3), also zero-tolerance:

- alert_orphan_errors: a stored alert whose subscription or
  triggering artefact does not resolve in the store — an alert
  without its trigger cannot exist.
- alert_derivation_errors: a stored alert that does not
  re-perform field-for-field against a fresh derivation, a
  derived alert that was never raised, or a struck signal the
  sweep's unmatched account does not reconcile.
- alert_state_fold_errors: an accuracy episode with more than
  one open alert, a degraded or collapsed record left without
  its open alert, or an act whose content address does not
  recompute.
- alert_escalation_errors: the escalation fold disagreeing
  with the pack's windows on a fixture clock — an
  unacknowledged alert not climbing at the stated times, or
  an acknowledged one climbing anyway.
- alert_digest_errors: a digest whose alert set is not
  exactly its subscriber's alerts for its date.
- alert_dedup_errors: a repeated sweep raising an alert that
  already stands — a crossing must fire exactly once.

Round 10 counters (thin-data depth + assisted intake,
Law 7 depth / F20-DI3), also zero-tolerance:

- thin_tier_overstatement_errors: a stored assessment whose
  tier a fresh re-performance does not earn, or a tier claim
  (a surface stating a tier) above the earned tier that the
  claim verifier does not refuse as a contradiction — or an
  earned-tier claim it wrongly refuses.
- thin_window_coverage_errors: an assessment window whose
  operating-day counts, observed counts or named missing
  dates disagree with an independent recomputation from the
  observation store, coffee's 365-day window missing any of
  the planted disruption days, or a stored assessment that
  does not re-perform field for field.
- thin_unnamed_gap_errors: a thin series whose assessment,
  board row or forecast view fails to name a gap — coffee's
  unreported drivers (stock, trade flows) or groundnut's
  not-estimable sentiment.
- intake_unconfirmed_leakage_errors: an observation standing
  at a pending or rejected intake entry's key — an
  unconfirmed figure an engine could read.
- intake_self_check_errors: an enterer confirming or
  rejecting their own entry (accepted, or leaving the entry
  in a checked state).
- intake_chain_errors: a confirmed entry not mapping to
  exactly one observation carrying its value, a check act
  whose content address does not recompute, or any chain
  problem the intake verifier reports over the eval's
  entries.

Round 11 counters (production data plane, F20-DI1/DI2/DI4),
also zero-tolerance:

- ingest_quarantine_errors: a planted bad row landing,
  quarantining with reasons other than exactly its planted
  ones, or a tampered quarantine record the verifier accepts.
- ingest_provenance_errors: a connector-landed fact without
  exactly one provenance row naming its batch and source, or
  a provenance row naming a missing batch or source.
- ingest_replay_errors: re-delivering a batch minting a new
  artefact or landing a row twice, or a later delivery of a
  landed fact counting as anything but a duplicate.
- ingest_refusal_errors: a whole-batch refusal (unknown
  source, unit mismatch, missing as-of, empty delivery) that
  lands a row, states the wrong reason, or fails to verify.
- ingest_correction_errors: a correction chain that does not
  fold to the stated effective value, a stored observation
  whose landed value moved, a correction answering a
  quarantined row landing a fact, or any problem the ingest
  verifier reports over the eval's data plane.
- ingest_backfill_errors: replayed origins missing from the
  series' results or its pooled ledger origins, a replay
  storing a result twice, or a replay artefact the verifier
  flags.

Round 12 counters (forecast-ops analytics, F20-AM1 + planted
shock grading), also zero-tolerance:

- analytics_reperformance_errors: a stored ops report the
  re-performance verifier flags, or a tampered report payload
  it accepts.
- analytics_trend_errors: a trend row whose early/late pooled
  figures, direction or windows disagree with an independent
  recomputation from the stored results, a series with enough
  origins named insufficient, or a ledger pin that does not
  resolve to the ledger of record.
- analytics_signal_outcome_errors: a grid outcome whose
  realised drift, move or verdict disagrees with the observed
  prices, a strikable origin missing its outcome row, an
  engine refusal not named as a skip, or a desk signal graded
  before its horizon landed (or left pending after it did).
- analytics_transmission_errors: a class row whose measurable
  set, error aggregates or verified counts disagree with the
  measurement layer's own verdicts, or a small sample not
  named as such on the row and the report's face.
- analytics_shock_window_errors: a shock row whose day pools
  disagree with an independent split of the stored scored
  days at the event's window, or the planted 2024 export
  ban — never inside a scored window — graded anywhere.

Round 13 counters (operator console, F20-OW2 + F20-OW3 +
F20-OW4 + F20-MF2), also zero-tolerance:

- console_preflight_errors: a pre-flight line whose state,
  age or gap sentence disagrees with an independent
  recomputation from the raw series, a catalogue driver a
  commodity does not report left unnamed on a series of
  that commodity, or a tampered report the re-performance
  verifier accepts.
- console_review_queue_errors: a queue row whose accuracy
  state disagrees with the forecast's pinned attachment,
  rows out of the pack's stated order (degraded, then
  unmeasured, then measured), a prior-official pin that is
  not that series' standing official, or a stated 30-day
  difference that is not the two artefacts' difference.
- console_rejection_errors: a rejected draft that can be
  approved afterwards by any path, stays in the review
  queue, or accepts a second, different rejection act.
- console_triage_errors: an unverified event that does not
  block its drafts' approval, a blocker that names the
  wrong event, a confirmed event that still blocks, a
  retired event applied by a new run, a superseded event
  applied instead of its replacement, or any problem the
  console verifier reports over the eval's console record.
- console_action_parity_errors: an act struck through the
  console's action door (the phone's door) that differs in
  any field from the same act struck through the canonical
  service path on a twin store holding the same artefact.

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
        + list((base / "dashboards").rglob("*.py"))
        + list((base / "signals").rglob("*.py"))
        + list((base / "planning").rglob("*.py"))
        + list((base / "alerts").rglob("*.py"))
        + list((base / "thin").rglob("*.py"))
        + list((base / "intake").rglob("*.py"))
        + list((base / "ingest").rglob("*.py"))
        + list((base / "analytics").rglob("*.py"))
        + list((base / "console").rglob("*.py"))
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
        "dashboard_lineage_errors": 0,
        "dashboard_gap_suppression_errors": 0,
        "dashboard_rerun_diff_errors": 0,
        "dashboard_board_errors": 0,
        "signal_degraded_strong_errors": 0,
        "signal_reperformance_errors": 0,
        "planning_exposure_errors": 0,
        "planning_provenance_errors": 0,
        "planning_ranking_errors": 0,
        "board_foreign_series_errors": 0,
        "alert_orphan_errors": 0,
        "alert_derivation_errors": 0,
        "alert_state_fold_errors": 0,
        "alert_escalation_errors": 0,
        "alert_digest_errors": 0,
        "alert_dedup_errors": 0,
        "thin_tier_overstatement_errors": 0,
        "thin_window_coverage_errors": 0,
        "thin_unnamed_gap_errors": 0,
        "intake_unconfirmed_leakage_errors": 0,
        "intake_self_check_errors": 0,
        "intake_chain_errors": 0,
        "ingest_quarantine_errors": 0,
        "ingest_provenance_errors": 0,
        "ingest_replay_errors": 0,
        "ingest_refusal_errors": 0,
        "ingest_correction_errors": 0,
        "ingest_backfill_errors": 0,
        "analytics_reperformance_errors": 0,
        "analytics_trend_errors": 0,
        "analytics_signal_outcome_errors": 0,
        "analytics_transmission_errors": 0,
        "analytics_shock_window_errors": 0,
        "console_preflight_errors": 0,
        "console_review_queue_errors": 0,
        "console_rejection_errors": 0,
        "console_triage_errors": 0,
        "console_action_parity_errors": 0,
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

    # --- prompt-to-dashboard (R7, Law 6) ----------------------------
    from fmcg_forecast.dashboards.pack import TERMINAL_FACT_KINDS
    from fmcg_forecast.dashboards.service import DashboardService

    dashboard_service = DashboardService(
        store, _OfflineModel(), event_service, sentiment
    )

    # Lineage: assemble a mixed dashboard; every rendered figure
    # must walk to a stored fact through its own artefact, and
    # the stored assembly must verify clean.
    dash_spec = dashboard_service.ask(
        "wheat forecast at delhi and soybean sentiment and "
        "declared events for soybean and the adopted scenario "
        "for soybean at indore",
        "eval.desk",
        _date(2026, 1, 7),
    )
    dash_assembly = dashboard_service.assemble(dash_spec.spec_id, _date(2026, 1, 7))
    if dashboard_service.verify_stored(dash_assembly.assembly_id):
        counters["dashboard_lineage_errors"] += 1
    rendered_figures = 0
    for dash_panel in dash_assembly.panels:
        if dash_panel.state != "rendered":
            continue
        for dash_figure in dash_panel.figures:
            rendered_figures += 1
            walk = dash_figure.lineage
            if (
                not walk
                or dash_figure.artefact_id not in {f.ref for f in walk}
                or not any(f.kind in TERMINAL_FACT_KINDS for f in walk)
            ):
                counters["dashboard_lineage_errors"] += 1
    if rendered_figures == 0:
        counters["dashboard_lineage_errors"] += 1
    # Hypothetical discipline + the adopted scenario renders as adopted.
    adopted_figures = {
        f.key: f.value
        for p in dash_assembly.panels
        for f in p.figures
        if f.key == "view_kind"
    }
    if adopted_figures.get("view_kind") != "adopted_scenario":
        counters["dashboard_lineage_errors"] += 1
    plain_spec = dashboard_service.ask(
        "soybean forecast at indore", "eval.desk", _date(2026, 1, 7)
    )
    if any(p.kind == "scenario_diff" for p in plain_spec.panels):
        counters["dashboard_gap_suppression_errors"] += 1

    # Gap suppression: unstateable clauses stay named gaps from
    # spec to rendered page; an unrun series is a gap, never a
    # number.
    gap_spec = dashboard_service.ask(
        "coffee stock position and wheat rainfall and tea prices",
        "eval.desk",
        _date(2026, 1, 7),
    )
    if sum(1 for p in gap_spec.panels if p.kind == "gap") != 3:
        counters["dashboard_gap_suppression_errors"] += 1
    gap_assembly = dashboard_service.assemble(gap_spec.spec_id, _date(2026, 1, 7))
    if any(p.state != "gap" for p in gap_assembly.panels):
        counters["dashboard_gap_suppression_errors"] += 1
    for gap_panel in gap_assembly.panels:
        if gap_panel.gap_needed not in gap_assembly.html:
            counters["dashboard_gap_suppression_errors"] += 1

    # Re-run diffs: identical re-assembly is the same artefact;
    # a gap that fills in flips on the diff; a new declaration
    # moves the events binding on the diff.
    again = dashboard_service.assemble(dash_spec.spec_id, _date(2026, 1, 8))
    if again.assembly_id != dash_assembly.assembly_id:
        counters["dashboard_rerun_diff_errors"] += 1
    cumin_spec = dashboard_service.ask(
        "cumin forecast at jodhpur", "eval.desk", _date(2026, 1, 7)
    )
    cumin_first = dashboard_service.assemble(cumin_spec.spec_id, _date(2026, 1, 7))
    if cumin_first.panels[0].state != "gap":
        counters["dashboard_rerun_diff_errors"] += 1
    scenario_forecast_service.run_forecast("cumin", "jodhpur")
    cumin_second = dashboard_service.assemble(cumin_spec.spec_id, _date(2026, 1, 8))
    if not any(
        d.kind == "panel_state_changed" and d.before == "gap" and d.after == "rendered"
        for d in cumin_second.diff
    ):
        counters["dashboard_rerun_diff_errors"] += 1
    events_spec = dashboard_service.ask(
        "declared events for groundnut", "eval.desk", _date(2026, 1, 7)
    )
    dashboard_service.assemble(events_spec.spec_id, _date(2026, 1, 7))
    new_groundnut_event = event_service.register_event(
        event_class="export_restriction",
        commodity="groundnut",
        window_start=_date(2026, 3, 1),
        window_end=_date(2026, 3, 31),
        channel="export_flow",
        peak_log_price_effect=0.05,
        basis="announced_measure",
        basis_detail="Export of groundnut oil restricted by a DGFT notification",
        decay_days=15,
        description="Groundnut export restriction for March",
        declared_by="eval.desk",
        declared_on=_date(2026, 1, 8),
    )
    events_second = dashboard_service.assemble(events_spec.spec_id, _date(2026, 1, 9))
    if not any(
        d.kind == "binding_superseded"
        and new_groundnut_event.event_id in (d.after or [])
        for d in events_second.diff
    ):
        counters["dashboard_rerun_diff_errors"] += 1

    # The morning board: exceptions backed by artefacts.
    board = dashboard_service.board(_date(2026, 2, 15))
    board_kinds: dict[str, list] = {}
    for board_row in board.rows:
        board_kinds.setdefault(board_row.kind, []).append(board_row)
    if not any(
        r.commodity == "chili" and r.market == "guntur"
        for r in board_kinds.get("degraded", [])
    ):
        counters["dashboard_board_errors"] += 1
    if not any(
        r.commodity == "coffee" and "stock_level" in r.headline
        for r in board_kinds.get("data_gap", [])
    ):
        counters["dashboard_board_errors"] += 1
    if not any(
        r.artefact_id == eval_tariff.event_id
        for r in board_kinds.get("active_event", [])
    ):
        counters["dashboard_board_errors"] += 1
    if any(
        r.commodity == "wheat"
        for r in board_kinds.get("degraded", []) + board_kinds.get("data_gap", [])
    ):
        counters["dashboard_board_errors"] += 1
    for board_row in board.rows:
        if (
            store.get_forecast(board_row.artefact_id) is None
            and store.get_scenario(board_row.artefact_id) is None
            and store.get_market_event(board_row.artefact_id) is None
        ):
            counters["dashboard_board_errors"] += 1
    if dashboard_service.board(_date(2026, 2, 15)).board_id != board.board_id:
        counters["dashboard_board_errors"] += 1

    # --- buy-window signals + coverage planning (R8, F20-PO2/PO3) ---
    import json as _json
    import sqlite3 as _sqlite3
    from datetime import timedelta as _timedelta

    from fmcg_forecast.forecast.engine import forecast_content_id as _fcid
    from fmcg_forecast.forecast.models import (
        ATTRIBUTION_ORDER as _ATTR,
        AccuracyAttachment as _Attachment,
        BaselineMethod as _Baseline,
        Forecast as _Forecast,
        ForecastDay as _FDay,
        ForecastMethod as _FMethod,
        HorizonAccuracy as _HAcc,
        HorizonSummary as _HSum,
        ResidualMethod as _Resid,
        SparsityMethod as _Spars,
    )
    from fmcg_forecast.models import Observation as _Obs
    from fmcg_forecast.planning.models import PlanLine as _PlanLine
    from fmcg_forecast.planning.service import PlanningService as _Planning
    from fmcg_forecast.planning.verify import (
        verify_assessment as _verify_assessment,
    )
    from fmcg_forecast.signals.service import SignalService as _Signals
    from fmcg_forecast.signals.verify import verify_signal as _verify_signal

    signal_service = _Signals(store)
    planning_service = _Planning(store, signal_service)

    # Every series with a head forecast: the signal re-performs,
    # and the hard caps hold on whatever the engine produced.
    for _series in (
        ("soybean", "indore"),
        ("wheat", "delhi_khari_baoli"),
        ("chili", "guntur"),
        ("coffee", "bengaluru"),
    ):
        _signal = signal_service.compute_for_series(*_series)
        counters["signal_reperformance_errors"] += len(
            _verify_signal(store, _signal)
        )
        if (
            _signal.accuracy_state in ("degraded", "unmeasured")
            and _signal.value == "buy_now"
        ):
            counters["signal_degraded_strong_errors"] += 1

    # Hand-computed fixtures on a synthetic series (the store
    # takes any series key; the signal engine never consults the
    # catalogue): spot 2000, flat path to P50 2100 at 30 days.
    def _fixture_forecast(_state):
        _days = [
            _FDay(
                forecast_date=_date(2025, 12, 31) + _timedelta(days=i + 1),
                baseline=2100.0, contributions={}, events_adjustment=0.0,
                p10=2010.0, p50=2100.0, p90=2190.0,
            )
            for i in range(90)
        ]
        _slices = [
            _HAcc(
                horizon_days=h,
                state=(
                    "degraded" if (_state == "degraded" and h == 30)
                    else "measured"
                ),
                record_id=f"ACC-EVAL-{h}", n_origins=6, mae=42.0,
                mape=7.5 if (_state == "degraded" and h == 30) else 2.0,
                bias=1.0, coverage=0.9,
            )
            for h in (7, 30, 90)
        ]
        _forecast = _Forecast(
            forecast_id="FCST-pending", commodity="fixture_grain",
            market="fixture_market", as_of=_date(2025, 12, 31),
            engine_version="eval-fixture",
            method=_FMethod(
                engine_version="eval-fixture",
                baseline=_Baseline(
                    intercept=0.0, trend_per_year=0.0, seasonal_sin=0.0,
                    seasonal_cos=0.0, anchor_date=_date(2025, 12, 31),
                    n_obs=300,
                ),
                drivers={},
                residuals=_Resid(
                    sigma=0.01, rho=0.0, q10=-0.01, q90=0.01,
                    window_obs=300,
                ),
                sparsity=_Spars(
                    observed_days=300, calendar_days=300, multiplier=1.0
                ),
                attribution_order=list(_ATTR),
            ),
            days=_days, lines=[],
            horizons_summary=[
                _HSum(
                    horizon_days=h,
                    forecast_date=_days[h - 1].forecast_date,
                    baseline=2100.0, contributions={},
                    events_adjustment=0.0, p10=2010.0, p50=2100.0,
                    p90=2190.0,
                )
                for h in (7, 30, 90)
            ],
            missing_drivers=[],
            accuracy=_Attachment(
                state=_state, pack_version="2026.10.1",
                per_horizon=_slices, note="eval fixture",
            ),
        )
        return _forecast.model_copy(
            update={"forecast_id": _fcid(_forecast)}
        )

    store.insert_observations(
        [
            _Obs(
                commodity="fixture_grain", market="fixture_market",
                obs_date=_date(2025, 12, 31), driver="modal_price",
                value=2000.0,
            )
        ]
    )
    _rising = _fixture_forecast("measured")
    store.insert_forecast(_rising)
    _sig = signal_service.compute_for_forecast(_rising)
    if not (
        _sig.drift_pct == 5.0
        and _sig.band_width_pct == 8.5714
        and _sig.value == "buy_now"
        and _verify_signal(store, _sig) == []
    ):
        counters["signal_reperformance_errors"] += 1
    _degraded_fx = _fixture_forecast("degraded")
    store.insert_forecast(_degraded_fx)
    _sig = signal_service.compute_for_forecast(_degraded_fx)
    if not (
        _sig.base_value == "buy_now"
        and _sig.value == "phased"
        and _sig.caps_applied == ["degraded_accuracy"]
    ):
        counters["signal_degraded_strong_errors"] += 1

    # The planner: a desk plan on soybean/indore, assessed on the
    # official forecast and on the adopted scenario's fork.
    _plan = planning_service.enter_plan(
        commodity="soybean", market="indore", entered_by="eval.desk",
        entered_on=_date(2026, 1, 5), opening_stock_tonnes=50.0,
        lines=[
            _PlanLine(month=_date(2026, 1, 1), required_tonnes=120.0),
            _PlanLine(month=_date(2026, 2, 1), required_tonnes=120.0),
            _PlanLine(month=_date(2026, 3, 1), required_tonnes=120.0),
        ],
    )
    _assessment = planning_service.assess(_plan.plan_id)
    counters["planning_exposure_errors"] += len(
        _verify_assessment(store, _assessment)
    )
    _expected_order = sorted(
        _assessment.options,
        key=lambda o: (o.cost_at_p50_inr, o.cost_at_p90_inr, o.name),
    )
    if [o.name for o in _assessment.options] != [
        o.name for o in _expected_order
    ] or [o.rank for o in _assessment.options] != [1, 2, 3]:
        counters["planning_ranking_errors"] += 1
    for _figure in _assessment.figures:
        _kinds = [f.kind for f in _figure.lineage]
        if _figure.basis == "desk" and _kinds != ["desk_entered"]:
            counters["planning_provenance_errors"] += 1
        elif _figure.basis == "market" and "desk_entered" in _kinds:
            counters["planning_provenance_errors"] += 1
        elif _figure.basis == "mixed" and _kinds.count("desk_entered") != 1:
            counters["planning_provenance_errors"] += 1
    try:
        _scenario_assessment = planning_service.assess(
            _plan.plan_id, basis="adopted_scenario"
        )
        counters["planning_exposure_errors"] += len(
            _verify_assessment(store, _scenario_assessment)
        )
        if _scenario_assessment.scenario_id is None:
            counters["planning_exposure_errors"] += 1
    except Exception:
        counters["planning_exposure_errors"] += 1

    # A tampered exposure figure must be caught.
    _conn = _sqlite3.connect(str(tmp / "evals.db"))
    _payload = _json.loads(
        _conn.execute(
            "SELECT payload FROM coverage_assessments "
            "WHERE assessment_id = ?",
            (_assessment.assessment_id,),
        ).fetchone()[0]
    )
    _payload["total_exposure_inr"] += 1.0
    _conn.execute(
        "UPDATE coverage_assessments SET payload = ? "
        "WHERE assessment_id = ?",
        (_json.dumps(_payload), _assessment.assessment_id),
    )
    _conn.commit()
    _conn.close()
    _tampered = store.get_coverage_assessment(_assessment.assessment_id)
    if not _verify_assessment(store, _tampered):
        counters["planning_exposure_errors"] += 1

    # Market provenance stays market: a fresh dashboard assembled
    # after plans exist carries no desk-entered fact anywhere.
    _spec = dashboard_service.ask(
        "soybean forecast at indore", "eval.desk", _date(2026, 1, 9)
    )
    _assembly = dashboard_service.assemble(_spec.spec_id, _date(2026, 1, 9))
    _appendix = dashboard_service.appendix(_assembly.assembly_id)
    for _panel in _appendix["panels"]:
        for _figure in _panel["figures"]:
            if any(
                fact["kind"] == "desk_entered"
                for fact in _figure["lineage"]
            ):
                counters["planning_provenance_errors"] += 1

    # The board, rebuilt now that signals exist: signal rows are
    # backed by signal artefacts that resolve in the store.
    _board2 = dashboard_service.board(_date(2026, 2, 15))
    for _row in _board2.rows:
        if _row.kind == "signal" and (
            store.get_buy_signal(_row.artefact_id) is None
        ):
            counters["signal_reperformance_errors"] += 1

    # The board names the fixture series' pending gates as
    # recorded: both hand-computed fixture forecasts are draft
    # artefacts from a series outside the catalogue, and each
    # must appear as a pending-gate row badged not_in_catalogue.
    _fixture_rows = [
        _row for _row in _board2.rows
        if _row.kind == "pending_gate"
        and _row.commodity == "fixture_grain"
    ]
    if {_row.artefact_id for _row in _fixture_rows} != {
        _rising.forecast_id, _degraded_fx.forecast_id
    } or any(
        _row.figures.get("catalogue") != "not_in_catalogue"
        for _row in _fixture_rows
    ):
        counters["board_foreign_series_errors"] += 1

    # --- alerting, subscriptions and escalation (R9, F20-AL1/AL2/AL3) ---
    from datetime import datetime as _datetime

    from fmcg_forecast.alerts.engine import (
        compute_crossings as _compute_crossings,
    )
    from fmcg_forecast.alerts.engine import fold_state as _fold_state
    from fmcg_forecast.alerts.pack import load_alert_pack as _load_alert_pack
    from fmcg_forecast.alerts.service import AlertService as _AlertService
    from fmcg_forecast.alerts.verify import (
        verify_alert as _verify_alert,
    )
    from fmcg_forecast.alerts.verify import (
        verify_alert_set as _verify_alert_set,
    )
    from fmcg_forecast.alerts.verify import verify_digest as _verify_digest

    _alert_pack = _load_alert_pack()
    _alerting = _AlertService(store, _alert_pack)

    # A planted price step on the fixture series: 2000 flat, then
    # 2240 from day 21 — one 7-day crossing of +12.0% at the step.
    # The R8 fixture's own spot observation (2000 on 2025-12-31)
    # then steps the series back down: a second crossing of
    # -10.7143% at the year end. Both are graded exactly.
    _step_start = _date(2025, 12, 1)
    store.insert_observations(
        [
            _Obs(
                commodity="fixture_grain", market="fixture_market",
                obs_date=_step_start + _timedelta(days=i),
                driver="modal_price",
                value=2000.0 if i < 20 else 2240.0,
            )
            for i in range(30)
        ]
    )
    _fixture_crossings = sorted(
        (
            c for c in _compute_crossings(store, _alert_pack)
            if c.commodity == "fixture_grain"
        ),
        key=lambda c: c.to_date,
    )
    if [c.move_pct for c in _fixture_crossings] != [12.0, -10.7143]:
        counters["alert_derivation_errors"] += 1

    _eval_sub = _alerting.enter_subscription(
        subscriber="eval.desk", role="desk_head",
        entered_on=_date(2025, 1, 1), commodities=[], markets=[],
        kinds=[
            "buy_signal", "event_window", "price_move",
            "accuracy_degraded", "coverage_collapse",
        ],
        min_severity="minor",
    )
    _T0 = _datetime(2026, 1, 5, 9, 0)
    _sweep1 = _alerting.sweep(_T0)
    _alerts_after_first = len(_alerting.list_alerts())
    _sweep2 = _alerting.sweep(_T0 + _timedelta(hours=1))
    if (
        _sweep2["alerts_raised_count"] != 0
        or len(_alerting.list_alerts()) != _alerts_after_first
    ):
        counters["alert_dedup_errors"] += 1

    # Each fixture crossing raised exactly one alert.
    _fixture_move_alerts = [
        a for a in _alerting.list_alerts(commodity="fixture_grain")
        if a.kind == "price_move"
    ]
    if len(_fixture_move_alerts) != 2 or any(
        a.severity != "critical" for a in _fixture_move_alerts
    ):
        counters["alert_derivation_errors"] += 1

    # Every stored alert re-performs; orphans and derivation
    # disagreements are counted separately.
    from fmcg_forecast.alerts.engine import (
        derive_candidates as _derive_candidates,
    )

    _candidates = _derive_candidates(store, _alert_pack)
    for _alert in _alerting.list_alerts():
        for _problem in _verify_alert(store, _alert, _candidates):
            if "orphan" in _problem:
                counters["alert_orphan_errors"] += 1
            else:
                counters["alert_derivation_errors"] += 1
    for _problem in _verify_alert_set(store, _alert_pack):
        if "episode" in _problem or "content id mismatch" in _problem:
            counters["alert_state_fold_errors"] += 1
        elif "orphan" in _problem:
            counters["alert_orphan_errors"] += 1
        else:
            counters["alert_derivation_errors"] += 1

    # The sweep's unmatched account reconciles with the alerts of
    # record: a struck signal is either alerted under some
    # subscription or named unmatched — never silently dropped.
    _alerted_signals = {
        a.trigger_id
        for a in _alerting.list_alerts()
        if a.kind == "buy_signal"
    }
    _expected_unmatched = {
        s.signal_id
        for s in store.list_buy_signals()
        if s.signal_id not in _alerted_signals
    }
    if set(_sweep1["unmatched_signal_ids"]) != _expected_unmatched:
        counters["alert_derivation_errors"] += 1

    # Degradation: one alert per degraded record on the ledger.
    _degraded_records = [
        r for r in store.list_accuracy_records() if r.degraded
    ]
    _degraded_alerts = [
        a
        for a in _alerting.list_alerts(
            subscription_id=_eval_sub.subscription_id
        )
        if a.kind == "accuracy_degraded"
    ]
    if len(_degraded_alerts) != len(_degraded_records):
        counters["alert_state_fold_errors"] += 1

    # The escalation clock on a fixture timeline: an
    # unacknowledged degraded alert (major — windows 24h, 72h)
    # climbs at the stated times; an acknowledged signal alert
    # never climbs.
    if _degraded_alerts:
        _esc_alert = _degraded_alerts[0]
        _at_25h = _fold_state(
            _esc_alert, [], _T0 + _timedelta(hours=25), _alert_pack
        )
        _at_97h = _fold_state(
            _esc_alert, [], _T0 + _timedelta(hours=97), _alert_pack
        )
        if not (
            _at_25h["state"] == "escalated"
            and _at_25h["escalation_level"] == 1
            and _at_25h["current_holder"] == "desk_head"
            and _at_97h["escalation_level"] == 2
            and _at_97h["current_holder"] == "procurement_lead"
        ):
            counters["alert_escalation_errors"] += 1
    _signal_alerts = [
        a
        for a in _alerting.list_alerts(
            subscription_id=_eval_sub.subscription_id
        )
        if a.kind == "buy_signal" and a.commodity == "soybean"
    ]
    if _signal_alerts:
        _ack_alert = _signal_alerts[0]
        _alerting.acknowledge(
            _ack_alert.alert_id, actor="eval.desk", role="desk_head",
            acted_at=_T0 + _timedelta(hours=2),
        )
        _folded = _fold_state(
            _ack_alert,
            store.list_alert_acts(_ack_alert.alert_id),
            _T0 + _timedelta(days=30),
            _alert_pack,
        )
        if _folded["state"] != "acknowledged":
            counters["alert_escalation_errors"] += 1

    # The digest carries exactly the subscriber's day.
    _digest = _alerting.build_digest(
        _eval_sub.subscription_id, _date(2026, 1, 5)
    )
    counters["alert_digest_errors"] += len(_verify_digest(store, _digest))
    _expected_digest = sorted(
        a.alert_id
        for a in _alerting.list_alerts(
            subscription_id=_eval_sub.subscription_id
        )
        if a.raised_on == _date(2026, 1, 5)
    )
    if _digest.alert_ids != _expected_digest:
        counters["alert_digest_errors"] += 1

    # --- thin data & assisted intake (R10, Law 7 depth + F20-DI3) -----
    from fmcg_forecast.dashboards.assemble import (
        head_forecast as _head_forecast,
    )
    from fmcg_forecast.intake.service import (
        IntakeService as _IntakeService,
    )
    from fmcg_forecast.intake.service import (
        IntakeValidationError as _IntakeValidationError,
    )
    from fmcg_forecast.thin.engine import (
        operating_days as _thin_operating_days,
    )
    from fmcg_forecast.thin.pack import (
        load_thin_data_pack as _load_thin_pack,
    )
    from fmcg_forecast.thin.service import ThinDataService as _ThinService
    from fmcg_forecast.thin.verify import (
        verify_assessment as _verify_thin,
    )

    _thin = _ThinService(store, _load_thin_pack())

    # Every graded series' head assessment re-performs, and its
    # windows recompute independently from the observation
    # store — operating pattern, observed days, named misses.
    for _series in (
        ("wheat", "delhi_khari_baoli"),
        ("groundnut", "rajkot"),
        ("coffee", "bengaluru"),
        ("chili", "guntur"),
    ):
        _head = _head_forecast(store, *_series)
        if _head is None:
            counters["thin_window_coverage_errors"] += 1
            continue
        _assessment = _thin.assess_forecast(_head.forecast_id)
        for _problem in _verify_thin(store, _assessment):
            if "tier overstatement" in _problem:
                counters["thin_tier_overstatement_errors"] += 1
            else:
                counters["thin_window_coverage_errors"] += 1
        _spec = BY_NAME[_series[0]]
        _price_dates = {
            r.obs_date
            for r in store.series(
                _series[0], _series[1], "modal_price", None, _head.as_of
            )
        }
        for _w in _assessment.windows:
            _expected = _thin_operating_days(_spec, _w.start, _w.end)
            _observed = [d for d in _expected if d in _price_dates]
            _missing = [d for d in _expected if d not in _price_dates]
            if (
                _w.operating_days != len(_expected)
                or _w.observed_days != len(_observed)
                or _w.missing_operating_dates != _missing
            ):
                counters["thin_window_coverage_errors"] += 1

    # Coffee: every unreported driver is named on the
    # assessment and on the morning board's gap row, and the
    # 365-day window names exactly the planted disruption days.
    _coffee_head = _head_forecast(store, "coffee", "bengaluru")
    _coffee_thin = _thin.assess_forecast(_coffee_head.forecast_id)
    for _driver in ("stock_level", "import_flow", "export_flow"):
        if not any(
            g.startswith(f"{_driver}:") for g in _coffee_thin.named_gaps
        ):
            counters["thin_unnamed_gap_errors"] += 1
    _year = next(w for w in _coffee_thin.windows if w.window_days == 365)
    if len(_year.missing_operating_dates) != (
        manifest.coffee_disruption_reporting_days_lost
    ):
        counters["thin_window_coverage_errors"] += 1
    _coffee_rows = [
        r for r in board.rows
        if r.kind == "data_gap" and r.commodity == "coffee"
    ]
    if not _coffee_rows or not all(
        d in _coffee_rows[0].headline
        for d in ("stock_level", "import_flow", "export_flow")
    ):
        counters["thin_unnamed_gap_errors"] += 1

    # Groundnut: the not-estimable sentiment driver is named.
    _groundnut_head = _head_forecast(store, "groundnut", "rajkot")
    _groundnut_thin = _thin.assess_forecast(_groundnut_head.forecast_id)
    if not any(
        g.startswith("sentiment:") for g in _groundnut_thin.named_gaps
    ):
        counters["thin_unnamed_gap_errors"] += 1

    # Tier claims: overstating coffee is a contradiction the
    # claim verifier must refuse; the earned tier must pass.
    if not _thin.verify_claim(_coffee_head.forecast_id, 30, "established"):
        counters["thin_tier_overstatement_errors"] += 1
    _coffee_30 = next(
        h for h in _coffee_thin.horizons if h.horizon_days == 30
    )
    if _thin.verify_claim(_coffee_head.forecast_id, 30, _coffee_30.tier):
        counters["thin_tier_overstatement_errors"] += 1

    # Assisted intake on two Monday keys (no generated coffee
    # row stands on a Monday): pending is invisible, the
    # self-check is refused, confirmation lands exactly one
    # fact, rejection lands nothing.
    _intake = _IntakeService(store)
    _entry = _intake.enter(
        commodity="coffee", market="bengaluru",
        obs_date=_date(2025, 12, 29), driver="modal_price",
        value=34100.0, entered_by="eval.assist",
        entered_by_role="desk_assistant",
        entered_at=_datetime(2025, 12, 29, 18, 0),
        source_note="eval fixture: phoned in by the market contact",
    )
    if store.series(
        "coffee", "bengaluru", "modal_price",
        _date(2025, 12, 29), _date(2025, 12, 29),
    ):
        counters["intake_unconfirmed_leakage_errors"] += 1
    try:
        _intake.confirm(
            _entry.entry_id, checker="eval.assist",
            checker_role="desk_head",
            acted_at=_datetime(2025, 12, 29, 18, 30),
        )
        counters["intake_self_check_errors"] += 1
    except _IntakeValidationError:
        pass
    if _intake.entry_state(_entry.entry_id) != "pending":
        counters["intake_self_check_errors"] += 1
    _intake.confirm(
        _entry.entry_id, checker="eval.checker",
        checker_role="desk_head",
        acted_at=_datetime(2025, 12, 29, 19, 0),
    )
    _landed = store.series(
        "coffee", "bengaluru", "modal_price",
        _date(2025, 12, 29), _date(2025, 12, 29),
    )
    if len(_landed) != 1 or _landed[0].value != 34100.0:
        counters["intake_chain_errors"] += 1
    _rejected = _intake.enter(
        commodity="coffee", market="bengaluru",
        obs_date=_date(2025, 12, 22), driver="modal_price",
        value=33800.0, entered_by="eval.assist",
        entered_by_role="desk_assistant",
        entered_at=_datetime(2025, 12, 22, 18, 0),
        source_note="eval fixture: phoned in by the market contact",
    )
    _intake.reject(
        _rejected.entry_id, checker="eval.checker",
        checker_role="desk_head",
        acted_at=_datetime(2025, 12, 22, 19, 0),
    )
    if store.series(
        "coffee", "bengaluru", "modal_price",
        _date(2025, 12, 22), _date(2025, 12, 22),
    ):
        counters["intake_unconfirmed_leakage_errors"] += 1
    counters["intake_chain_errors"] += len(_intake.verify_all())

    # --- production data plane (R11, F20-DI1/DI2/DI4) ------------------
    import sqlite3 as _sqlite3

    from fmcg_forecast.ingest.service import (
        IngestService as _IngestService,
    )
    from fmcg_forecast.ingest.verify import (
        verify_batch as _verify_ingest_batch,
    )
    from fmcg_forecast.ingest.verify import (
        verify_replay as _verify_replay,
    )

    _ingest = _IngestService(store)
    _header = "commodity,market,obs_date,driver,value,unit"
    _fixture_csv = "\n".join(
        [
            _header,
            "coffee,bengaluru,2025-12-31,modal_price,34100,INR/quintal",
            "coffee,bengaluru,2025-12-31,arrivals,2600,quintal/day",
            "coffee,bengaluru,2025-12-31,modal_price,34100,INR/quintal",
            "coffee,bengaluru,2025-12-24,arrivals,-50,quintal/day",
            "coffee,bengaluru,2026-03-02,modal_price,35000,INR/quintal",
            "coffee,bengaluru,2025-12-29,stock_level,80,index (0-160)",
            "tea,bengaluru,2025-12-29,modal_price,100,INR/quintal",
            "coffee,chennai,2025-12-29,modal_price,34000,INR/quintal",
            "coffee,bengaluru,2025-12-30,modal_price,99999,INR/quintal",
            "coffee,bengaluru,2025-12-24,modal_price,33900,INR/quintal",
            "coffee,bengaluru,2025-12-24,modal_price,34050,INR/quintal",
        ]
    )
    _batch = _ingest.load_file_drop(
        "agmarknet_file_drop", _fixture_csv, as_of=_date(2026, 1, 5),
        received_by="eval.desk", received_at=_datetime(2026, 1, 5, 9, 0),
    )
    if (_batch.rows_received, _batch.rows_loaded,
            _batch.rows_quarantined, _batch.rows_duplicate) != (11, 2, 8, 1):
        counters["ingest_quarantine_errors"] += 1
    _expected_reasons = {
        3: ["value_out_of_range"],
        4: ["future_date"],
        5: ["driver_not_reported"],
        6: ["unknown_commodity"],
        7: ["unknown_market"],
        8: ["conflicts_with_landed"],
        9: ["duplicate_conflicting"],
        10: ["duplicate_conflicting"],
    }
    _actual_reasons = {
        r.row_index: r.reasons
        for r in _ingest.list_quarantine(batch_id=_batch.batch_id)
    }
    if _actual_reasons != _expected_reasons:
        counters["ingest_quarantine_errors"] += 1
    # zero quarantined rows reached the observations table
    if store.series("coffee", "bengaluru", "modal_price",
                    _date(2025, 12, 24), _date(2025, 12, 24)):
        counters["ingest_quarantine_errors"] += 1
    if store.series("coffee", "bengaluru", "arrivals",
                    _date(2025, 12, 24), _date(2025, 12, 24)):
        counters["ingest_quarantine_errors"] += 1

    # provenance: exactly the landed rows, naming batch and source
    _prov = store.list_provenance(batch_id=_batch.batch_id)
    if len(_prov) != 2 or {p.source_id for p in _prov} != {"agmarknet_file_drop"}:
        counters["ingest_provenance_errors"] += 1
    if {p.row_index for p in _prov} != {0, 1}:
        counters["ingest_provenance_errors"] += 1

    # replay: the same delivery is the same artefact, landing nothing twice
    _coffee_prices_before = len(store.series("coffee", "bengaluru", "modal_price"))
    _replay_batch = _ingest.load_file_drop(
        "agmarknet_file_drop", _fixture_csv, as_of=_date(2026, 1, 5),
        received_by="eval.desk", received_at=_datetime(2026, 1, 6, 9, 0),
    )
    if _replay_batch.batch_id != _batch.batch_id:
        counters["ingest_replay_errors"] += 1
    if len(store.series("coffee", "bengaluru", "modal_price")) != _coffee_prices_before:
        counters["ingest_replay_errors"] += 1

    # API push: per-row provenance is the price of admission
    _push = _ingest.load_api_push(
        "mandi_api_push",
        [
            {"commodity": "coffee", "market": "bengaluru",
             "obs_date": "2025-12-28", "driver": "modal_price",
             "value": 34300, "unit": "INR/quintal",
             "source": "mandi_api_push", "as_of": "2026-01-05"},
            {"commodity": "coffee", "market": "bengaluru",
             "obs_date": "2025-12-31", "driver": "arrivals",
             "value": 2500, "unit": "quintal/day", "as_of": "2026-01-05"},
            {"commodity": "coffee", "market": "bengaluru",
             "obs_date": "2025-12-28", "driver": "arrivals",
             "value": 2300, "unit": "quintal/day",
             "source": "mandi_api_push", "as_of": "2026-01-04"},
        ],
        as_of=_date(2026, 1, 5), received_by="eval.feed",
        received_at=_datetime(2026, 1, 5, 9, 30),
    )
    if (_push.rows_loaded, _push.rows_quarantined) != (1, 2):
        counters["ingest_quarantine_errors"] += 1
    if {
        r.row_index: r.reasons
        for r in _ingest.list_quarantine(batch_id=_push.batch_id)
    } != {1: ["missing_provenance"], 2: ["missing_provenance"]}:
        counters["ingest_quarantine_errors"] += 1

    # whole-batch refusals: recorded, reasoned, and landing nothing
    _prices_before_refusals = len(store.series("coffee", "bengaluru", "modal_price"))
    for _text, _as_of, _source, _reason in (
        (_fixture_csv, _date(2026, 1, 5), "no_such_source", "unknown_source"),
        (_fixture_csv.replace("INR/quintal", "INR/kg"),
         _date(2026, 1, 5), "agmarknet_file_drop", "unit_mismatch"),
        (_fixture_csv, None, "agmarknet_file_drop", "batch_missing_provenance"),
        (_header, _date(2026, 1, 5), "agmarknet_file_drop", "empty_batch"),
    ):
        _refused = _ingest.load_file_drop(
            _source, _text, as_of=_as_of, received_by="eval.desk",
            received_at=_datetime(2026, 1, 5, 10, 0),
        )
        if _refused.status != "refused" or _refused.refusal_reason != _reason:
            counters["ingest_refusal_errors"] += 1
        if _verify_ingest_batch(store, _refused):
            counters["ingest_refusal_errors"] += 1
    if len(store.series("coffee", "bengaluru", "modal_price")) != _prices_before_refusals:
        counters["ingest_refusal_errors"] += 1

    # corrections: the fold is the effective fact; history stands
    _c1 = _ingest.correct(
        "coffee", "bengaluru", _date(2025, 12, 31), "modal_price", 34250.0,
        reason="transcription slip in the phoned figure",
        corrected_by="eval.head", corrected_by_role="desk_head",
        corrected_at=_datetime(2026, 1, 5, 11, 0),
    )
    _c2 = _ingest.correct(
        "coffee", "bengaluru", _date(2025, 12, 31), "modal_price", 34300.0,
        reason="the market contact corrected the correction",
        corrected_by="eval.head", corrected_by_role="desk_head",
        corrected_at=_datetime(2026, 1, 5, 12, 0),
    )
    if _c2.supersedes_correction_id != _c1.correction_id:
        counters["ingest_correction_errors"] += 1
    _effective = _ingest.effective_fact(
        "coffee", "bengaluru", _date(2025, 12, 31), "modal_price"
    )
    if (
        _effective["state"] != "corrected"
        or _effective["landed_value"] != 34100.0
        or _effective["effective_value"] != 34300.0
    ):
        counters["ingest_correction_errors"] += 1
    _landed = store.series("coffee", "bengaluru", "modal_price",
                           _date(2025, 12, 31), _date(2025, 12, 31))
    if len(_landed) != 1 or _landed[0].value != 34100.0:
        counters["ingest_correction_errors"] += 1
    _q3 = next(
        r for r in _ingest.list_quarantine(batch_id=_batch.batch_id)
        if r.row_index == 3
    )
    _ingest.correct(
        "coffee", "bengaluru", _date(2025, 12, 24), "arrivals", 2450.0,
        reason="the minus was a stray keystroke on the phoned figure",
        corrected_by="eval.head", corrected_by_role="desk_head",
        corrected_at=_datetime(2026, 1, 5, 12, 30),
        corrects_quarantine_id=_q3.quarantine_id,
    )
    _q_effective = _ingest.effective_fact(
        "coffee", "bengaluru", _date(2025, 12, 24), "arrivals"
    )
    if _q_effective["state"] != "quarantine_corrected":
        counters["ingest_correction_errors"] += 1
    if store.series("coffee", "bengaluru", "arrivals",
                    _date(2025, 12, 24), _date(2025, 12, 24)):
        counters["ingest_correction_errors"] += 1
    counters["ingest_correction_errors"] += len(_ingest.verify_all())

    # backfill replay: origins after the grid's last earn
    # their place in the series' results and its pooled
    # ledger (the pack pools the most recent six origins, so
    # the replayed origins must postdate the grid's)
    _replay = _ingest.replay_backtests(
        "cumin", "unjha",
        [_date(2025, 10, 15), _date(2025, 11, 15), _date(2025, 12, 15)],
        replayed_by="eval.desk", replayed_at=_datetime(2026, 1, 5, 13, 0),
    )
    if _replay.results_stored != 9 or _replay.skipped:
        counters["ingest_backfill_errors"] += 1
    _record30 = store.get_accuracy_record("cumin", "unjha", 30)
    if _record30 is None or _date(2025, 12, 15) not in _record30.origins:
        counters["ingest_backfill_errors"] += 1
    if _verify_replay(store, _replay):
        counters["ingest_backfill_errors"] += 1
    _replay2 = _ingest.replay_backtests(
        "cumin", "unjha",
        [_date(2025, 10, 15), _date(2025, 11, 15), _date(2025, 12, 15)],
        replayed_by="eval.desk", replayed_at=_datetime(2026, 1, 5, 14, 0),
    )
    if _replay2.results_stored != 0 or _replay2.results_already_on_record != 9:
        counters["ingest_backfill_errors"] += 1

    # tamper: a quarantine record altered in place is caught
    _conn = _sqlite3.connect(str(tmp / "evals.db"))
    _payload = _json.loads(
        _conn.execute(
            "SELECT payload FROM ingest_quarantine WHERE quarantine_id = ?",
            (_q3.quarantine_id,),
        ).fetchone()[0]
    )
    _payload["reasons"] = ["future_date"]
    _conn.execute(
        "UPDATE ingest_quarantine SET payload = ? WHERE quarantine_id = ?",
        (_json.dumps(_payload), _q3.quarantine_id),
    )
    _conn.commit()
    _conn.close()
    if not _verify_ingest_batch(store, _batch):
        counters["ingest_quarantine_errors"] += 1

    # --- forecast-ops analytics (R12, F20-AM1 + shock grading) -----------
    from fmcg_forecast.analytics.service import (
        AnalyticsService as _AnalyticsService,
    )
    from fmcg_forecast.analytics.verify import (
        verify_report as _verify_ops_report,
    )
    from fmcg_forecast.backtest import metrics as _ametrics
    from fmcg_forecast.events.measure import (
        measure_event_effect as _measure_event,
    )
    from fmcg_forecast.events.pack import (
        load_event_pack as _load_event_pack,
    )

    _analytics = _AnalyticsService(store)
    _ops = _analytics.build_report()

    # trends: every row re-pooled independently from the
    # stored results, by the ledger's own pooling rule
    def _pool_sums(_rs):
        _se = round(sum(r.sum_err for r in _rs), _ametrics.SUM_DP)
        _sae = round(sum(r.sum_abs_err for r in _rs), _ametrics.SUM_DP)
        _sap = round(sum(r.sum_abs_pct for r in _rs), _ametrics.SUM_DP)
        _cov = sum(r.covered_days for r in _rs)
        _n = sum(r.n_days for r in _rs)
        return _ametrics._derive(_se, _sae, _sap, _cov, _n)

    for _row in _ops.trends:
        _results = sorted(
            store.list_backtest_results(
                _row.commodity, _row.market, _row.horizon_days
            ),
            key=lambda r: r.origin,
        )
        if len(_results) != _row.n_results:
            counters["analytics_trend_errors"] += 1
            continue
        _record = store.get_accuracy_record(
            _row.commodity, _row.market, _row.horizon_days
        )
        if (_record.record_id if _record else None) != _row.ledger_record_id:
            counters["analytics_trend_errors"] += 1
        if len(_results) < 6:
            if (
                _row.direction != "insufficient_history"
                or _row.delta_mape_pp is not None
                or _row.early_origins or _row.late_origins
            ):
                counters["analytics_trend_errors"] += 1
            continue
        _early = _pool_sums(_results[:3])
        _late = _pool_sums(_results[-3:])
        _delta = round(_late["mape"] - _early["mape"], 4)
        _direction = (
            "worsening" if _delta > 0.25
            else "improving" if _delta < -0.25
            else "steady"
        )
        if (
            _row.direction != _direction
            or _row.early_mape != _early["mape"]
            or _row.late_mape != _late["mape"]
            or _row.delta_mape_pp != _delta
            or _row.early_origins != [r.origin for r in _results[:3]]
            or _row.late_origins != [r.origin for r in _results[-3:]]
        ):
            counters["analytics_trend_errors"] += 1

    # signal outcomes: every row re-measured against the
    # observed prices inside its own horizon window
    def _check_outcome(_row):
        _window = store.series(
            _row.commodity, _row.market, "modal_price",
            _row.as_of + timedelta(days=1),
            _row.as_of + timedelta(days=_row.horizon_days),
        )
        if not _window:
            return (
                _row.state == "pending"
                and _row.favourable is None
                and _row.move is None
            )
        _realised = _window[-1]
        _drift = round(
            (float(_realised.value) - _row.spot_inr) / _row.spot_inr * 100, 4
        )
        _move = (
            "rose" if _drift >= 2.0
            else "fell" if _drift <= -2.0
            else "flat"
        )
        _fav = (
            _move == "rose" if _row.value == "buy_now"
            else _move in ("rose", "flat") if _row.value == "phased"
            else _move in ("fell", "flat")
        )
        return (
            _row.state == "graded"
            and _row.realised_date == _realised.obs_date
            and _row.realised_drift_pct == _drift
            and _row.drift_error_pct == round(_drift - _row.predicted_drift_pct, 4)
            and _row.move == _move
            and _row.favourable == _fav
        )

    _grid_rows = [
        r for r in _ops.signal_outcomes if r.population == "backtest_grid"
    ]
    _desk_rows = [
        r for r in _ops.signal_outcomes if r.population == "desk"
    ]
    if len(_grid_rows) != 135:
        counters["analytics_signal_outcome_errors"] += 1
    if len(_ops.origin_signal_skips) != 5 or {
        s.commodity for s in _ops.origin_signal_skips
    } != {"coffee"}:
        counters["analytics_signal_outcome_errors"] += 1
    if len(_desk_rows) != len(store.list_buy_signals()):
        counters["analytics_signal_outcome_errors"] += 1
    for _row in _ops.signal_outcomes:
        if not _check_outcome(_row):
            counters["analytics_signal_outcome_errors"] += 1

    # transmission: every class row re-measured through the
    # events layer's own measurement
    _epack = _load_event_pack()
    for _row in _ops.transmission:
        _members = [
            e for e in store.list_market_events()
            if e.event_class == _row.event_class
        ]
        _verdicts = [(e, _measure_event(store, e, _epack)) for e in _members]
        _meas = [
            (e, v) for e, v in _verdicts
            if v.status != "not_measurable" and v.measured_log_effect is not None
        ]
        if (
            _row.n_events != len(_members)
            or _row.n_measurable != len(_meas)
            or _row.measurable_event_ids != [e.event_id for e, _ in _meas]
            or _row.verified_count
            != sum(1 for _, v in _meas if v.status == "verified")
            or _row.unverified_count
            != sum(1 for _, v in _meas if v.status == "unverified")
        ):
            counters["analytics_transmission_errors"] += 1
            continue
        if _meas:
            _signed = [
                round(
                    v.measured_log_effect
                    - e.transmission.peak_log_price_effect,
                    4,
                )
                for e, v in _meas
            ]
            if _row.mean_signed_error != round(sum(_signed) / len(_signed), 4):
                counters["analytics_transmission_errors"] += 1
            if _row.mean_abs_error != round(
                sum(abs(s) for s in _signed) / len(_signed), 4
            ):
                counters["analytics_transmission_errors"] += 1
        _expected_state = (
            "no_measurable_events" if not _meas
            else "small_sample" if len(_meas) < 3
            else "evidence"
        )
        if _row.sample_state != _expected_state:
            counters["analytics_transmission_errors"] += 1
    if not {
        "tariff_change", "export_restriction", "weather_shock"
    } <= set(_ops.small_sample_classes):
        counters["analytics_transmission_errors"] += 1

    # shock windows: every row's pools re-split independently
    # from the stored scored days at the event's window
    for _row in _ops.shock_windows:
        _event = store.get_market_event(_row.event_id)
        _prices = store.series(_row.commodity, _row.market, "modal_price")
        if _event.window_end is not None:
            _shock_end = _event.window_end + timedelta(days=_event.decay_days)
        else:
            _shock_end = _prices[-1].obs_date
        _results = store.list_backtest_results(
            _row.commodity, _row.market, _row.horizon_days
        )

        def _split(_keep):
            _day_rows, _realised = [], {}
            for _res in _results:
                for _day in _res.days:
                    if _keep(_day.forecast_date):
                        _day_rows.append(
                            (_day.forecast_date, _day.p10, _day.p50, _day.p90)
                        )
                        _realised[_day.forecast_date] = _day.realised
            return _ametrics.score_days(_day_rows, _realised)[1]

        _shock = _split(
            lambda d: _event.window_start <= d <= _shock_end
        )
        _rest = _split(
            lambda d: not (_event.window_start <= d <= _shock_end)
        )
        if (
            _row.shock_n_days != _shock["n_days"]
            or _row.rest_n_days != _rest["n_days"]
            or (_shock["n_days"] and _row.shock_mape != _shock["mape"])
            or (_rest["n_days"] and _row.rest_mape != _rest["mape"])
        ):
            counters["analytics_shock_window_errors"] += 1
        if _event.origin == "historical" and _event.event_class == "export_restriction":
            if _row.state != "no_shock_window_days" or _row.shock_n_days != 0:
                counters["analytics_shock_window_errors"] += 1

    # re-performance: the clean report verifies; a tampered
    # payload does not
    counters["analytics_reperformance_errors"] += len(
        _verify_ops_report(store, _ops)
    )
    _conn = _sqlite3.connect(str(tmp / "evals.db"))
    _payload = _json.loads(
        _conn.execute(
            "SELECT payload FROM ops_reports WHERE report_id = ?",
            (_ops.report_id,),
        ).fetchone()[0]
    )
    _payload["trends"][0]["late_mape"] = 99.0
    _conn.execute(
        "UPDATE ops_reports SET payload = ? WHERE report_id = ?",
        (_json.dumps(_payload), _ops.report_id),
    )
    _conn.commit()
    _conn.close()
    if not _verify_ops_report(store, store.get_ops_report(_ops.report_id)):
        counters["analytics_reperformance_errors"] += 1

    # --- operator console (R13, F20-OW2 + F20-OW3 + F20-OW4 + F20-MF2) ---
    import json as _json13
    import sqlite3 as _sqlite3_13
    from datetime import date as _date13

    from fmcg_forecast.catalogue import ALL_DRIVERS as _ALL_DRIVERS
    from fmcg_forecast.console.engine import (
        ConsoleStateError as _ConsoleStateError,
    )
    from fmcg_forecast.console.pack import (
        load_console_pack as _load_console_pack,
    )
    from fmcg_forecast.console.service import (
        ConsoleService as _ConsoleService,
    )
    from fmcg_forecast.console.verify import (
        verify_console as _verify_console,
    )
    from fmcg_forecast.console.verify import (
        verify_preflight as _verify_preflight,
    )
    from fmcg_forecast.events.service import (
        EventService as _EventService13,
    )
    from fmcg_forecast.forecast.models import HORIZONS as _HORIZONS13
    from fmcg_forecast.forecast.service import (
        ApprovalStateError as _ApprovalStateError,
    )
    from fmcg_forecast.forecast.service import (
        ForecastService as _ForecastService13,
    )
    from fmcg_forecast.modelport import OfflineModel as _OfflineModel13

    _events13 = _EventService13(store)
    _console13 = _ConsoleService(store, _events13)
    _cpack = _load_console_pack()
    _hend = manifest.history_end
    _plain13 = _ForecastService13(store, _OfflineModel13())

    # pre-flight: every series' checklist re-derived from the
    # raw record — last observations, index weeks, ledger pins
    for _spec in BY_NAME.values():
        for _market in _spec.markets:
            _c, _m = _spec.commodity, _market.market
            _report = _console13.strike_preflight(_c, _m)
            _expected_gaps = []
            for _driver in _ALL_DRIVERS:
                _rows = store.series(
                    _c, _m, _driver, _date13(2000, 1, 1), _hend
                )
                _last = max((r.obs_date for r in _rows), default=None)
                _row = next(
                    d for d in _report.drivers if d.driver == _driver
                )
                if _driver not in _spec.drivers:
                    if _last is not None or _row.state != "missing":
                        counters["console_preflight_errors"] += 1
                    _expected_gaps.append(
                        f"driver {_driver} is missing — "
                        f"{_spec.display} does not report it"
                    )
                    continue
                if _last is None:
                    if _row.state != "missing":
                        counters["console_preflight_errors"] += 1
                    _expected_gaps.append(
                        f"driver {_driver} is missing — never "
                        f"reported for {_c}/{_m}"
                    )
                    continue
                _age = (_hend - _last).days
                _want = (
                    "present"
                    if _age <= _cpack.obs_fresh_days
                    else "stale"
                )
                if (
                    _row.state != _want
                    or _row.last_observed_date != _last
                    or _row.age_days != _age
                ):
                    counters["console_preflight_errors"] += 1
                if _want == "stale":
                    _expected_gaps.append(
                        f"driver {_driver} is stale — last observed "
                        f"{_last.isoformat()}, {_age} days before "
                        f"the as-of"
                    )
            _weeks = [
                i for i in store.list_indices(_c) if i.week_end <= _hend
            ]
            if not _weeks:
                if _report.sentiment.state != "absent":
                    counters["console_preflight_errors"] += 1
                _expected_gaps.append(
                    f"sentiment is absent — no index week stands "
                    f"for {_c}"
                )
            else:
                _latest = max(i.week_end for i in _weeks)
                _sage = (_hend - _latest).days
                _swant = (
                    "current"
                    if _sage <= _cpack.sentiment_fresh_days
                    else "stale"
                )
                if (
                    _report.sentiment.state != _swant
                    or _report.sentiment.age_days != _sage
                ):
                    counters["console_preflight_errors"] += 1
                if _swant == "stale":
                    _expected_gaps.append(
                        f"sentiment is stale — last index week ended "
                        f"{_latest.isoformat()}, {_sage} days before "
                        f"the as-of"
                    )
            for _h in _HORIZONS13:
                _rec = store.get_accuracy_record(_c, _m, _h)
                _crow = next(
                    x for x in _report.coverage if x.horizon_days == _h
                )
                _cwant = (
                    "unmeasured" if _rec is None
                    else "degraded" if _rec.degraded
                    else "measured"
                )
                if _crow.state != _cwant:
                    counters["console_preflight_errors"] += 1
                if _cwant == "unmeasured":
                    _expected_gaps.append(
                        f"no backtest coverage at the {_h}-day "
                        f"horizon — accuracy unmeasured"
                    )
            if _report.gaps != _expected_gaps:
                counters["console_preflight_errors"] += 1
            if _report.state != ("gapped" if _expected_gaps else "clear"):
                counters["console_preflight_errors"] += 1
            counters["console_preflight_errors"] += len(
                _verify_preflight(store, _report)
            )

    # a tampered pre-flight payload is refused by re-performance
    _coffee13 = _console13.strike_preflight("coffee", "bengaluru")
    _conn13 = _sqlite3_13.connect(str(tmp / "evals.db"))
    _orig13 = _conn13.execute(
        "SELECT payload FROM preflight_reports WHERE report_id = ?",
        (_coffee13.report_id,),
    ).fetchone()[0]
    _tampered13 = _json13.loads(_orig13)
    _tampered13["gaps"] = []
    _conn13.execute(
        "UPDATE preflight_reports SET payload = ? WHERE report_id = ?",
        (_json13.dumps(_tampered13), _coffee13.report_id),
    )
    _conn13.commit()
    if not _verify_preflight(
        store, store.get_preflight_report(_coffee13.report_id)
    ):
        counters["console_preflight_errors"] += 1
    _conn13.execute(
        "UPDATE preflight_reports SET payload = ? WHERE report_id = ?",
        (_orig13, _coffee13.report_id),
    )
    _conn13.commit()
    _conn13.close()

    # review queue: states from the pinned attachments, the
    # pack's order, and the prior-official arithmetic
    _chili13 = _plain13.run_forecast(
        "chili", "guntur", as_of=_date13(2025, 12, 15)
    )
    _wheat_early = _plain13.run_forecast(
        "wheat", "delhi_khari_baoli", as_of=_date13(2025, 12, 10)
    )
    _plain13.approve(
        _wheat_early.forecast_id, "d.kaur", "desk_head",
        _date13(2026, 1, 2),
    )
    _wheat13 = _plain13.run_forecast(
        "wheat", "delhi_khari_baoli", as_of=_date13(2025, 12, 15)
    )
    _queue13 = _console13.review_queue()
    _rank13 = {"degraded": 0, "unmeasured": 1, "measured": 2}
    _keys13 = [
        (_rank13[r["accuracy_state"]], r["as_of"], r["forecast_id"])
        for r in _queue13
    ]
    if _keys13 != sorted(_keys13):
        counters["console_review_queue_errors"] += 1
    _qids13 = [r["forecast_id"] for r in _queue13]
    if not (
        _chili13.forecast_id in _qids13
        and _wheat13.forecast_id in _qids13
        and _qids13.index(_chili13.forecast_id)
        < _qids13.index(_wheat13.forecast_id)
    ):
        counters["console_review_queue_errors"] += 1
    for _row13 in _queue13:
        _fc13 = store.get_forecast(_row13["forecast_id"])
        if _fc13 is None or _fc13.accuracy.state != _row13["accuracy_state"]:
            counters["console_review_queue_errors"] += 1
            continue
        if _row13["prior_official_id"] is not None:
            _prior13 = store.get_forecast(_row13["prior_official_id"])
            _approval13 = store.get_approval(_row13["prior_official_id"])
            if (
                _prior13 is None
                or _approval13 is None
                or _prior13.commodity != _fc13.commodity
                or _prior13.market != _fc13.market
                or not _prior13.as_of < _fc13.as_of
            ):
                counters["console_review_queue_errors"] += 1
            else:
                _p_now = next(
                    s.p50 for s in _fc13.horizons_summary
                    if s.horizon_days == 30
                )
                _p_then = next(
                    s.p50 for s in _prior13.horizons_summary
                    if s.horizon_days == 30
                )
                if _row13["delta_p50_30"] != round(_p_now - _p_then, 2):
                    counters["console_review_queue_errors"] += 1

    # rejection: the act is final — no approval path reopens it
    _console13.reject_forecast(
        _chili13.forecast_id, "d.kaur", "desk_head",
        _date13(2026, 1, 3), "stale_inputs",
        "arrivals feed stale at the run",
    )
    try:
        _plain13.approve(
            _chili13.forecast_id, "d.kaur", "desk_head",
            _date13(2026, 1, 4),
        )
        counters["console_rejection_errors"] += 1
    except _ApprovalStateError:
        pass
    if _chili13.forecast_id in [
        r["forecast_id"] for r in _console13.review_queue()
    ]:
        counters["console_rejection_errors"] += 1
    try:
        _console13.reject_forecast(
            _chili13.forecast_id, "r.menon", "desk_head",
            _date13(2026, 1, 4), "accuracy_not_credible",
        )
        counters["console_rejection_errors"] += 1
    except _ConsoleStateError:
        pass
    counters["console_rejection_errors"] += len(_verify_console(store))

    # triage: the gate on the official view, both directions
    _events13.triage_exclusions = _console13.excluded_event_ids
    _guarded13 = _ForecastService13(
        store,
        _OfflineModel13(),
        events_provider=_events13.forecast_adjustments,
        approval_guard=_console13.approval_blockers,
    )
    _forged13 = _events13.register_event(
        event_class="tariff_change", commodity="soybean",
        window_start=_date13(2025, 6, 15),
        window_end=_date13(2025, 7, 15), channel="import_flow",
        peak_log_price_effect=0.60, basis="desk_estimate",
        basis_detail="A desk estimate of the tariff's pass-through, "
        "stated for triage grading",
        decay_days=10,
        description="A claimed tariff step on oilseed imports",
        declared_by="a.sharma", declared_on=_date13(2025, 6, 10),
    )
    if _events13.verify_event(_forged13.event_id).status != "unverified":
        counters["console_triage_errors"] += 1
    _draft13 = _guarded13.run_forecast(
        "soybean", "indore", as_of=_date13(2025, 5, 31)
    )
    if _forged13.event_id not in _draft13.method.events_applied:
        counters["console_triage_errors"] += 1
    _blockers13 = _console13.approval_blockers(_draft13)
    if not any(_forged13.event_id in b for b in _blockers13):
        counters["console_triage_errors"] += 1
    try:
        _guarded13.approve(
            _draft13.forecast_id, "d.kaur", "desk_head",
            _date13(2025, 6, 2),
        )
        counters["console_triage_errors"] += 1
    except _ApprovalStateError:
        pass
    _console13.confirm_event(
        _forged13.event_id, "a.sharma", "analyst", _date13(2025, 6, 2),
        "checked against the customs circular",
    )
    if any(
        _forged13.event_id in b
        for b in _console13.approval_blockers(_draft13)
    ):
        counters["console_triage_errors"] += 1
    # the desk clears every remaining applied-event blocker the
    # same way (earlier eval sections declared their own probes
    # over this window); with the queue cleared, approval stands
    for _applied13 in _draft13.method.events_applied:
        if any(
            _applied13 in b
            for b in _console13.approval_blockers(_draft13)
        ):
            _console13.confirm_event(
                _applied13, "a.sharma", "analyst", _date13(2025, 6, 2),
                "cleared in the eval's triage pass",
            )
    if _console13.approval_blockers(_draft13):
        counters["console_triage_errors"] += 1
    _guarded13.approve(
        _draft13.forecast_id, "d.kaur", "desk_head", _date13(2025, 6, 2)
    )

    _retire13 = _events13.register_event(
        event_class="logistics_disruption", commodity="cumin",
        window_start=_date13(2025, 3, 1),
        window_end=_date13(2025, 3, 20), channel="arrivals",
        peak_log_price_effect=0.07, basis="desk_estimate",
        basis_detail="A corridor report, stated for triage grading",
        decay_days=10,
        description="A claimed corridor disruption into Unjha",
        declared_by="a.sharma", declared_on=_date13(2025, 2, 20),
    )
    _first13 = _guarded13.run_forecast(
        "cumin", "unjha", as_of=_date13(2025, 2, 15)
    )
    if _retire13.event_id not in _first13.method.events_applied:
        counters["console_triage_errors"] += 1
    _console13.retire_event(
        _retire13.event_id, "a.sharma", "analyst",
        _date13(2025, 2, 21), "the corridor report was a misread",
    )
    if not any(
        _retire13.event_id in b and "retired" in b
        for b in _console13.approval_blockers(_first13)
    ):
        counters["console_triage_errors"] += 1
    _second13 = _guarded13.run_forecast(
        "cumin", "unjha", as_of=_date13(2025, 2, 15)
    )
    if _retire13.event_id in _second13.method.events_applied:
        counters["console_triage_errors"] += 1

    _amend13 = _events13.register_event(
        event_class="weather_shock", commodity="chili",
        window_start=_date13(2025, 2, 1),
        window_end=_date13(2025, 2, 28), channel="weather_index",
        driver_effect=-0.4, peak_log_price_effect=0.05,
        basis="desk_estimate",
        basis_detail="A field report, stated for triage grading",
        decay_days=10,
        description="A claimed dry spell in the chili belt",
        declared_by="a.sharma", declared_on=_date13(2025, 1, 20),
    )
    _adraft13 = _guarded13.run_forecast(
        "chili", "guntur", as_of=_date13(2025, 1, 15)
    )
    if _amend13.event_id not in _adraft13.method.events_applied:
        counters["console_triage_errors"] += 1
    _act13 = _console13.amend_event(
        _amend13.event_id, "a.sharma", "analyst", _date13(2025, 1, 22),
        {
            "event_class": "weather_shock", "commodity": "chili",
            "window_start": _date13(2025, 2, 1),
            "window_end": _date13(2025, 2, 28),
            "channel": "weather_index", "driver_effect": -0.4,
            "peak_log_price_effect": 0.09, "basis": "desk_estimate",
            "basis_detail": "Revised pass-through after the second "
            "field report",
            "decay_days": 10,
            "description": "A claimed dry spell in the chili belt",
            "declared_by": "a.sharma",
            "declared_on": _date13(2025, 1, 22),
        },
        "peak revised on the second field report",
    )
    if _console13.triage_state(_amend13.event_id) != "superseded":
        counters["console_triage_errors"] += 1
    if not any(
        (_act13.replacement_event_id or "") in b
        for b in _console13.approval_blockers(_adraft13)
    ):
        counters["console_triage_errors"] += 1
    _afresh13 = _guarded13.run_forecast(
        "chili", "guntur", as_of=_date13(2025, 1, 15)
    )
    if (
        _act13.replacement_event_id not in _afresh13.method.events_applied
        or _amend13.event_id in _afresh13.method.events_applied
    ):
        counters["console_triage_errors"] += 1
    counters["console_triage_errors"] += len(_verify_console(store))

    # action parity: the console's action door (the phone's
    # door) strikes the identical act as the canonical path,
    # on a twin store holding the same artefacts
    from fmcg_forecast.alerts.models import (
        AlertInstance as _AlertInstance13,
    )
    from fmcg_forecast.alerts.pack import (
        load_alert_pack as _load_alert_pack13,
    )
    from fmcg_forecast.alerts.service import (
        AlertService as _AlertService13,
    )
    from fmcg_forecast.store import build_store as _build_store13
    from fmcg_forecast.truth import build_truth_store as _build_truth13
    from fmcg_forecast.workflow import load_dataset as _load_dataset13

    _twin = _build_store13(str(tmp / "evals-twin.db"))
    _twin_truth = _build_truth13(str(tmp / "evals-twin.db"))
    _load_dataset13(_twin, _twin_truth, data.manifest.seed)
    _twin_console = _ConsoleService(_twin, _EventService13(_twin))
    _parity_fc = _plain13.run_forecast(
        "groundnut", "rajkot", as_of=_date13(2025, 11, 30)
    )
    _twin.insert_forecast(_parity_fc)
    _direct = _plain13.approve(
        _parity_fc.forecast_id, "d.kaur", "desk_head",
        _date13(2026, 1, 5),
    )
    _via_door = _twin_console.dispatch_action(
        {
            "kind": "approve_forecast",
            "forecast_id": _parity_fc.forecast_id,
            "approver": "d.kaur", "role": "desk_head",
            "decided_on": "2026-01-05",
        }
    )
    if _via_door != _direct.model_dump(mode="json"):
        counters["console_action_parity_errors"] += 1
    _parity_fc2 = _plain13.run_forecast(
        "groundnut", "gondal", as_of=_date13(2025, 11, 30)
    )
    _twin.insert_forecast(_parity_fc2)
    _direct_rej = _console13.reject_forecast(
        _parity_fc2.forecast_id, "d.kaur", "desk_head",
        _date13(2026, 1, 5), "duplicate_of_newer_run",
    )
    _door_rej = _twin_console.dispatch_action(
        {
            "kind": "reject_forecast",
            "forecast_id": _parity_fc2.forecast_id,
            "rejected_by": "d.kaur", "role": "desk_head",
            "decided_on": "2026-01-05",
            "reason": "duplicate_of_newer_run",
        }
    )
    if _door_rej != _direct_rej.model_dump(mode="json"):
        counters["console_action_parity_errors"] += 1
    from datetime import datetime as _datetime13

    _alert13 = _AlertInstance13(
        alert_id="ALT-evalparity",
        subscription_id="SUB-eval", subscriber="d.kaur",
        kind="buy_signal", commodity="wheat",
        market="delhi_khari_baoli", severity="major",
        trigger_id="SIG-eval", trigger_summary={"value": "buy_now"},
        raised_at=_datetime13(2026, 1, 5, 9, 0),
        pack_version=_load_alert_pack13().version,
        scope_note="signal only — no trade is placed",
    )
    store.insert_alert(_alert13)
    _twin.insert_alert(_alert13)
    _direct_act = _AlertService13(store).acknowledge(
        _alert13.alert_id, "d.kaur", "desk_head",
        _datetime13(2026, 1, 6, 10, 30), "seen",
    )
    _door_act = _twin_console.dispatch_action(
        {
            "kind": "acknowledge_alert", "alert_id": _alert13.alert_id,
            "actor": "d.kaur", "role": "desk_head",
            "acted_at": "2026-01-06T10:30:00", "note": "seen",
        }
    )
    if _door_act != _direct_act.model_dump(mode="json"):
        counters["console_action_parity_errors"] += 1

    print("Round 13 evals — FMCG commodity forecast (R1 data integrity + R2 forecast engine + R3 backtesting/ledger + R4 sentiment + R5 event registry + R6 scenario studio + R7 prompt-to-dashboard + R8 buy signals & coverage planning + R9 alerting, subscriptions & escalation + R10 thin-data depth & assisted intake + R11 production data plane + R12 forecast-ops analytics & shock grading + R13 operator console: review queue & rejection, event triage gate, coverage pre-flight, phone action parity)")
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
