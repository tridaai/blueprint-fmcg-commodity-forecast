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
    package = Path(__file__).resolve().parents[1] / "src" / "fmcg_forecast" / "forecast"
    violations = 0
    for path in package.rglob("*.py"):
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

    print("Round 2 evals — FMCG commodity forecast (R1 data integrity + R2 forecast engine)")
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
