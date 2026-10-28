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
    print(f"sealed truth rows stored: {truth_store.count()} (readable only via the truth store)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
