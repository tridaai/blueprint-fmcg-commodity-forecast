"""Round 13 tests: the operator console (F20-OW2, F20-OW3,
F20-OW4, F20-MF2).

The review queue with its rejection acts (a rejected draft
can never be approved; the queue works degraded first), the
event triage queue gating the official view (an unverified
event contributes to drafts, labelled, and zero to official
forecasts until a named analyst confirms it; retired and
superseded events leave new runs altogether), the coverage
pre-flight (hand-computed on a fabricated series; a run pins
its named gaps verbatim), and the phone console whose action
door strikes byte-identical acts to the canonical endpoints
(parity graded over HTTP on twin stores). Postgres parity
runs when FMCG_TEST_DATABASE_URL names a cluster.
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
from fmcg_forecast.api import create_app
from fmcg_forecast.backtest.harness import run_all
from fmcg_forecast.console import cli as console_cli
from fmcg_forecast.console.engine import (
    ConsoleStateError,
    ConsoleValidationError,
    compute_preflight,
    fold_triage_state,
)
from fmcg_forecast.console.pack import load_console_pack
from fmcg_forecast.console.render import render_console, render_console_phone
from fmcg_forecast.console.service import ConsoleService
from fmcg_forecast.console.verify import verify_console, verify_preflight
from fmcg_forecast.events.service import EventService
from fmcg_forecast.forecast.engine import ForecastError, forecast_content_id
from fmcg_forecast.forecast.models import (
    AccuracyAttachment,
    AccuracyRecord,
    BaselineMethod,
    Forecast,
    ForecastDay,
    ForecastMethod,
    HorizonAccuracy,
    HorizonSummary,
    ResidualMethod,
    SparsityMethod,
)
from fmcg_forecast.forecast.service import (
    ApprovalStateError,
    ForecastService,
)
from fmcg_forecast.modelport import OfflineModel
from fmcg_forecast.models import Observation
from fmcg_forecast.sentiment.grading import build_sentiment_grading_store
from fmcg_forecast.sentiment.load import load_sentiment_corpus
from fmcg_forecast.sentiment.models import SentimentIndex
from fmcg_forecast.sentiment.service import SentimentService
from fmcg_forecast.store import build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset

SEED = 20261027
HISTORY_END = date(2025, 12, 31)


@pytest.fixture(scope="module")
def graded(tmp_path_factory):
    """A loaded store: grid run, ledger built, corpus pipelined,
    events seeded — the desk's full record."""
    db = str(tmp_path_factory.mktemp("r13") / "test.db")
    store = build_store(db)
    truth = build_truth_store(db)
    load_dataset(store, truth, SEED)
    run_all(store)
    grading = build_sentiment_grading_store(db)
    load_sentiment_corpus(store, grading, SEED)
    SentimentService(store, OfflineModel()).run_pipeline()
    EventService(store).seed_historical(store.get_manifest())
    return {"store": store, "db": db}


def _console(store) -> ConsoleService:
    return ConsoleService(store, EventService(store))


def _guarded(store) -> ForecastService:
    """A forecast service wired the way the API wires it."""
    events = EventService(store)
    console = ConsoleService(store, events)
    events.triage_exclusions = console.excluded_event_ids
    return ForecastService(
        store,
        OfflineModel(),
        events_provider=events.forecast_adjustments,
        approval_guard=console.approval_blockers,
    )


# --- the pack ---------------------------------------------------------------


def test_pack_is_versioned_and_fail_closed():
    pack = load_console_pack()
    assert pack.version == "2026.10.1"
    assert pack.queue_state_order == ["degraded", "unmeasured", "measured"]
    assert "stale_inputs" in pack.rejection_reasons
    assert pack.triage_acts == ["confirm", "amend", "retire"]
    for rule in (pack.queue_rule, pack.rejection_rule, pack.triage_rule,
                 pack.preflight_rule):
        assert len(rule) > 100
    with pytest.raises(ValueError):
        load_console_pack("1999.1.1")


# --- the pre-flight: hand-computed fixture ------------------------------------


def _obs(store, commodity, market, driver, last_date, value=100.0):
    store.insert_observations(
        [
            Observation(
                commodity=commodity, market=market, obs_date=last_date,
                driver=driver, value=value,
            )
        ]
    )


def _record(store, commodity, market, horizon, *, degraded=False, mape=3.0):
    record = AccuracyRecord(
        record_id=f"ACC-{commodity}-{market}-{horizon}",
        commodity=commodity, market=market, horizon_days=horizon,
        origins=[date(2025, 1, 1)], n_results=6, n_days=100,
        covered_days=90, mae=10.0, mape=mape, bias=1.0, coverage=0.9,
        engine_version="fixture", pack_version="2026.10.1",
        degraded_threshold_mape_pct=5.0, degraded=degraded,
    )
    store.save_accuracy_record(record)
    return record


def _index(store, commodity, week_end):
    store.insert_index(
        SentimentIndex(
            index_id=f"IDX-{commodity}-{week_end.isoformat()}",
            commodity=commodity,
            week_start=week_end - timedelta(days=6),
            week_end=week_end, value=0.5, n_items=3,
            extraction_ids=[], aspect_values={},
            pack_version="2026.10.1", window_days=14, half_life_days=7.0,
        )
    )


def test_preflight_hand_computed_fixture(tmp_path):
    """Every line of the checklist, and the exact gap list, from
    a series whose last-observation dates are planted by hand."""
    store = build_store(str(tmp_path / "pf.db"))
    as_of = date(2026, 1, 10)
    series = ("wheat", "delhi_khari_baoli")
    _obs(store, *series, "modal_price", date(2026, 1, 9))      # age 1: present
    _obs(store, *series, "arrivals", date(2026, 1, 2))         # age 8: stale
    # stock_level: never reported -> missing
    _obs(store, *series, "import_flow", date(2026, 1, 10))     # age 0: present
    _obs(store, *series, "export_flow", date(2025, 12, 20))    # age 21: stale
    _obs(store, *series, "weather_index", date(2026, 1, 8))    # age 2: present
    _index(store, "wheat", date(2025, 12, 28))                 # age 13: current
    _record(store, *series, 7)
    _record(store, *series, 30, degraded=True, mape=6.5)
    # 90-day horizon: no record -> unmeasured

    report = compute_preflight(store, *series, as_of, load_console_pack())
    states = {d.driver: d.state for d in report.drivers}
    assert states == {
        "modal_price": "present",
        "arrivals": "stale",
        "stock_level": "missing",
        "import_flow": "present",
        "export_flow": "stale",
        "weather_index": "present",
    }
    assert report.last_observation_date == date(2026, 1, 9)
    assert report.sentiment.state == "current"
    assert report.sentiment.age_days == 13
    coverage = {c.horizon_days: c.state for c in report.coverage}
    assert coverage == {7: "measured", 30: "degraded", 90: "unmeasured"}
    assert report.gaps == [
        "driver arrivals is stale — last observed 2026-01-02, 8 days "
        "before the as-of",
        "driver stock_level is missing — never reported for "
        "wheat/delhi_khari_baoli",
        "driver export_flow is stale — last observed 2025-12-20, 21 "
        "days before the as-of",
        "no backtest coverage at the 90-day horizon — accuracy "
        "unmeasured",
    ]
    assert report.state == "gapped"
    assert verify_preflight(store, report) == []


def test_preflight_bare_coffee_names_every_gap(tmp_path):
    """A series with nothing on record: the catalogue's
    does-not-report gaps and the never-reported gaps are
    different sentences, and both are named."""
    store = build_store(str(tmp_path / "pf2.db"))
    report = compute_preflight(
        store, "coffee", "bengaluru", date(2026, 1, 10), load_console_pack()
    )
    assert report.gaps == [
        "driver modal_price is missing — never reported for "
        "coffee/bengaluru",
        "driver arrivals is missing — never reported for "
        "coffee/bengaluru",
        "driver stock_level is missing — Coffee does not report it",
        "driver import_flow is missing — Coffee does not report it",
        "driver export_flow is missing — Coffee does not report it",
        "driver weather_index is missing — never reported for "
        "coffee/bengaluru",
        "sentiment is absent — no index week stands for coffee",
        "no backtest coverage at the 7-day horizon — accuracy "
        "unmeasured",
        "no backtest coverage at the 30-day horizon — accuracy "
        "unmeasured",
        "no backtest coverage at the 90-day horizon — accuracy "
        "unmeasured",
    ]
    assert report.state == "gapped"
    assert report.sentiment.state == "absent"


def test_preflight_clear_series(tmp_path):
    store = build_store(str(tmp_path / "pf3.db"))
    as_of = date(2026, 1, 10)
    series = ("wheat", "delhi_khari_baoli")
    for driver in ("modal_price", "arrivals", "stock_level",
                   "import_flow", "export_flow", "weather_index"):
        _obs(store, *series, driver, date(2026, 1, 9))
    _index(store, "wheat", date(2026, 1, 4))
    for horizon in (7, 30, 90):
        _record(store, *series, horizon)
    report = compute_preflight(store, *series, as_of, load_console_pack())
    assert report.state == "clear"
    assert report.gaps == []
    assert verify_preflight(store, report) == []


# --- the pre-flight on the graded store ---------------------------------------


def test_preflight_on_graded_store(graded):
    store = graded["store"]
    console = _console(store)
    report = console.strike_preflight("coffee", "bengaluru")
    assert report.as_of == HISTORY_END
    gaps = " | ".join(report.gaps)
    for driver in ("stock_level", "import_flow", "export_flow"):
        assert f"driver {driver} is missing — Coffee does not report it" in gaps
    states = {d.driver: d.state for d in report.drivers}
    assert states["modal_price"] == "present"
    coverage = {c.horizon_days: c.state for c in report.coverage}
    assert set(coverage.values()) <= {"measured", "degraded"}
    # idempotent: striking again returns the same artefact
    again = console.strike_preflight("coffee", "bengaluru")
    assert again.report_id == report.report_id
    assert console.preflight_view(report.report_id)["problems"] == []
    with pytest.raises(ConsoleValidationError):
        console.strike_preflight("wheat", "not_a_market")


def test_preflight_tamper_is_detected(graded, tmp_path):
    store = graded["store"]
    console = _console(store)
    report = console.strike_preflight("groundnut", "rajkot")
    conn = sqlite3.connect(graded["db"])
    original = conn.execute(
        "SELECT payload FROM preflight_reports WHERE report_id = ?",
        (report.report_id,),
    ).fetchone()[0]
    payload = json.loads(original)
    payload["gaps"] = []
    conn.execute(
        "UPDATE preflight_reports SET payload = ? WHERE report_id = ?",
        (json.dumps(payload), report.report_id),
    )
    conn.commit()
    problems = verify_preflight(store, store.get_preflight_report(report.report_id))
    assert problems  # content address + re-performance both fail
    # restore: the shared store must stay clean for later tests
    conn.execute(
        "UPDATE preflight_reports SET payload = ? WHERE report_id = ?",
        (original, report.report_id),
    )
    conn.commit()
    conn.close()
    assert verify_preflight(store, store.get_preflight_report(report.report_id)) == []


# --- run-anyway: pinning the checklist (F20-OW4) -------------------------------


def test_run_pins_preflight_gaps(graded):
    store = graded["store"]
    console = _console(store)
    report = console.strike_preflight("coffee", "bengaluru")
    service = ForecastService(store, OfflineModel())
    pinned = service.run_forecast(
        "coffee", "bengaluru", preflight_id=report.report_id
    )
    assert pinned.preflight is not None
    assert pinned.preflight.preflight_id == report.report_id
    assert pinned.preflight.gaps == report.gaps
    assert report.gaps  # the pin is non-trivial: coffee is gapped
    plain = service.run_forecast("coffee", "bengaluru")
    assert plain.preflight is None
    assert plain.forecast_id != pinned.forecast_id
    assert service.verify_stored(pinned.forecast_id) == []
    assert verify_console(store) == []

    wheat = console.strike_preflight("wheat", "indore")
    with pytest.raises(ForecastError):
        service.run_forecast(
            "coffee", "bengaluru", preflight_id=wheat.report_id
        )
    with pytest.raises(ForecastError):
        service.run_forecast(
            "coffee", "bengaluru", preflight_id="PRE-doesnotexist"
        )
    older = console.strike_preflight(
        "coffee", "bengaluru", as_of=date(2025, 11, 30)
    )
    with pytest.raises(ForecastError):
        service.run_forecast(
            "coffee", "bengaluru", preflight_id=older.report_id
        )


# --- the review queue (F20-OW2) -------------------------------------------------


def _attachment(state: str, degraded_horizons=()) -> AccuracyAttachment:
    per_horizon = []
    for horizon in (7, 30, 90):
        degraded = horizon in degraded_horizons
        per_horizon.append(
            HorizonAccuracy(
                horizon_days=horizon,
                state="degraded" if degraded else state,
                record_id=f"ACC-fixture-{horizon}",
                n_origins=6, mae=10.0, mape=6.5 if degraded else 3.0,
                bias=0.5, coverage=0.9,
            )
        )
    return AccuracyAttachment(
        state=state, pack_version="2026.10.1",
        per_horizon=per_horizon, note="fixture",
    )


def test_review_queue_order_and_prior_official(graded):
    store = graded["store"]
    console = _console(store)
    service = ForecastService(store, OfflineModel())
    chili = service.run_forecast("chili", "guntur")
    wheat = service.run_forecast("wheat", "delhi_khari_baoli")
    assert chili.accuracy.state == "degraded"
    assert wheat.accuracy.state == "measured"

    rows = console.review_queue()
    ids = [r["forecast_id"] for r in rows]
    assert ids.index(chili.forecast_id) < ids.index(wheat.forecast_id)
    chili_row = next(r for r in rows if r["forecast_id"] == chili.forecast_id)
    assert chili_row["degraded_horizons"] == [30, 90]
    assert chili_row["prior_official_id"] is None
    assert set(chili_row["contributions_30d"]) == set(
        next(
            s for s in chili.horizons_summary if s.horizon_days == 30
        ).contributions
    )

    # approve the wheat draft; a later wheat draft then carries
    # it as its prior official, with the 30-day difference
    service.approve(
        wheat.forecast_id, "d.kaur", "desk_head", date(2026, 1, 2)
    )
    later = service.run_forecast(
        "wheat", "delhi_khari_baoli", as_of=date(2025, 12, 15)
    )
    row = next(
        r for r in console.review_queue()
        if r["forecast_id"] == later.forecast_id
    )
    assert row["prior_official_id"] == wheat.forecast_id
    p50 = {
        s.horizon_days: s.p50 for s in later.horizons_summary
    }
    prior_p50 = {
        s.horizon_days: s.p50 for s in wheat.horizons_summary
    }
    assert row["delta_p50_30"] == round(p50[30] - prior_p50[30], 2)
    # the approved forecast itself has left the queue
    assert wheat.forecast_id not in [
        r["forecast_id"] for r in console.review_queue()
    ]


# --- rejection discipline (F20-OW2) ----------------------------------------------


def test_rejection_discipline(graded):
    store = graded["store"]
    console = _console(store)
    service = ForecastService(store, OfflineModel())
    draft = service.run_forecast(
        "wheat", "delhi_khari_baoli", as_of=date(2025, 12, 20)
    )
    assert draft.status == "draft"

    with pytest.raises(ConsoleValidationError):
        console.reject_forecast(
            draft.forecast_id, "d.kaur", "desk_head",
            date(2026, 1, 3), "not_a_reason",
        )
    with pytest.raises(ConsoleValidationError):
        console.reject_forecast(
            draft.forecast_id, "d.kaur", "desk_head",
            date(2026, 1, 3), "other_stated_reason",
        )
    with pytest.raises(ConsoleValidationError):
        console.reject_forecast(
            draft.forecast_id, "unknown", "desk_head",
            date(2026, 1, 3), "stale_inputs",
        )

    act = console.reject_forecast(
        draft.forecast_id, "d.kaur", "desk_head",
        date(2026, 1, 3), "stale_inputs", "arrivals feed is a week old",
    )
    assert act.rejection_id.startswith("REJ-")
    assert console.rejection_view(draft.forecast_id)["problems"] == []
    # idempotent: the identical act returns the record
    again = console.reject_forecast(
        draft.forecast_id, "d.kaur", "desk_head",
        date(2026, 1, 3), "stale_inputs", "arrivals feed is a week old",
    )
    assert again.rejection_id == act.rejection_id
    # a different rejection against the same draft is refused
    with pytest.raises(ConsoleStateError):
        console.reject_forecast(
            draft.forecast_id, "r.menon", "desk_head",
            date(2026, 1, 4), "accuracy_not_credible",
        )
    # the rejected draft leaves the review queue
    assert draft.forecast_id not in [
        r["forecast_id"] for r in console.review_queue()
    ]
    # and it can never be approved — on the plain service path,
    # with no guard wired: the rejection check is in the act path
    with pytest.raises(ApprovalStateError) as excinfo:
        service.approve(
            draft.forecast_id, "d.kaur", "desk_head", date(2026, 1, 5)
        )
    assert "rejected" in str(excinfo.value)
    # the desk's remedy is a new run: a new artefact, approvable
    fresh = service.run_forecast(
        "wheat", "delhi_khari_baoli", as_of=date(2025, 12, 22)
    )
    assert fresh.forecast_id != draft.forecast_id
    service.approve(fresh.forecast_id, "d.kaur", "desk_head", date(2026, 1, 5))
    # an official forecast cannot be rejected
    with pytest.raises(ConsoleStateError):
        console.reject_forecast(
            fresh.forecast_id, "d.kaur", "desk_head",
            date(2026, 1, 6), "stale_inputs",
        )
    assert verify_console(store) == []


# --- event triage (F20-OW3) --------------------------------------------------------


def _declare(events: EventService, **overrides):
    fields = {
        "event_class": "tariff_change",
        "commodity": "soybean",
        "window_start": date(2025, 6, 15),
        "window_end": date(2025, 7, 15),
        "channel": "import_flow",
        "peak_log_price_effect": 0.60,
        "basis": "desk_estimate",
        "basis_detail": "A desk estimate of the tariff's pass-through, "
        "stated for triage grading",
        "decay_days": 10,
        "description": "A claimed tariff step on oilseed imports",
        "declared_by": "a.sharma",
        "declared_on": date(2025, 6, 10),
    }
    fields.update(overrides)
    return events.register_event(**fields)


def test_triage_gate_confirm_path(graded):
    store = graded["store"]
    events = EventService(store)
    console = _console(store)
    guarded = _guarded(store)
    forged = _declare(events)
    # the claim disagrees with the measured tariff effect
    assert events.verify_event(forged.event_id).status == "unverified"

    draft = guarded.run_forecast("soybean", "indore", as_of=date(2025, 5, 31))
    assert forged.event_id in draft.method.events_applied
    view = guarded.events_view(draft.forecast_id)
    flag = next(e for e in view["events"] if e["event_id"] == forged.event_id)
    assert flag  # the event line is on the draft, in full

    queue = console.triage_queue()
    row = next(r for r in queue if r["event_id"] == forged.event_id)
    assert row["lane"] == "unverified"
    assert row["triage_state"] == "declared"

    # approval is refused, naming the event — the unverified
    # event contributes zero to the official view
    with pytest.raises(ApprovalStateError) as excinfo:
        guarded.approve(
            draft.forecast_id, "d.kaur", "desk_head", date(2025, 6, 2)
        )
    assert forged.event_id in str(excinfo.value)

    # a named analyst confirms it in triage; approval now stands
    act = console.confirm_event(
        forged.event_id, "a.sharma", "analyst", date(2025, 6, 2),
        "checked against the customs circular",
    )
    assert act.act == "confirm"
    assert console.triage_state(forged.event_id) == "confirmed"
    assert forged.event_id not in [
        r["event_id"] for r in console.triage_queue()
    ]
    approval = guarded.approve(
        draft.forecast_id, "d.kaur", "desk_head", date(2025, 6, 2)
    )
    assert approval.forecast_id == draft.forecast_id
    assert verify_console(store) == []


def test_triage_retire_excludes_from_new_runs(graded):
    store = graded["store"]
    events = EventService(store)
    console = _console(store)
    guarded = _guarded(store)
    event = _declare(
        events,
        event_class="logistics_disruption", commodity="cumin",
        window_start=date(2025, 3, 1), window_end=date(2025, 3, 20),
        channel="arrivals", peak_log_price_effect=0.07,
        description="A claimed corridor disruption into Unjha",
        declared_on=date(2025, 2, 20),
    )
    first = guarded.run_forecast("cumin", "unjha", as_of=date(2025, 2, 15))
    assert event.event_id in first.method.events_applied

    console.retire_event(
        event.event_id, "a.sharma", "analyst", date(2025, 2, 21),
        "the corridor report was a misread advisory",
    )
    assert console.triage_state(event.event_id) == "retired"
    # the standing draft is blocked, naming the retirement
    blockers = console.approval_blockers(first)
    assert any(event.event_id in b and "retired" in b for b in blockers)
    # and new runs no longer apply it at all
    second = guarded.run_forecast("cumin", "unjha", as_of=date(2025, 2, 15))
    assert event.event_id not in second.method.events_applied
    assert second.forecast_id != first.forecast_id


def test_triage_amend_supersedes(graded):
    store = graded["store"]
    events = EventService(store)
    console = _console(store)
    guarded = _guarded(store)
    event = _declare(
        events,
        event_class="weather_shock", commodity="chili",
        window_start=date(2025, 2, 1), window_end=date(2025, 2, 28),
        channel="weather_index", driver_effect=-0.4,
        peak_log_price_effect=0.05,
        description="A claimed dry spell in the chili belt",
        declared_on=date(2025, 1, 20),
    )
    draft = guarded.run_forecast("chili", "guntur", as_of=date(2025, 1, 15))
    assert event.event_id in draft.method.events_applied

    act = console.amend_event(
        event.event_id, "a.sharma", "analyst", date(2025, 1, 22),
        {
            "event_class": "weather_shock", "commodity": "chili",
            "window_start": date(2025, 2, 1),
            "window_end": date(2025, 2, 28),
            "channel": "weather_index", "driver_effect": -0.4,
            "peak_log_price_effect": 0.09,
            "basis": "desk_estimate",
            "basis_detail": "Revised pass-through after the second "
            "field report",
            "decay_days": 10,
            "description": "A claimed dry spell in the chili belt",
            "declared_by": "a.sharma", "declared_on": date(2025, 1, 22),
        },
        "peak revised on the second field report",
    )
    replacement_id = act.replacement_event_id
    assert replacement_id and replacement_id != event.event_id
    assert console.triage_state(event.event_id) == "superseded"
    # the standing draft is blocked, naming the replacement
    blockers = console.approval_blockers(draft)
    assert any(replacement_id in b for b in blockers)
    # new runs apply the replacement, never the replaced event
    fresh = guarded.run_forecast("chili", "guntur", as_of=date(2025, 1, 15))
    assert replacement_id in fresh.method.events_applied
    assert event.event_id not in fresh.method.events_applied
    assert verify_console(store) == []


def test_triage_state_machine_refusals(graded):
    store = graded["store"]
    events = EventService(store)
    console = _console(store)

    declared = _declare(
        events, commodity="groundnut",
        event_class="import_policy", channel="import_flow",
        window_start=date(2025, 4, 1), window_end=date(2025, 4, 30),
        peak_log_price_effect=-0.05,
        description="A claimed import-policy easing for groundnut",
        declared_on=date(2025, 3, 25),
    )
    # amending by restating the identical declaration is refused
    with pytest.raises(ConsoleValidationError):
        console.amend_event(
            declared.event_id, "a.sharma", "analyst", date(2025, 3, 26),
            {
                "event_class": "import_policy", "commodity": "groundnut",
                "window_start": date(2025, 4, 1),
                "window_end": date(2025, 4, 30),
                "channel": "import_flow",
                "peak_log_price_effect": -0.05,
                "basis": "desk_estimate",
                "basis_detail": "A desk estimate of the tariff's "
                "pass-through, stated for triage grading",
                "decay_days": 10,
                "description": "A claimed import-policy easing for "
                "groundnut",
                "declared_by": "a.sharma",
                "declared_on": date(2025, 3, 25),
            },
        )
    # placeholder actors are refused, as at every act door
    with pytest.raises(ConsoleValidationError):
        console.confirm_event(
            declared.event_id, "unknown", "analyst", date(2025, 3, 26)
        )
    console.confirm_event(
        declared.event_id, "a.sharma", "analyst", date(2025, 3, 26)
    )
    with pytest.raises(ConsoleStateError):
        console.confirm_event(
            declared.event_id, "a.sharma", "analyst", date(2025, 3, 27)
        )
    console.retire_event(
        declared.event_id, "a.sharma", "analyst", date(2025, 3, 28)
    )
    with pytest.raises(ConsoleStateError):
        console.retire_event(
            declared.event_id, "a.sharma", "analyst", date(2025, 3, 29)
        )
    with pytest.raises(ConsoleStateError):
        console.amend_event(
            declared.event_id, "a.sharma", "analyst", date(2025, 3, 29),
            {"event_class": "import_policy", "commodity": "groundnut",
             "window_start": date(2025, 4, 1),
             "window_end": date(2025, 4, 30), "channel": "import_flow",
             "peak_log_price_effect": -0.07, "basis": "desk_estimate",
             "basis_detail": "x", "decay_days": 10,
             "description": "y", "declared_by": "a.sharma",
             "declared_on": date(2025, 3, 29)},
        )
    # a retired event can be revived by a later confirm: the fold
    # is the latest act
    console.confirm_event(
        declared.event_id, "a.sharma", "analyst", date(2025, 3, 30)
    )
    assert console.triage_state(declared.event_id) == "confirmed"
    acts = store.list_event_triage_acts(declared.event_id)
    assert fold_triage_state(acts) == "confirmed"
    assert verify_console(store) == []


# --- the composed console + pages -------------------------------------------------


def test_console_view_and_pages(graded):
    store = graded["store"]
    console = _console(store)
    view = console.console_view()
    assert view["pack_version"] == "2026.10.1"
    assert view["morning_board"]["row_count"] > 0
    assert "counts" in view["review_queue"]
    assert set(view["triage_queue"]["counts_by_lane"]) <= {
        "verified", "unverified", "not_measurable",
    }
    assert len(view["preflights"]) == 14  # 7 commodities, 14 series
    assert view["problems"] == []

    desktop = render_console(view)
    assert "Operator console" in desktop
    assert "Forecast review queue" in desktop
    assert "Event triage queue" in desktop
    assert "Coverage pre-flights" in desktop

    phone = render_console_phone(view)
    assert "Desk inbox" in phone
    assert 'data-kind="approve_forecast"' in phone
    assert 'data-kind="confirm_event"' in phone
    assert "/console/actions" in phone


# --- the API surface ----------------------------------------------------------------


def test_api_console_surface(graded):
    store = graded["store"]
    client = TestClient(create_app(store))

    pack = client.get("/console/pack")
    assert pack.status_code == 200
    assert pack.json()["version"] == "2026.10.1"

    struck = client.post(
        "/console/preflights",
        json={"commodity": "coffee", "market": "bengaluru"},
    )
    assert struck.status_code == 201
    assert struck.json()["state"] == "gapped"
    assert struck.json()["problems"] == []
    preflight_id = struck.json()["report_id"]

    run = client.post(
        "/forecasts/run",
        json={"commodity": "coffee", "market": "bengaluru",
              "preflight_id": preflight_id},
    )
    assert run.status_code == 200
    assert run.json()["preflight"]["preflight_id"] == preflight_id
    mismatch = client.post(
        "/forecasts/run",
        json={"commodity": "wheat", "market": "indore",
              "preflight_id": preflight_id},
    )
    assert mismatch.status_code == 400

    # reject -> approve is a 409 over HTTP too
    draft = client.post(
        "/forecasts/run",
        json={"commodity": "cumin", "market": "unjha",
              "as_of": "2025-12-18"},
    ).json()
    rejected = client.post(
        f"/forecasts/{draft['forecast_id']}/reject",
        json={"rejected_by": "d.kaur", "role": "desk_head",
              "decided_on": "2026-01-03", "reason": "stale_inputs"},
    )
    assert rejected.status_code == 200
    refused = client.post(
        f"/forecasts/{draft['forecast_id']}/approve",
        json={"approver": "d.kaur", "role": "desk_head",
              "decided_on": "2026-01-04"},
    )
    assert refused.status_code == 409
    assert "rejected" in refused.json()["detail"]

    # triage over HTTP: a forged ban claim blocks approval until
    # a named analyst confirms it. The claim repeats the real
    # 2024 ban one year on — the measured window shows no such
    # step (the prior-year window is the ban-depressed one), so
    # the claim grades unverified.
    forged = client.post(
        "/market-events",
        json={
            "event_class": "export_restriction",
            "commodity": "basmati_rice",
            "window_start": "2025-09-01", "window_end": "2025-10-30",
            "channel": "export_flow", "driver_effect": 0.05,
            "peak_log_price_effect": -0.60, "basis": "desk_estimate",
            "basis_detail": "A desk estimate, stated for triage "
            "grading", "decay_days": 10,
            "description": "A claimed export restriction on basmati",
            "declared_by": "a.sharma", "declared_on": "2025-08-05",
        },
    )
    assert forged.status_code == 201
    forged_id = forged.json()["event_id"]
    shocked = client.post(
        "/forecasts/run",
        json={"commodity": "basmati_rice",
              "market": "delhi_khari_baoli", "as_of": "2025-08-15"},
    ).json()
    assert forged_id in shocked["method"]["events_applied"]
    events_view = client.get(f"/forecasts/{shocked['forecast_id']}/events")
    flag = next(
        e for e in events_view.json()["events"]
        if e["event_id"] == forged_id
    )
    assert flag["verification_status"] == "unverified"
    assert flag["triage_state"] == "declared"
    assert events_view.json()["official_blockers"]
    blocked = client.post(
        f"/forecasts/{shocked['forecast_id']}/approve",
        json={"approver": "d.kaur", "role": "desk_head",
              "decided_on": "2025-08-20"},
    )
    assert blocked.status_code == 409
    assert forged_id in blocked.json()["detail"]
    confirmed = client.post(
        f"/market-events/{forged_id}/triage/confirm",
        json={"actor": "a.sharma", "role": "analyst",
              "acted_on": "2025-08-20", "note": "circular checked"},
    )
    assert confirmed.status_code == 200
    approved = client.post(
        f"/forecasts/{shocked['forecast_id']}/approve",
        json={"approver": "d.kaur", "role": "desk_head",
              "decided_on": "2025-08-20"},
    )
    assert approved.status_code == 200

    console_json = client.get("/console")
    assert console_json.status_code == 200
    assert console_json.json()["problems"] == []
    assert "Operator console" in client.get("/console/html").text
    phone = client.get("/console/phone")
    assert phone.status_code == 200
    assert "Desk inbox" in phone.text
    assert client.get("/console/verify").json()["problems"] == []
    queue = client.get("/console/review-queue").json()["rows"]
    assert all(r["forecast_id"] != draft["forecast_id"] for r in queue)


# --- phone action parity over HTTP (F20-MF2) -----------------------------------------


def _fixture_forecast(commodity, market, p50, as_of=HISTORY_END):
    days = [
        ForecastDay(
            forecast_date=as_of + timedelta(days=i + 1), baseline=p50,
            contributions={}, events_adjustment=0.0,
            p10=p50 - 90.0, p50=p50, p90=p50 + 90.0,
        )
        for i in range(90)
    ]
    summaries = [
        HorizonSummary(
            horizon_days=h, forecast_date=days[h - 1].forecast_date,
            baseline=p50, contributions={}, events_adjustment=0.0,
            p10=p50 - 90.0, p50=p50, p90=p50 + 90.0,
        )
        for h in (7, 30, 90)
    ]
    method = ForecastMethod(
        engine_version="fixture-1",
        baseline=BaselineMethod(
            intercept=0.0, trend_per_year=0.0, seasonal_sin=0.0,
            seasonal_cos=0.0, anchor_date=as_of, n_obs=300,
        ),
        drivers={},
        residuals=ResidualMethod(
            sigma=0.01, rho=0.0, q10=-0.01, q90=0.01, window_obs=300
        ),
        sparsity=SparsityMethod(
            observed_days=300, calendar_days=300, multiplier=1.0
        ),
        attribution_order=[], events_applied=[],
    )
    forecast = Forecast(
        forecast_id="FCST-pending", commodity=commodity, market=market,
        as_of=as_of, engine_version="fixture-1", method=method,
        days=days, lines=[], horizons_summary=summaries,
        missing_drivers=[], accuracy=_attachment("measured"),
    )
    forecast.forecast_id = forecast_content_id(forecast)
    return forecast


def test_phone_action_parity_over_http(tmp_path):
    """The same act, struck through the phone's action door and
    through the canonical endpoint, is the same artefact —
    byte for byte — on twin stores holding the same record."""
    forecast = _fixture_forecast("wheat", "delhi_khari_baoli", 2250.0)
    alert = AlertInstance(
        alert_id="ALT-fixtureparity",
        subscription_id="SUB-fixture", subscriber="d.kaur",
        kind="buy_signal", commodity="wheat",
        market="delhi_khari_baoli", severity="major",
        trigger_id="SIG-fixture", trigger_summary={"value": "buy_now"},
        raised_at=datetime(2026, 1, 5, 9, 0),
        pack_version=load_alert_pack().version,
        scope_note="signal only — no trade is placed",
    )
    clients = []
    for name in ("a", "b"):
        store = build_store(str(tmp_path / f"{name}.db"))
        store.insert_forecast(forecast)
        store.insert_alert(alert)
        clients.append(TestClient(create_app(store)))
    desktop, phone = clients

    canonical = desktop.post(
        f"/forecasts/{forecast.forecast_id}/approve",
        json={"approver": "d.kaur", "role": "desk_head",
              "decided_on": "2026-01-06"},
    )
    assert canonical.status_code == 200
    via_phone = phone.post(
        "/console/actions",
        json={"kind": "approve_forecast",
              "forecast_id": forecast.forecast_id,
              "approver": "d.kaur", "role": "desk_head",
              "decided_on": "2026-01-06"},
    )
    assert via_phone.status_code == 200
    assert via_phone.json() == canonical.json()

    canonical_act = desktop.post(
        f"/alerts/{alert.alert_id}/acknowledge",
        json={"actor": "d.kaur", "role": "desk_head",
              "at": "2026-01-06T10:30:00", "note": "seen"},
    )
    assert canonical_act.status_code == 200
    phone_act = phone.post(
        "/console/actions",
        json={"kind": "acknowledge_alert", "alert_id": alert.alert_id,
              "actor": "d.kaur", "role": "desk_head",
              "acted_at": "2026-01-06T10:30:00", "note": "seen"},
    )
    assert phone_act.status_code == 200
    assert phone_act.json() == canonical_act.json()


# --- the CLI -------------------------------------------------------------------------


def test_cli_console(graded, capsys):
    db = graded["db"]
    assert console_cli.main(["--db", db, "pack"]) == 0
    assert console_cli.main(
        ["--db", db, "preflight", "groundnut", "gondal"]
    ) == 0
    assert console_cli.main(["--db", db, "queue"]) == 0
    assert console_cli.main(["--db", db, "triage"]) == 0
    assert console_cli.main(["--db", db, "verify"]) == 0
    capsys.readouterr()

    store = graded["store"]
    service = ForecastService(store, OfflineModel())
    draft = service.run_forecast(
        "groundnut", "gondal", as_of=date(2025, 11, 30)
    )
    assert console_cli.main(
        ["--db", db, "reject", draft.forecast_id, "--by", "d.kaur",
         "--role", "desk_head", "--reason", "duplicate_of_newer_run",
         "--on", "2026-01-03"]
    ) == 0
    assert console_cli.main(
        ["--db", db, "reject", draft.forecast_id, "--by", "d.kaur",
         "--role", "desk_head", "--reason", "stale_inputs",
         "--on", "2026-01-04"]
    ) == 2
    capsys.readouterr()


# --- Postgres parity -------------------------------------------------------------------


PG_URL = os.environ.get("FMCG_TEST_DATABASE_URL")


@pytest.mark.skipif(not PG_URL, reason="FMCG_TEST_DATABASE_URL not set")
def test_postgres_parity(graded):
    lite = graded["store"]
    pg = build_store(database_url=PG_URL)
    pg_truth = build_truth_store(database_url=PG_URL)
    load_dataset(pg, pg_truth, SEED)
    run_all(pg)
    grading = build_sentiment_grading_store(database_url=PG_URL)
    load_sentiment_corpus(pg, grading, SEED)
    SentimentService(pg, OfflineModel()).run_pipeline()
    EventService(pg).seed_historical(pg.get_manifest())

    lite_console = _console(lite)
    pg_console = _console(pg)
    for series in (("coffee", "bengaluru"), ("wheat", "delhi_khari_baoli")):
        lite_report = lite_console.strike_preflight(*series)
        pg_report = pg_console.strike_preflight(*series)
        assert pg_report.model_dump(mode="json") == lite_report.model_dump(
            mode="json"
        )

    lite_service = ForecastService(lite, OfflineModel())
    pg_service = ForecastService(pg, OfflineModel())
    lite_draft = lite_service.run_forecast(
        "soybean", "nagpur", as_of=date(2025, 10, 31)
    )
    pg_draft = pg_service.run_forecast(
        "soybean", "nagpur", as_of=date(2025, 10, 31)
    )
    assert pg_draft.forecast_id == lite_draft.forecast_id
    lite_act = lite_console.reject_forecast(
        lite_draft.forecast_id, "d.kaur", "desk_head",
        date(2026, 1, 3), "stale_inputs",
    )
    pg_act = pg_console.reject_forecast(
        pg_draft.forecast_id, "d.kaur", "desk_head",
        date(2026, 1, 3), "stale_inputs",
    )
    assert pg_act.model_dump(mode="json") == lite_act.model_dump(mode="json")

    lite_events, pg_events = EventService(lite), EventService(pg)
    lite_event = _declare(lite_events, commodity="cumin",
                          event_class="demand_shock", channel="modal_price",
                          window_start=date(2025, 9, 1),
                          window_end=date(2025, 9, 30),
                          peak_log_price_effect=0.04,
                          description="A claimed festive demand step")
    pg_event = _declare(pg_events, commodity="cumin",
                        event_class="demand_shock", channel="modal_price",
                        window_start=date(2025, 9, 1),
                        window_end=date(2025, 9, 30),
                        peak_log_price_effect=0.04,
                        description="A claimed festive demand step")
    assert pg_event.event_id == lite_event.event_id
    lite_confirm = lite_console.confirm_event(
        lite_event.event_id, "a.sharma", "analyst", date(2025, 9, 5)
    )
    pg_confirm = pg_console.confirm_event(
        pg_event.event_id, "a.sharma", "analyst", date(2025, 9, 5)
    )
    assert pg_confirm.model_dump(mode="json") == lite_confirm.model_dump(
        mode="json"
    )
    assert verify_console(pg) == []
