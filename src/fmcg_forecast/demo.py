"""Demo: generate the dataset, load it, and print the planted checks.

Runs against a fresh demo SQLite file so the walkthrough always
shows the current generator. The checks printed here are the same
planted truths the eval gate grades with zero tolerance.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from fmcg_forecast.config import Settings
from fmcg_forecast.store import build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset


def _mean_price(store, commodity, market, start, end) -> float:
    rows = store.series(commodity, market, "modal_price", start, end)
    return sum(r.value for r in rows) / len(rows)


def main() -> int:
    settings = Settings.from_env()
    demo_db = Path("./data/demo-fmcg.db")
    if demo_db.exists():
        demo_db.unlink()
    store = build_store(str(demo_db))
    truth_store = build_truth_store(str(demo_db))
    state = load_dataset(store, truth_store, settings.dataset_seed)
    manifest = store.get_manifest()
    assert manifest is not None

    print(f"generator {manifest.generator_version} seed {manifest.seed}")
    print(f"history rows: {manifest.history_rows}  future (sealed truth) rows: {manifest.future_rows}")
    print(f"history digest: {manifest.history_digest[:16]}…")
    print("\nrows per commodity:")
    for commodity, count in store.row_counts().items():
        print(f"  {commodity:<14} {count}")

    def yoy_effect(commodity, market, start, post_end):
        def window_ratio(shift):
            pre = _mean_price(store, commodity, market, start - timedelta(days=25 + shift), start - timedelta(days=5 + shift))
            post = _mean_price(store, commodity, market, start + timedelta(days=5) - timedelta(days=shift), post_end - timedelta(days=shift))
            return post / pre

        return window_ratio(0) / window_ratio(365)

    tariff = next(e for e in manifest.events if e.kind == "tariff_shock")
    effect = yoy_effect("soybean", "indore", tariff.start_date, tariff.start_date + timedelta(days=20))
    print(f"\ntariff shock ({tariff.event_id}): soybean/indore seasonally-matched price effect "
          f"x{effect:.3f} (planted peak +16% decaying over 45 days)")

    ban = next(e for e in manifest.events if e.kind == "export_ban")
    effect = yoy_effect("basmati_rice", "delhi_khari_baoli", ban.start_date, ban.end_date - timedelta(days=10))
    print(f"export ban ({ban.event_id}): basmati/delhi seasonally-matched price effect "
          f"x{effect:.3f} (planted -11% for the window)")

    harvest = store.series("wheat", "delhi_khari_baoli", "arrivals", date(2024, 4, 1), date(2024, 6, 30))
    lean = store.series("wheat", "delhi_khari_baoli", "arrivals", date(2024, 10, 1), date(2024, 12, 31))
    h = sum(r.value for r in harvest) / len(harvest)
    l = sum(r.value for r in lean) / len(lean)
    print(f"seasonality: wheat arrivals harvest season {h:.0f}/day vs lean {l:.0f}/day (x{h / l:.2f})")

    coffee = next(c for c in manifest.commodities if c.commodity == "coffee")
    disruption_rows = store.series(
        "coffee", "bengaluru", "modal_price",
        manifest.coffee_disruption_start, manifest.coffee_disruption_end,
    )
    print(f"coffee (thin data): {coffee.history_days_per_market} reporting days, "
          f"{coffee.history_rows} rows, missing drivers named: {coffee.missing_drivers}, "
          f"rows inside the planted disruption window: {len(disruption_rows)}")

    print("\n--- forecast engine (R2): computed, decomposed, gated ---")
    from fmcg_forecast.forecast.service import ForecastService
    from fmcg_forecast.modelport import build_model_port

    service = ForecastService(store, build_model_port(settings))
    wheat = service.run_forecast("wheat", "delhi_khari_baoli")
    print(f"wheat/delhi forecast {wheat.forecast_id} as of {wheat.as_of} (status: {wheat.status})")
    for summary in wheat.horizons_summary:
        drivers = ", ".join(
            f"{name} {value:+.2f}" for name, value in summary.contributions.items()
        )
        print(f"  {summary.horizon_days:>2}d {summary.forecast_date}: baseline {summary.baseline:.2f} "
              f"-> P50 {summary.p50:.2f} (P10 {summary.p10:.2f} / P90 {summary.p90:.2f}); {drivers}")
    problems = service.verify_stored(wheat.forecast_id)
    print(f"  re-performance verification of the stored artefact: {len(problems)} problems")
    commentary = service.draft_commentary(wheat.forecast_id)
    print(f"  commentary (model profile {commentary.model_profile}, figures verified):")
    print(f"    {commentary.text}")
    approval = service.approve(
        wheat.forecast_id, approver="r.menon", role="Head of Trading Desk",
        decided_on=date(2026, 1, 2),
    )
    print(f"  approval act {approval.approval_id}: {approval.approver} ({approval.role}) "
          f"made it the official view on {approval.decided_on}")

    coffee_fc = service.run_forecast("coffee", "bengaluru")
    h30 = next(s for s in coffee_fc.horizons_summary if s.horizon_days == 30)
    print(f"coffee/bengaluru forecast {coffee_fc.forecast_id}: missing drivers named "
          f"{coffee_fc.missing_drivers}; sparsity widening x{coffee_fc.method.sparsity.multiplier} "
          f"(wheat x{wheat.method.sparsity.multiplier}); 30d band {h30.p10:.2f}..{h30.p90:.2f} "
          f"around P50 {h30.p50:.2f}")
    print(f"  note: those forecasts were run before any backtest existed — their "
          f"accuracy reads '{coffee_fc.accuracy.state}', named on the artefact")

    print("\n--- backtesting + the accuracy ledger (R3): every forecast carries its measured accuracy ---")
    from fmcg_forecast.backtest.harness import run_all

    report, records = run_all(store)
    print(f"harness: {report.engine_runs} engine runs at monthly 2025 origins, "
          f"{report.results_stored} results stored, {len(report.skipped)} origins skipped")
    for skip in report.skipped:
        print(f"  skipped {skip['commodity']}/{skip['market']} @ {skip['origin']}: "
              f"{skip['reason'].split(';')[0]}")
    print(f"ledger: {len(records)} accuracy records (14 series x 3 horizons), pooled "
          f"over the most recent 6 origins, degraded bar = pooled MAPE above 5.0%")
    for record in records:
        if record.commodity in ("wheat", "chili", "coffee"):
            flag = "  <-- DEGRADED" if record.degraded else ""
            print(f"  {record.commodity}/{record.market} {record.horizon_days:>2}d: "
                  f"MAPE {record.mape:.2f}%  bias {record.bias:+.2f}  coverage "
                  f"{record.coverage:.2f}  over {record.n_results} origins{flag}")

    chili = service.run_forecast("chili", "guntur")
    print(f"\nchili/guntur forecast {chili.forecast_id} carries accuracy: {chili.accuracy.state}")
    print(f"  {chili.accuracy.note}")
    chili_commentary = service.draft_commentary(chili.forecast_id)
    print(f"  commentary states it too: 'Backtest accuracy state: degraded' "
          f"in text -> {'Backtest accuracy state: degraded' in chili_commentary.text}")
    wheat2 = service.run_forecast("wheat", "indore")
    print(f"wheat/indore forecast {wheat2.forecast_id} carries accuracy: "
          f"{wheat2.accuracy.state} (a fresh run pins the ledger as it now stands; "
          f"the pre-backtest run above keeps its unmeasured snapshot)")
    print(f"sealed truth rows stored: {truth_store.count()} (readable only via the truth store)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
