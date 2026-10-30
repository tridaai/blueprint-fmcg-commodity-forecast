"""Round 14 tests: geospatial basis & netting (F20-PO4,
F20-GS1, F20-GS2).

The basis band hand-computed on a fabricated series (paired
spreads, the pack's percentile rule written out independently
in the test), a market under the paired-days floor named
insufficient instead of classified, the landed comparison
that names a missing freight line instead of assuming one,
the cost-line fold (a later entry stands, desk provenance
on its face), the weather overlay re-performed from the
stored weather facts alone, and the market map whose every
cell equals the artefact reads it composes — a market with
no data rendered as a named gap, never a zero. Postgres
parity runs when FMCG_TEST_DATABASE_URL names a cluster.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.alerts.models import AlertInstance
from fmcg_forecast.alerts.pack import load_alert_pack
from fmcg_forecast.alerts.service import AlertService
from fmcg_forecast.api import create_app
from fmcg_forecast.backtest.harness import run_all
from fmcg_forecast.events.service import EventService
from fmcg_forecast.geo import cli as geo_cli
from fmcg_forecast.geo.engine import compute_weather_row, quantile, to_paise
from fmcg_forecast.geo.pack import load_geo_pack
from fmcg_forecast.geo.render import render_market_map
from fmcg_forecast.geo.service import GeoService, GeoValidationError
from fmcg_forecast.geo.verify import (
    verify_basis_reading,
    verify_cost_line_entry,
    verify_geo,
    verify_landed_comparison,
    verify_market_map,
)
from fmcg_forecast.modelport import OfflineModel
from fmcg_forecast.models import Observation
from fmcg_forecast.sentiment.grading import build_sentiment_grading_store
from fmcg_forecast.sentiment.load import load_sentiment_corpus
from fmcg_forecast.sentiment.service import SentimentService
from fmcg_forecast.store import build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset

SEED = 20261027
HISTORY_END = date(2025, 12, 31)


@pytest.fixture(scope="module")
def graded(tmp_path_factory):
    """A loaded store: grid run, corpus pipelined, events
    seeded — the desk's full record."""
    db = str(tmp_path_factory.mktemp("r14") / "test.db")
    store = build_store(db)
    truth = build_truth_store(db)
    load_dataset(store, truth, SEED)
    run_all(store)
    grading = build_sentiment_grading_store(db)
    load_sentiment_corpus(store, grading, SEED)
    SentimentService(store, OfflineModel()).run_pipeline()
    EventService(store).seed_historical(store.get_manifest())
    return {"store": store, "db": db}


# --- fabricated series ---------------------------------------------------


def _obs(commodity, market, driver, day, value):
    return Observation(
        commodity=commodity, market=market, obs_date=day,
        driver=driver, value=value,
    )


def _days(start: date, count: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(count)]


def _fabricated_store(tmp_path):
    """Wheat on three markets, 100 paired days from
    2025-03-01: the reference flat, Indore's spread cycling
    through a stated set, Kanpur paired on only 30 days,
    and weather facts under Indore that end in a spike."""
    store = build_store(str(tmp_path / "fab.db"))
    rows: list[Observation] = []
    days = _days(date(2025, 3, 1), 100)
    spreads = [-2000 + (i % 10) * 100 for i in range(100)]  # paise
    spreads[-1] = 5000  # the current day jumps above any band
    for i, day in enumerate(days):
        rows.append(_obs("wheat", "delhi_khari_baoli",
                         "modal_price", day, 2000.0))
        rows.append(_obs("wheat", "indore", "modal_price", day,
                         2000.0 + spreads[i] / 100.0))
        if i < 30:
            rows.append(_obs("wheat", "kanpur", "modal_price",
                             day, 1990.0))
    for i, day in enumerate(days):
        rows.append(_obs("wheat", "indore", "weather_index", day,
                         50.0 if i < 99 else 95.0))
    store.insert_observations(rows)
    return store, days, spreads


def _expected_quantile(sorted_values: list[int], q: float) -> int:
    """The pack's percentile rule, written out independently."""
    rank = q * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    fraction = rank - low
    if low == high:
        return sorted_values[low]
    return int(round(
        sorted_values[low] * (1 - fraction)
        + sorted_values[high] * fraction
    ))


# --- the pack --------------------------------------------------------------


def test_pack_is_versioned_and_fail_closed():
    pack = load_geo_pack()
    assert pack.version == "2026.10.1"
    assert {line.line for line in pack.cost_lines} == {"freight", "handling"}
    markets = {g.market for g in pack.geography}
    from fmcg_forecast.catalogue import COMMODITIES

    assert markets == {
        m.market for c in COMMODITIES for m in c.markets
    }
    with pytest.raises(ValueError):
        load_geo_pack("1999.01.1")


def test_quantile_and_paise_rules():
    assert quantile([100], 0.10) == 100
    assert quantile([0, 100], 0.50) == 50
    assert quantile([0, 100, 200], 0.25) == 50
    assert to_paise(2450.0) == 245000
    assert to_paise(2415.255) == 241526  # rounded once, to the paise


# --- basis: the hand-computed fixture (F20-PO4) ----------------------------


def test_basis_band_hand_computed(tmp_path):
    store, days, spreads = _fabricated_store(tmp_path)
    as_of = days[-1]
    service = GeoService(store)
    reading = service.strike_basis_reading("wheat", as_of)
    rows = {r.market: r for r in reading.rows}
    reference = rows["delhi_khari_baoli"]
    assert reference.classification == "reference"
    assert reference.current_spread_paise == 0
    assert reference.band_low_paise == 0
    assert reference.paired_days == 100

    indore = rows["indore"]
    ordered = sorted(spreads)
    assert indore.paired_days == 100
    assert indore.band_low_paise == _expected_quantile(ordered, 0.10)
    assert indore.band_median_paise == _expected_quantile(ordered, 0.50)
    assert indore.band_high_paise == _expected_quantile(ordered, 0.90)
    assert indore.current_spread_paise == 5000
    assert indore.current_date == as_of
    assert indore.classification == "wide"  # 5000 sits above the band
    assert indore.freshness == "current"
    assert verify_basis_reading(store, reading) == []
    # a re-strike is the same artefact, not a duplicate
    assert service.strike_basis_reading("wheat", as_of).reading_id == (
        reading.reading_id
    )
    assert len(store.list_basis_readings("wheat")) == 1


def test_basis_below_the_floor_is_named_not_classified(tmp_path):
    store, days, _ = _fabricated_store(tmp_path)
    reading = GeoService(store).strike_basis_reading("wheat", days[-1])
    kanpur = {r.market: r for r in reading.rows}["kanpur"]
    assert kanpur.paired_days == 30
    assert kanpur.classification == "insufficient_history"
    assert kanpur.band_low_paise is not None  # the band is still stated
    assert any("30 paired days" in gap for gap in kanpur.gaps)


def test_basis_no_paired_history_and_stale(tmp_path):
    store = build_store(str(tmp_path / "bare.db"))
    rows = [
        _obs("groundnut", "rajkot", "modal_price",
             date(2025, 1, 6) + timedelta(days=i), 5900.0)
        for i in range(10)
    ]
    store.insert_observations(rows)
    service = GeoService(store)
    reading = service.strike_basis_reading("groundnut", date(2025, 3, 1))
    rows_by_market = {r.market: r for r in reading.rows}
    gondal = rows_by_market["gondal"]
    assert gondal.classification == "no_paired_history"
    assert gondal.current_spread_paise is None
    assert gondal.band_low_paise is None
    rajkot = rows_by_market["rajkot"]
    assert rajkot.freshness == "stale"  # last pair is weeks before as_of
    assert any("stated as of that date" in gap for gap in rajkot.gaps)
    assert verify_basis_reading(store, reading) == []


def test_basis_on_graded_store(graded):
    store = graded["store"]
    service = GeoService(store)
    reading = service.strike_basis_reading("wheat", HISTORY_END)
    assert reading.reference_market == "delhi_khari_baoli"
    assert len(reading.rows) == 3
    for row in reading.rows:
        assert row.paired_days >= load_geo_pack().min_paired_days
        assert row.classification in (
            "reference", "wide", "within", "narrow"
        )
    coffee = service.strike_basis_reading("coffee", HISTORY_END)
    assert len(coffee.rows) == 1
    assert coffee.rows[0].classification == "reference"
    assert verify_geo(store) == []


# --- cost lines and landed cost (F20-PO4) -----------------------------------


def test_cost_line_entry_discipline(tmp_path):
    store, _, _ = _fabricated_store(tmp_path)
    service = GeoService(store)
    entry = service.enter_cost_line(
        "wheat", "indore", "freight", 45000, "a.rao", date(2025, 6, 1)
    )
    assert entry.origin == "desk_entered"
    assert entry.entered_by == "a.rao"
    assert verify_cost_line_entry(entry) == []
    # an identical re-entry is the same artefact, not a duplicate
    again = service.enter_cost_line(
        "wheat", "indore", "freight", 45000, "a.rao", date(2025, 6, 1)
    )
    assert again.entry_id == entry.entry_id
    assert len(store.list_cost_line_entries()) == 1
    with pytest.raises(GeoValidationError):
        service.enter_cost_line(
            "wheat", "indore", "insurance", 100, "a.rao", date(2025, 6, 1)
        )
    with pytest.raises(GeoValidationError):
        service.enter_cost_line(
            "wheat", "indore", "freight", -5, "a.rao", date(2025, 6, 1)
        )
    with pytest.raises(GeoValidationError):
        service.enter_cost_line(
            "wheat", "indore", "freight", 45.5, "a.rao", date(2025, 6, 1)
        )
    with pytest.raises(GeoValidationError):
        service.enter_cost_line(
            "wheat", "guntur", "freight", 100, "a.rao", date(2025, 6, 1)
        )
    with pytest.raises(GeoValidationError):
        service.enter_cost_line(
            "wheat", "indore", "freight", 100, "  ", date(2025, 6, 1)
        )


def test_cost_line_fold_latest_entry_stands(tmp_path):
    store, days, _ = _fabricated_store(tmp_path)
    service = GeoService(store)
    service.enter_cost_line(
        "wheat", "indore", "freight", 40000, "a.rao", date(2025, 5, 1)
    )
    newer = service.enter_cost_line(
        "wheat", "indore", "freight", 45000, "d.kaur", date(2025, 6, 1)
    )
    heads = service.head_cost_lines("wheat", "indore")
    assert heads["freight"].entry_id == newer.entry_id
    assert heads["freight"].rate_paise_per_quintal == 45000
    assert len(store.list_cost_line_entries("wheat", "indore")) == 2
    # scoped to before the newer entry landed, the first stands
    scoped = service.head_cost_lines(
        "wheat", "indore", as_of=date(2025, 5, 15)
    )
    assert scoped["freight"].rate_paise_per_quintal == 40000


def test_landed_comparison_names_missing_lines(tmp_path):
    store, days, _ = _fabricated_store(tmp_path)
    as_of = days[-1]
    service = GeoService(store)
    service.enter_cost_line(
        "wheat", "indore", "freight", 45000, "a.rao", date(2025, 6, 1)
    )
    service.enter_cost_line(
        "wheat", "indore", "handling", 12000, "a.rao", date(2025, 6, 1)
    )
    service.enter_cost_line(
        "wheat", "delhi_khari_baoli", "freight", 90000,
        "a.rao", date(2025, 6, 1),
    )
    comparison = service.strike_landed_comparison(
        "wheat", as_of, "verdanta_plant"
    )
    rows = {r.market: r for r in comparison.rows}
    indore = rows["indore"]
    # last Indore price is 2000 + 5000/100 = 2050.00 INR = 205000 paise
    assert indore.state == "computable"
    assert indore.price_paise == 205000
    assert indore.landed_paise == 205000 + 45000 + 12000
    assert indore.rank == 1
    delhi = rows["delhi_khari_baoli"]
    assert delhi.state == "not_computable"
    assert delhi.missing_lines == ["handling"]
    assert delhi.landed_paise is None
    assert delhi.rank is None  # never ranked
    kanpur = rows["kanpur"]
    assert kanpur.state == "not_computable"
    assert kanpur.missing_lines == ["freight", "handling"]
    # no line was assumed: the missing line carries no rate anywhere
    for line in delhi.lines:
        if line.line == "handling":
            assert line.state == "missing"
            assert line.rate_paise_per_quintal is None
    assert comparison.scope_note.startswith("comparison only")
    assert verify_landed_comparison(store, comparison) == []


def test_landed_ranking_follows_the_pack_rule(tmp_path):
    store, days, _ = _fabricated_store(tmp_path)
    as_of = days[-1]
    service = GeoService(store)
    for market, freight, handling in (
        ("indore", 45000, 12000),
        ("delhi_khari_baoli", 1000, 1000),
        ("kanpur", 100, 100),
    ):
        service.enter_cost_line(
            "wheat", market, "freight", freight, "a.rao", date(2025, 6, 1)
        )
        service.enter_cost_line(
            "wheat", market, "handling", handling, "a.rao", date(2025, 6, 1)
        )
    comparison = service.strike_landed_comparison(
        "wheat", as_of, "verdanta_plant"
    )
    ranked = sorted(
        (r for r in comparison.rows if r.rank is not None),
        key=lambda r: r.rank,
    )
    # Kanpur's price is weeks old at as_of (30 paired days from
    # March), so its landed row prices off a stale price — the
    # state is on its face, and it still ranks by the rule.
    assert [r.market for r in ranked] == [
        "kanpur", "delhi_khari_baoli", "indore",
    ]
    assert ranked[0].price_state == "stale"
    assert ranked[0].landed_paise == 199000 + 200


def test_landed_on_graded_store(graded):
    store = graded["store"]
    service = GeoService(store)
    for market in ("delhi_khari_baoli", "indore", "kanpur"):
        service.enter_cost_line(
            "wheat", market, "freight", 30000, "a.rao", HISTORY_END
        )
        service.enter_cost_line(
            "wheat", market, "handling", 8000, "a.rao", HISTORY_END
        )
    comparison = service.strike_landed_comparison(
        "wheat", HISTORY_END, "verdanta_plant"
    )
    for row in comparison.rows:
        last = store.series(
            "wheat", row.market, "modal_price", None, HISTORY_END
        )[-1]
        assert row.price_paise == to_paise(last.value)
        assert row.landed_paise == row.price_paise + 38000
    assert verify_landed_comparison(store, comparison) == []


# --- the weather overlay (F20-GS2) -------------------------------------------


def test_weather_overlay_from_the_stored_facts(tmp_path):
    store, days, _ = _fabricated_store(tmp_path)
    pack = load_geo_pack()
    row = compute_weather_row(store, "wheat", "indore", days[-1], pack)
    # 99 facts at 50.0 and the latest at 95.0 inside the 90-day
    # window ending at the latest fact: the window holds the
    # last 90 facts (89 at 50.0, one at 95.0)
    window = [50.0] * 89 + [95.0]
    mean = sum(window) / len(window)
    std = (sum((v - mean) ** 2 for v in window) / len(window)) ** 0.5
    assert row.window_facts == 90
    assert row.mean == round(mean, 6)
    assert row.std == round(std, 6)
    assert row.z == round((95.0 - mean) / std, 4)
    assert row.state == "deviating"
    assert row.latest_date == days[-1]


def test_weather_overlay_states(tmp_path):
    store = build_store(str(tmp_path / "wx.db"))
    rows: list[Observation] = []
    for i in range(40):
        rows.append(_obs("wheat", "indore", "weather_index",
                         date(2025, 5, 1) + timedelta(days=i), 50.0))
    for i in range(5):
        rows.append(_obs("wheat", "kanpur", "weather_index",
                         date(2025, 5, 1) + timedelta(days=i), 50.0))
    store.insert_observations(rows)
    pack = load_geo_pack()
    flat = compute_weather_row(store, "wheat", "indore",
                               date(2025, 6, 9), pack)
    assert flat.state == "flat"
    assert flat.z is None
    thin = compute_weather_row(store, "wheat", "kanpur",
                               date(2025, 6, 9), pack)
    assert thin.state == "insufficient_history"
    assert thin.window_facts == 5
    none = compute_weather_row(store, "chili", "guntur",
                               date(2025, 6, 9), pack)
    assert none.state == "no_current_data"


# --- the market map (F20-GS1 + F20-GS2) ---------------------------------------


def _alert(store, alert_id, market, severity, raised_at):
    alert = AlertInstance(
        alert_id=alert_id,
        subscription_id="SUB-fixture",
        subscriber="d.kaur",
        kind="buy_signal",
        commodity="wheat",
        market=market,
        severity=severity,
        trigger_id="SIG-fixture",
        trigger_summary={"value": "buy_now"},
        raised_at=raised_at,
        pack_version=load_alert_pack().version,
        scope_note="signal only — no trade is placed",
    )
    store.insert_alert(alert)
    return alert


def test_map_cells_equal_the_artefact_reads(tmp_path):
    store, days, _ = _fabricated_store(tmp_path)
    as_of = days[-1]
    alerts = AlertService(store)
    _alert(store, "ALT-map-open", "indore", "major",
           datetime(2025, 6, 1, 9, 0))
    _alert(store, "ALT-map-closed", "indore", "critical",
           datetime(2025, 6, 1, 9, 0))
    alerts.close("ALT-map-closed", "d.kaur", "desk_head",
                 datetime(2025, 6, 2, 9, 0), "acted_on")
    _alert(store, "ALT-map-future", "kanpur", "minor",
           datetime(2025, 12, 1, 9, 0))
    service = GeoService(store)
    market_map = service.strike_map("wheat", as_of)
    reading = store.get_basis_reading(market_map.basis_reading_id)
    assert reading is not None
    cells = {c.market: c for c in market_map.cells}
    assert set(cells) == {"delhi_khari_baoli", "indore", "kanpur"}
    indore = cells["indore"]
    assert indore.open_alerts == 1  # the closed one does not count
    assert indore.top_severity == "major"
    assert indore.basis_classification == "wide"
    assert indore.current_spread_paise == 5000
    assert indore.price_paise == 205000
    assert indore.weather.state == "deviating"
    assert cells["kanpur"].open_alerts == 0  # raised after as_of
    assert cells["delhi_khari_baoli"].basis_classification == "reference"
    # the rendered page is the artefact's own, byte for byte
    assert market_map.html == render_market_map(market_map)
    assert "Indore" in market_map.html
    assert verify_market_map(store, market_map) == []
    # a re-strike is the same artefact
    assert service.strike_map("wheat", as_of).map_id == market_map.map_id


def test_map_renders_a_market_with_no_data_as_a_named_gap(tmp_path):
    store = build_store(str(tmp_path / "gap.db"))
    store.insert_observations([
        _obs("wheat", "delhi_khari_baoli", "modal_price",
             date(2025, 6, 2), 2450.0),
    ])
    service = GeoService(store)
    market_map = service.strike_map("wheat", date(2025, 6, 2))
    cells = {c.market: c for c in market_map.cells}
    assert cells["indore"].data_state == "no_current_data"
    assert cells["indore"].price_paise is None
    assert "No current data" in market_map.html
    assert "named gap" in market_map.html
    assert verify_market_map(store, market_map) == []


def test_map_active_events_follow_the_registry_windows(graded):
    store = graded["store"]
    service = GeoService(store)
    by_source = {
        e.source_record_id: e.event_id for e in store.list_market_events()
    }
    inside = service.strike_map("soybean", date(2025, 6, 20))
    assert [e.event_id for e in inside.active_events] == [
        by_source["EVT-2025-TARIFF-SOYBEAN"]
    ]
    outside = service.strike_map("soybean", date(2025, 8, 15))
    assert outside.active_events == []
    ban = service.strike_map("basmati_rice", date(2024, 9, 15))
    assert [e.event_id for e in ban.active_events] == [
        by_source["EVT-2024-BAN-BASMATI"]
    ]
    assert verify_geo(store) == []


# --- tamper --------------------------------------------------------------------


def _tamper(db: str, table: str, key_column: str, key: str, edit) -> str:
    conn = sqlite3.connect(db)
    original = conn.execute(
        f"SELECT payload FROM {table} WHERE {key_column} = ?", (key,)
    ).fetchone()[0]
    payload = json.loads(original)
    edit(payload)
    conn.execute(
        f"UPDATE {table} SET payload = ? WHERE {key_column} = ?",
        (json.dumps(payload), key),
    )
    conn.commit()
    conn.close()
    return original


def _restore(db: str, table: str, key_column: str, key: str, original: str):
    conn = sqlite3.connect(db)
    conn.execute(
        f"UPDATE {table} SET payload = ? WHERE {key_column} = ?",
        (original, key),
    )
    conn.commit()
    conn.close()


def test_tampered_geo_artefacts_are_detected(graded):
    store = graded["store"]
    db = graded["db"]
    service = GeoService(store)
    reading = service.strike_basis_reading("wheat", HISTORY_END)
    original = _tamper(
        db, "basis_readings", "reading_id", reading.reading_id,
        lambda p: p["rows"][1].update({"current_spread_paise": 1}),
    )
    problems = verify_basis_reading(
        store, store.get_basis_reading(reading.reading_id)
    )
    assert problems
    _restore(db, "basis_readings", "reading_id", reading.reading_id, original)
    assert verify_basis_reading(
        store, store.get_basis_reading(reading.reading_id)
    ) == []

    market_map = service.strike_map("wheat", HISTORY_END)
    original = _tamper(
        db, "market_maps", "map_id", market_map.map_id,
        lambda p: p["cells"][0].update({"open_alerts": 99}),
    )
    assert verify_market_map(store, store.get_market_map(market_map.map_id))
    _restore(db, "market_maps", "map_id", market_map.map_id, original)
    assert verify_market_map(
        store, store.get_market_map(market_map.map_id)
    ) == []


# --- surfaces -------------------------------------------------------------------


def test_api_geo_surface(graded):
    store = graded["store"]
    client = TestClient(create_app(store))
    pack = client.get("/geo/pack")
    assert pack.status_code == 200
    assert pack.json()["version"] == "2026.10.1"
    entered = client.post("/geo/cost-lines", json={
        "commodity": "soybean", "market": "indore", "line": "freight",
        "rate_paise_per_quintal": 45000, "entered_by": "a.rao",
        "entered_on": "2025-12-30",
    })
    assert entered.status_code == 201
    assert entered.json()["origin"] == "desk_entered"
    refused = client.post("/geo/cost-lines", json={
        "commodity": "soybean", "market": "indore", "line": "insurance",
        "rate_paise_per_quintal": 100, "entered_by": "a.rao",
        "entered_on": "2025-12-30",
    })
    assert refused.status_code == 422
    basis = client.post("/geo/basis-readings", json={
        "commodity": "wheat", "as_of": "2025-12-31",
    })
    assert basis.status_code == 201
    assert basis.json()["problems"] == []
    landed = client.post("/geo/landed-comparisons", json={
        "commodity": "soybean", "as_of": "2025-12-31",
        "priced_for": "verdanta_plant",
    })
    assert landed.status_code == 201
    rows = {r["market"]: r for r in landed.json()["rows"]}
    assert rows["indore"]["state"] == "not_computable"
    assert rows["indore"]["missing_lines"] == ["handling"]
    assert rows["nagpur"]["missing_lines"] == ["freight", "handling"]
    struck = client.post("/geo/maps", json={
        "commodity": "wheat", "as_of": "2025-12-31",
    })
    assert struck.status_code == 201
    map_id = struck.json()["map_id"]
    page = client.get(f"/geo/maps/{map_id}/html")
    assert page.status_code == 200
    assert "Market map" in page.text
    assert client.get("/geo/maps/NOPE").status_code == 404
    verify = client.get("/geo/verify")
    assert verify.status_code == 200
    assert verify.json()["problems"] == []


def test_cli_geo_surface(graded, capsys):
    db = graded["db"]
    assert geo_cli.main([
        "--db", db, "enter-cost", "wheat", "kanpur", "freight",
        "31000", "--by", "a.rao", "--on", "2025-12-30",
    ]) == 0
    capsys.readouterr()
    assert geo_cli.main([
        "--db", db, "basis", "wheat", "--as-of", "2025-12-31",
    ]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["commodity"] == "wheat"
    assert out["problems"] == []
    assert geo_cli.main(["--db", db, "verify"]) == 0
    assert geo_cli.main([
        "--db", db, "enter-cost", "wheat", "kanpur", "insurance",
        "100", "--by", "a.rao", "--on", "2025-12-30",
    ]) == 2


# --- Postgres parity ---------------------------------------------------------


PG_DSN = os.environ.get("FMCG_TEST_DATABASE_URL")


@pytest.mark.skipif(not PG_DSN, reason="FMCG_TEST_DATABASE_URL not set")
def test_postgres_parity(graded):
    lite = graded["store"]
    pg = build_store(database_url=PG_DSN)
    pg_truth = build_truth_store(database_url=PG_DSN)
    load_dataset(pg, pg_truth, SEED)
    run_all(pg)
    grading = build_sentiment_grading_store(database_url=PG_DSN)
    load_sentiment_corpus(pg, grading, SEED)
    SentimentService(pg, OfflineModel()).run_pipeline()
    EventService(pg).seed_historical(pg.get_manifest())

    lite_geo = GeoService(lite)
    pg_geo = GeoService(pg)
    for geo in (lite_geo, pg_geo):
        for market in ("delhi_khari_baoli", "indore", "kanpur"):
            geo.enter_cost_line(
                "wheat", market, "freight", 30000, "a.rao", HISTORY_END
            )
            geo.enter_cost_line(
                "wheat", market, "handling", 8000, "a.rao", HISTORY_END
            )
    lite_reading = lite_geo.strike_basis_reading("wheat", HISTORY_END)
    pg_reading = pg_geo.strike_basis_reading("wheat", HISTORY_END)
    assert pg_reading.model_dump(mode="json") == (
        lite_reading.model_dump(mode="json")
    )
    lite_landed = lite_geo.strike_landed_comparison(
        "wheat", HISTORY_END, "verdanta_plant"
    )
    pg_landed = pg_geo.strike_landed_comparison(
        "wheat", HISTORY_END, "verdanta_plant"
    )
    assert pg_landed.model_dump(mode="json") == (
        lite_landed.model_dump(mode="json")
    )
    lite_map = lite_geo.strike_map("soybean", date(2025, 6, 20))
    pg_map = pg_geo.strike_map("soybean", date(2025, 6, 20))
    assert pg_map.model_dump(mode="json") == lite_map.model_dump(mode="json")
    assert pg_geo.verify_all() == []
