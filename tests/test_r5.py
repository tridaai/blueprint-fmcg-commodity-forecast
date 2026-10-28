"""Round 5 tests: event pack, path rule, registry acts, seeding,
transmission verification against measured history, impact view,
forecast integration (per-event lines, interval widening), API,
tamper detection, truth isolation."""

from __future__ import annotations

import ast
import json
import math
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.api import create_app
from fmcg_forecast.events.measure import event_impact, measure_event_effect
from fmcg_forecast.events.models import MarketEvent, event_content_id
from fmcg_forecast.events.pack import EVENT_PACK_V1, load_event_pack
from fmcg_forecast.events.paths import build_event_path, event_log_effect
from fmcg_forecast.events.service import (
    EventNotFoundError,
    EventService,
    EventValidationError,
)
from fmcg_forecast.events.verify import verify_market_event
from fmcg_forecast.forecast.engine import EventAdjustment, run_engine
from fmcg_forecast.forecast.service import ForecastService
from fmcg_forecast.forecast.verify import verify_forecast
from fmcg_forecast.modelport import OfflineModel
from fmcg_forecast.store import build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset

SEED = 20261027
PACK = EVENT_PACK_V1


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db = str(tmp_path_factory.mktemp("r5") / "test.db")
    store = build_store(db)
    truth = build_truth_store(db)
    load_dataset(store, truth, SEED)
    events = EventService(store)
    seeded = events.seed_historical(store.get_manifest())
    return {"db": db, "store": store, "events": events, "seeded": seeded}


def _declared(events: EventService, **overrides) -> MarketEvent:
    kwargs = dict(
        event_class="demand_shock",
        commodity="wheat",
        window_start=date(2026, 1, 10),
        window_end=date(2026, 1, 19),
        channel="modal_price",
        peak_log_price_effect=0.10,
        basis="desk_estimate",
        basis_detail="Desk estimate worked by hand for the fixture",
        decay_days=10,
        description="Fixture demand shock over the wheat window",
        declared_by="t.iyer",
        declared_on=date(2026, 1, 3),
    )
    kwargs.update(overrides)
    return events.register_event(**kwargs)


# --- the pack ------------------------------------------------------------


def test_pack_loader_is_fail_closed():
    assert load_event_pack().version == "2026.10.1"
    assert load_event_pack("2026.10.1").version == "2026.10.1"
    with pytest.raises(ValueError):
        load_event_pack("1999.01.1")


def test_pack_is_well_formed():
    assert set(PACK.classes) == {
        "tariff_change",
        "export_restriction",
        "import_policy",
        "weather_shock",
        "logistics_disruption",
        "demand_shock",
    }
    for channels in PACK.classes.values():
        assert "modal_price" in channels
    assert PACK.bases == ["announced_measure", "measured_analogue", "desk_estimate"]
    assert PACK.interval_widening_factor == 1.25
    assert PACK.verified_band_low < 1.0 < PACK.verified_band_high


# --- the path rule, worked by hand -----------------------------------------


def _fixture_event() -> MarketEvent:
    event = MarketEvent(
        event_id="EVT-pending",
        event_class="demand_shock",
        commodity="wheat",
        window_start=date(2025, 3, 10),
        window_end=date(2025, 3, 19),
        direction=1,
        transmission={
            "channel": "modal_price",
            "driver_effect": None,
            "peak_log_price_effect": 0.12,
            "basis": "desk_estimate",
            "basis_detail": "hand fixture",
        },
        decay_days=10,
        description="hand fixture",
        declared_by="t.iyer",
        declared_on=date(2025, 3, 1),
        pack_version=PACK.version,
        origin="declared",
        source_record_id=None,
    )
    event.event_id = event_content_id(event)
    return event


def test_path_rule_hand_computed():
    event = _fixture_event()
    cases = {
        date(2025, 3, 9): 0.0,      # before the window
        date(2025, 3, 10): 0.04,    # ramp day 1: peak x 1/3
        date(2025, 3, 11): 0.08,    # ramp day 2: peak x 2/3
        date(2025, 3, 12): 0.12,    # ramp complete
        date(2025, 3, 19): 0.12,    # last window day
        date(2025, 3, 20): 0.108,   # decay day 1: peak x (1 - 1/10)
        date(2025, 3, 24): 0.06,    # decay day 5: peak x 0.5
        date(2025, 3, 28): 0.012,   # decay day 9
        date(2025, 3, 29): 0.0,     # decay spent
        date(2025, 4, 15): 0.0,
    }
    for day, expected in cases.items():
        assert event_log_effect(event, day, PACK) == pytest.approx(expected, abs=1e-12)


def test_path_rule_open_ended_never_decays():
    event = _fixture_event()
    event.window_end = None
    assert event_log_effect(event, date(2026, 3, 10), PACK) == pytest.approx(0.12)


def test_build_event_path_shape():
    event = _fixture_event()
    path = build_event_path(event, date(2025, 3, 8), 30, PACK)
    assert len(path) == 30
    assert path[0] == 0.0 and path[1] == 0.0
    assert path[2] == pytest.approx(0.04)
    assert path[4] == pytest.approx(0.12)


# --- registration: the analyst act ------------------------------------------


def test_registration_is_content_addressed_and_idempotent(env):
    first = _declared(env["events"], commodity="groundnut")
    again = _declared(env["events"], commodity="groundnut")
    assert first.event_id == again.event_id
    assert first.event_id == event_content_id(first)
    assert first.direction == 1
    assert verify_market_event(first, PACK) == []


def test_registration_refusals(env):
    events = env["events"]
    with pytest.raises(EventValidationError):
        _declared(events, declared_by="unknown")
    with pytest.raises(EventValidationError):
        _declared(events, declared_by="  ")
    with pytest.raises(EventValidationError):
        _declared(events, event_class="price_control")
    with pytest.raises(EventValidationError):
        _declared(events, commodity="rice_crude")
    with pytest.raises(EventValidationError):
        _declared(events, channel="weather_index")  # not a demand_shock channel
    with pytest.raises(EventValidationError):
        _declared(events, peak_log_price_effect=0.0)
    with pytest.raises(EventValidationError):
        _declared(events, window_end=date(2026, 1, 1))  # before the start
    with pytest.raises(EventValidationError):
        _declared(events, decay_days=0)
    with pytest.raises(EventValidationError):
        _declared(events, basis="model_said_so")
    with pytest.raises(EventValidationError):
        _declared(events, basis_detail="   ")


def test_negative_peak_derives_negative_direction(env):
    event = _declared(
        env["events"],
        commodity="groundnut",
        window_start=date(2026, 2, 1),
        window_end=date(2026, 2, 20),
        peak_log_price_effect=-0.07,
        description="Fixture negative demand shock",
    )
    assert event.direction == -1


# --- historical seeding -------------------------------------------------------


def test_seeding_maps_the_manifest_exactly(env):
    events = env["events"]
    assert len(env["seeded"]["seeded"]) == 3
    by_source = {e.source_record_id: e for e in events.list_events()}

    tariff = by_source["EVT-2025-TARIFF-SOYBEAN"]
    assert tariff.event_class == "tariff_change"
    assert tariff.commodity == "soybean"
    assert tariff.window_start == date(2025, 6, 15)
    assert tariff.window_end == date(2025, 7, 30)
    assert tariff.transmission.channel == "import_flow"
    assert tariff.transmission.peak_log_price_effect == 0.16
    assert tariff.decay_days == 45
    assert tariff.origin == "historical"

    ban = by_source["EVT-2024-BAN-BASMATI"]
    assert ban.event_class == "export_restriction"
    assert ban.transmission.channel == "export_flow"
    assert ban.transmission.driver_effect == 0.05
    assert ban.transmission.peak_log_price_effect == -0.11
    assert ban.window_start == date(2024, 9, 1)
    assert ban.window_end == date(2024, 10, 30)

    drought = by_source["ANOMALY-CHILI-2025"]
    assert drought.event_class == "weather_shock"
    assert drought.transmission.channel == "weather_index"
    assert drought.transmission.driver_effect == -0.6
    # (-0.06 log per index point) x (-0.6 deviation) = +0.036 peak
    assert drought.transmission.peak_log_price_effect == pytest.approx(0.036)
    assert drought.direction == 1

    for event in by_source.values():
        assert verify_market_event(event, PACK) == []


def test_seeding_is_idempotent(env):
    again = env["events"].seed_historical(env["store"].get_manifest())
    assert again["seeded"] == []
    assert len(again["already_on_record"]) == 3
    assert len(env["events"].list_events()) >= 3


# --- transmission verification against measured history ----------------------


def test_planted_transmissions_verify(env):
    events = env["events"]
    by_source = {e.source_record_id: e for e in events.list_events()}
    tariff = events.verify_event(by_source["EVT-2025-TARIFF-SOYBEAN"].event_id)
    assert tariff.status == "verified"
    # the R1 band for the seasonally-matched tariff measurement
    assert 1.06 <= tariff.measured_ratio <= 1.24
    ban = events.verify_event(by_source["EVT-2024-BAN-BASMATI"].event_id)
    assert ban.status == "verified"
    assert 0.83 <= ban.measured_ratio <= 0.96
    drought = events.verify_event(by_source["ANOMALY-CHILI-2025"].event_id)
    assert drought.status == "verified"
    assert drought.measured_log_effect > 0
    assert PACK.verified_band_low <= drought.ratio_to_claim <= PACK.verified_band_high


def test_forged_claim_is_flagged_unverified(env):
    forged = _declared(
        env["events"],
        commodity="soybean",
        event_class="tariff_change",
        channel="import_flow",
        window_start=date(2025, 6, 15),
        window_end=date(2025, 7, 30),
        peak_log_price_effect=0.60,
        basis="desk_estimate",
        basis_detail="A wild claim over the real tariff window",
        decay_days=45,
        description="Forged tariff claim for the verifier probe",
        declared_on=date(2025, 8, 1),
    )
    verdict = env["events"].verify_event(forged.event_id)
    assert verdict.status == "unverified"
    assert verdict.ratio_to_claim < PACK.verified_band_low
    # the flag rides on the event's face — the standard read carries it
    view = env["events"].event_view(forged.event_id)
    assert view["verification"]["status"] == "unverified"


def test_wrong_sign_claim_is_flagged_unverified(env):
    forged = _declared(
        env["events"],
        commodity="soybean",
        window_start=date(2025, 6, 15),
        window_end=date(2025, 7, 30),
        peak_log_price_effect=-0.16,
        basis="desk_estimate",
        basis_detail="A claim against the measured direction",
        decay_days=45,
        description="Wrong-sign claim over the tariff window",
        declared_on=date(2025, 8, 1),
    )
    assert env["events"].verify_event(forged.event_id).status == "unverified"


def test_future_event_is_not_measurable_and_named(env):
    future = _declared(
        env["events"],
        commodity="cumin",
        window_start=date(2026, 6, 1),
        window_end=date(2026, 6, 30),
        description="A declared future shock",
        declared_on=date(2026, 1, 3),
    )
    verdict = env["events"].verify_event(future.event_id)
    assert verdict.status == "not_measurable"
    assert verdict.measured_log_effect is None
    impact = env["events"].impact(future.event_id, "unjha")
    assert impact.state == "not_measurable"


# --- the impact view ------------------------------------------------------------


def test_impact_view_measures_the_planted_shocks(env):
    events = env["events"]
    by_source = {e.source_record_id: e for e in events.list_events()}
    tariff = event_impact(
        env["store"], by_source["EVT-2025-TARIFF-SOYBEAN"], "indore", PACK
    )
    assert tariff.state == "measured"
    assert len(tariff.days) > 40
    assert 1.0 < tariff.mean_price_ratio < 1.25
    assert tariff.peak_log_effect > 0.10
    ban = events.impact(by_source["EVT-2024-BAN-BASMATI"].event_id, "delhi_khari_baoli")
    assert ban.state == "measured"
    assert ban.mean_price_ratio < 1.0
    with pytest.raises(EventValidationError):
        events.impact(by_source["EVT-2025-TARIFF-SOYBEAN"].event_id, "guntur")
    with pytest.raises(EventNotFoundError):
        events.impact("EVT-nope")


# --- forecast integration ---------------------------------------------------------


def test_forecast_carries_the_event_line_at_the_stated_magnitude(env):
    store, events = env["store"], env["events"]
    wired = ForecastService(
        store, OfflineModel(), events_provider=events.forecast_adjustments
    )
    # before the declaration: the same run is clear
    before = wired.run_forecast("wheat", "delhi_khari_baoli", date(2025, 12, 31))
    assert wired.events_view(before.forecast_id)["state"] == "clear"
    assert all(d.events_adjustment == 0.0 for d in before.days)

    event = _declared(events)  # wheat, +0.10, 2026-01-10..19, decay 10
    after = wired.run_forecast("wheat", "delhi_khari_baoli", date(2025, 12, 31))
    view = wired.events_view(after.forecast_id)
    assert view["state"] == "shocked"
    assert view["events_applied"] == [event.event_id]
    entry = view["events"][0]
    path = entry["input_path"]
    # hand-computed from the pack's path rule (as_of 2025-12-31, so
    # forecast day 1 is 2026-01-01 and the window opens on day 10)
    assert path[0] == 0.0 and path[8] == 0.0
    assert path[9] == pytest.approx(0.0333, abs=1e-9)    # ramp 1/3
    assert path[10] == pytest.approx(0.0667, abs=1e-9)   # ramp 2/3
    assert path[11] == pytest.approx(0.10, abs=1e-9)     # peak
    assert path[18] == pytest.approx(0.10, abs=1e-9)     # last window day
    assert path[19] == pytest.approx(0.09, abs=1e-9)     # decay day 1
    assert path[27] == pytest.approx(0.01, abs=1e-9)     # decay day 9
    assert path[28] == 0.0                               # decay spent
    assert all(v == 0.0 for v in path[28:])
    # the INR line exists exactly on the touched days
    assert after.days[0].events_adjustment == 0.0
    assert after.days[11].events_adjustment > 0.0
    assert after.days[60].events_adjustment == 0.0
    assert verify_forecast(after) == []


def test_two_overlapping_events_telescope_as_separate_lines(env):
    store, events = env["store"], env["events"]
    wired = ForecastService(
        store, OfflineModel(), events_provider=events.forecast_adjustments
    )
    second = _declared(
        events,
        commodity="cumin",
        event_class="logistics_disruption",
        channel="arrivals",
        window_start=date(2026, 1, 15),
        window_end=date(2026, 2, 5),
        peak_log_price_effect=0.05,
        basis_detail="Corridor disruption over the cumin window",
        decay_days=10,
        description="Fixture logistics disruption on cumin",
    )
    third = _declared(
        events,
        commodity="cumin",
        window_start=date(2026, 1, 20),
        window_end=date(2026, 2, 10),
        peak_log_price_effect=-0.03,
        basis_detail="Offsetting demand fixture on cumin",
        decay_days=5,
        description="Fixture offsetting demand shock on cumin",
    )
    forecast = wired.run_forecast("cumin", "unjha", date(2025, 12, 31))
    view = wired.events_view(forecast.forecast_id)
    assert view["state"] == "shocked"
    assert set(view["events_applied"]) == {second.event_id, third.event_id}
    assert len(view["events"]) == 2
    assert verify_forecast(forecast) == []
    for i, day in enumerate(forecast.days):
        total = sum(e["contribution_path_inr"][i] for e in view["events"])
        assert total == pytest.approx(day.events_adjustment, abs=0.02)


def test_provider_excludes_events_outside_the_window(env):
    events = env["events"]
    # every soybean event's effect ended months before the default run
    assert events.forecast_adjustments("soybean", date(2025, 12, 31)) == []
    tariff_id = next(
        e.event_id
        for e in events.list_events()
        if e.source_record_id == "EVT-2025-TARIFF-SOYBEAN"
    )
    touching = [
        a
        for a in events.forecast_adjustments("soybean", date(2025, 6, 20))
        if a.event_id == tariff_id
    ]
    assert len(touching) == 1
    assert touching[0].interval_widening == PACK.interval_widening_factor
    assert max(touching[0].path) == pytest.approx(0.16)


def test_interval_widening_applies_exactly_per_pack(env):
    store = env["store"]
    manifest = store.get_manifest()
    as_of = date(2025, 12, 31)
    path = [0.0] * 90
    for i in range(9, 28):
        path[i] = 0.05
    plain = run_engine(store, manifest, "wheat", "delhi_khari_baoli", as_of)
    shocked = run_engine(
        store,
        manifest,
        "wheat",
        "delhi_khari_baoli",
        as_of,
        event_adjustments=[
            EventAdjustment(
                event_id="EVT-WIDEN", path=path,
                interval_widening=PACK.interval_widening_factor,
            )
        ],
    )
    # day index 11 is inside the event path; index 60 is outside
    for idx, expected in ((11, PACK.interval_widening_factor), (60, 1.0)):
        with_log = math.log(shocked.days[idx].p90 / shocked.days[idx].p50)
        plain_log = math.log(plain.days[idx].p90 / plain.days[idx].p50)
        assert with_log / plain_log == pytest.approx(expected, rel=0.01)
    assert verify_forecast(shocked) == []


def test_engine_refuses_duplicate_and_narrowing_adjustments(env):
    store = env["store"]
    manifest = store.get_manifest()
    adj = EventAdjustment(event_id="EVT-DUP", path=[0.05] * 90)
    with pytest.raises(Exception):
        run_engine(
            store, manifest, "wheat", "indore", date(2025, 12, 31),
            event_adjustments=[adj, adj],
        )
    with pytest.raises(Exception):
        run_engine(
            store, manifest, "wheat", "indore", date(2025, 12, 31),
            event_adjustments=[
                EventAdjustment(event_id="EVT-NARROW", path=[0.05] * 90, interval_widening=0.8)
            ],
        )


# --- tamper ---------------------------------------------------------------------


def test_tampered_declaration_is_detected(env):
    store, events = env["store"], env["events"]
    target = next(
        e for e in events.list_events() if e.source_record_id == "EVT-2025-TARIFF-SOYBEAN"
    )
    tampered = target.model_copy(deep=True)
    tampered.transmission.peak_log_price_effect = 0.25
    conn = sqlite3.connect(env["db"])
    try:
        conn.execute(
            "UPDATE market_events SET payload = ? WHERE event_id = ?",
            (tampered.model_dump_json(), target.event_id),
        )
        conn.commit()
        stored = store.get_market_event(target.event_id)
        problems = verify_market_event(stored, PACK)
        assert any("content id mismatch" in p for p in problems)
        assert events.verify_registry()["problems"]
    finally:
        # restore the record of record — the tamper is a probe,
        # not a state the rest of the suite should inherit
        conn.execute(
            "UPDATE market_events SET payload = ? WHERE event_id = ?",
            (target.model_dump_json(), target.event_id),
        )
        conn.commit()
        conn.close()


# --- API ---------------------------------------------------------------------------


def test_api_surface(env):
    client = TestClient(create_app(env["store"], OfflineModel()))
    r = client.get("/market-events")
    assert r.status_code == 200
    assert len(r.json()["events"]) >= 3
    tariff = next(
        e for e in r.json()["events"] if e["source_record_id"] == "EVT-2025-TARIFF-SOYBEAN"
    )
    assert tariff["verification"]["status"] == "verified"

    r = client.post("/market-events/seed-historical")
    assert r.status_code == 200 and r.json()["seeded"] == []

    r = client.post(
        "/market-events",
        json={
            "event_class": "import_policy",
            "commodity": "groundnut",
            "window_start": "2026-02-01",
            "window_end": "2026-03-01",
            "channel": "import_flow",
            "peak_log_price_effect": 0.04,
            "basis": "announced_measure",
            "basis_detail": "Import policy change announced with a stated duty step",
            "decay_days": 15,
            "description": "Import policy change on groundnut",
            "declared_by": "t.iyer",
            "declared_on": "2026-01-03",
        },
    )
    assert r.status_code == 201
    new_id = r.json()["event_id"]
    assert r.json()["verification"]["status"] == "not_measurable"

    r = client.post(
        "/market-events",
        json={
            "event_class": "import_policy",
            "commodity": "groundnut",
            "window_start": "2026-02-01",
            "channel": "weather_index",
            "peak_log_price_effect": 0.04,
            "basis": "announced_measure",
            "basis_detail": "wrong channel probe",
            "decay_days": 15,
            "description": "probe",
            "declared_by": "t.iyer",
        },
    )
    assert r.status_code == 422

    r = client.get(f"/market-events/{new_id}/verify")
    assert r.status_code == 200 and r.json()["status"] == "not_measurable"
    r = client.get(f"/market-events/{tariff['event_id']}/impact", params={"market": "indore"})
    assert r.status_code == 200 and r.json()["state"] == "measured"
    r = client.get("/market-events/EVT-nope")
    assert r.status_code == 404
    r = client.get("/market-events/verify")
    assert r.status_code == 200

    # a forecast run through the API carries the registered groundnut
    # event as its own line (alongside any earlier groundnut fixtures
    # whose windows also touch the run)
    r = client.post(
        "/forecasts/run",
        json={"commodity": "groundnut", "market": "rajkot"},
    )
    assert r.status_code == 200
    forecast_id = r.json()["forecast_id"]
    r = client.get(f"/forecasts/{forecast_id}/events")
    assert r.status_code == 200
    assert r.json()["state"] == "shocked"
    assert new_id in r.json()["events_applied"]


# --- isolation -----------------------------------------------------------------------


def test_events_package_never_touches_the_truth_store():
    base = Path(__file__).resolve().parents[1] / "src" / "fmcg_forecast" / "events"
    for path in base.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert not name.endswith(".truth"), f"{path.name} imports {name}"
        assert "truth_observations" not in path.read_text(encoding="utf-8")
