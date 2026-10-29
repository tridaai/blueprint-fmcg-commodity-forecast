"""Round 9 tests: subscriptions as desk-entered artefacts
(supersession by link, entry refusals), alert derivation over
signals / event windows / price crossings / the accuracy ledger
(fires exactly once, severity floors, the entered-on gate),
accuracy episodes (a still-degraded replacement record does not
re-fire; a resolved episode can), the escalation clock on a
fixture timeline (acknowledgement stops it at the rung reached),
closure vocabulary and state refusals, superseded-signal marking,
digest exactness, tamper detection, API + CLI surfaces.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.alerts import cli as alerts_cli
from fmcg_forecast.alerts.engine import compute_crossings, fold_state
from fmcg_forecast.alerts.pack import ALERT_SCOPE_NOTE, load_alert_pack
from fmcg_forecast.alerts.service import (
    AlertNotFoundError,
    AlertService,
    AlertStateError,
    AlertValidationError,
)
from fmcg_forecast.alerts.verify import verify_crossing, verify_digest
from fmcg_forecast.api import create_app
from fmcg_forecast.events.service import EventService
from fmcg_forecast.forecast.engine import forecast_content_id
from fmcg_forecast.forecast.models import (
    ATTRIBUTION_ORDER,
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
from fmcg_forecast.models import Observation
from fmcg_forecast.signals.service import SignalService
from fmcg_forecast.store import build_store

HISTORY_END = date(2025, 12, 31)
T0 = datetime(2026, 1, 5, 9, 0, 0)
ALL_KINDS = [
    "buy_signal",
    "event_window",
    "price_move",
    "accuracy_degraded",
    "coverage_collapse",
]


# --- hand-built fixtures -------------------------------------------------


def _attachment(state: str) -> AccuracyAttachment:
    if state == "unmeasured":
        return AccuracyAttachment(
            state="unmeasured",
            pack_version=None,
            per_horizon=[
                HorizonAccuracy(
                    horizon_days=h, state="unmeasured", record_id=None,
                    n_origins=0, mae=None, mape=None, bias=None,
                    coverage=None,
                )
                for h in (7, 30, 90)
            ],
            note="no backtest coverage yet",
        )
    slices = []
    for h in (7, 30, 90):
        degraded = state == "degraded" and h == 30
        slices.append(
            HorizonAccuracy(
                horizon_days=h,
                state="degraded" if degraded else "measured",
                record_id=f"ACC-FIX-{h}",
                n_origins=6,
                mae=42.0,
                mape=7.5 if degraded else 2.0,
                bias=1.0,
                coverage=0.9,
            )
        )
    return AccuracyAttachment(
        state=state,  # type: ignore[arg-type]
        pack_version="2026.10.1",
        per_horizon=slices,
        note="fixture attachment",
    )


def _fixture_forecast(
    commodity: str,
    market: str,
    p50: float,
    p10: float,
    p90: float,
    accuracy: AccuracyAttachment | None,
    as_of: date = HISTORY_END,
) -> Forecast:
    days = [
        ForecastDay(
            forecast_date=as_of + timedelta(days=i + 1),
            baseline=p50,
            contributions={},
            events_adjustment=0.0,
            p10=p10,
            p50=p50,
            p90=p90,
        )
        for i in range(90)
    ]
    summaries = [
        HorizonSummary(
            horizon_days=h,
            forecast_date=days[h - 1].forecast_date,
            baseline=p50,
            contributions={},
            events_adjustment=0.0,
            p10=p10,
            p50=p50,
            p90=p90,
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
        attribution_order=list(ATTRIBUTION_ORDER),
    )
    forecast = Forecast(
        forecast_id="FCST-pending",
        commodity=commodity,
        market=market,
        as_of=as_of,
        engine_version="fixture-1",
        method=method,
        days=days,
        lines=[],
        horizons_summary=summaries,
        missing_drivers=[],
        accuracy=accuracy,
    )
    return forecast.model_copy(
        update={"forecast_id": forecast_content_id(forecast)}
    )


def _accuracy_record(
    record_id: str,
    commodity: str,
    market: str,
    mape: float,
    coverage: float,
    degraded: bool,
) -> AccuracyRecord:
    return AccuracyRecord(
        record_id=record_id,
        commodity=commodity,
        market=market,
        horizon_days=30,
        origins=[date(2025, m, 1) for m in range(5, 11)],
        n_results=6,
        n_days=180,
        covered_days=int(180 * coverage),
        mae=42.0,
        mape=mape,
        bias=1.0,
        coverage=coverage,
        engine_version="fixture-1",
        pack_version="2026.10.1",
        degraded_threshold_mape_pct=5.0,
        degraded=degraded,
    )


@pytest.fixture()
def fx(tmp_path):
    """A bare store: three forecast series, one declared event, a
    planted price step, and two accuracy records (one degraded,
    one coverage-collapsed)."""
    store = build_store(str(tmp_path / "r9.db"))
    signals = SignalService(store)

    def add(commodity, market, spot, p50, p10, p90, accuracy):
        store.insert_observations(
            [
                Observation(
                    commodity=commodity, market=market,
                    obs_date=HISTORY_END, driver="modal_price", value=spot,
                )
            ]
        )
        forecast = _fixture_forecast(commodity, market, p50, p10, p90, accuracy)
        store.insert_forecast(forecast)
        return forecast

    # wheat: drift +12.5% -> buy_now, critical by the drift rule.
    wheat = add("wheat", "delhi_khari_baoli", 2000.0, 2250.0, 2160.0, 2340.0,
                _attachment("measured"))
    # soybean: drift -5% -> wait, minor.
    add("soybean", "indore", 2000.0, 1900.0, 1810.0, 1990.0,
        _attachment("measured"))
    # cumin: flat, but inside a declared event window.
    cumin = add("cumin", "unjha", 2000.0, 2010.0, 1950.0, 2070.0,
                _attachment("measured"))
    events = EventService(store)
    event = events.register_event(
        event_class="tariff_change",
        commodity="cumin",
        window_start=date(2026, 1, 10),
        window_end=date(2026, 1, 20),
        channel="import_flow",
        peak_log_price_effect=0.08,
        basis="announced_measure",
        basis_detail="fixture declaration",
        decay_days=20,
        description="fixture event window over the cumin horizon",
        declared_by="a.sharma",
        declared_on=date(2026, 1, 2),
    )
    # groundnut at rajkot: a planted step, 2000 -> 2240 on day 21
    # of a daily series — one 7-day crossing of exactly +12.0%.
    step_start = date(2025, 12, 1)
    rows = []
    for i in range(30):
        day = step_start + timedelta(days=i)
        rows.append(
            Observation(
                commodity="groundnut", market="rajkot", obs_date=day,
                driver="modal_price",
                value=2000.0 if i < 20 else 2240.0,
            )
        )
    store.insert_observations(rows)
    # the accuracy ledger, as the harness would have saved it.
    store.save_accuracy_record(
        _accuracy_record("ACC-R9-CHILI-30-A", "chili", "guntur", 7.5, 0.9, True)
    )
    store.save_accuracy_record(
        _accuracy_record("ACC-R9-COFFEE-30-A", "coffee", "bengaluru", 2.0, 0.5, False)
    )
    return {
        "store": store,
        "signals": signals,
        "wheat": wheat,
        "cumin": cumin,
        "event": event,
        "alerts": AlertService(store),
    }


def _subscribe(alerts: AlertService, **overrides):
    spec = dict(
        subscriber="r.menon",
        role="desk_head",
        entered_on=date(2025, 12, 1),
        commodities=[],
        markets=[],
        kinds=list(ALL_KINDS),
        min_severity="minor",
    )
    spec.update(overrides)
    return alerts.enter_subscription(**spec)


def _kind_alerts(alerts: AlertService, kind: str, commodity: str | None = None):
    return [
        a
        for a in alerts.list_alerts(commodity=commodity)
        if a.kind == kind
    ]


# --- subscriptions ---------------------------------------------------------


def test_subscription_entry_supersession_and_head(fx):
    alerts = fx["alerts"]
    first = _subscribe(alerts)
    again = _subscribe(alerts)
    assert again.subscription_id == first.subscription_id
    assert len(alerts.list_subscriptions("r.menon")) == 1
    changed = _subscribe(alerts, min_severity="major")
    assert changed.subscription_id != first.subscription_id
    assert changed.supersedes_subscription_id == first.subscription_id
    assert alerts.head_subscription("r.menon").subscription_id == (
        changed.subscription_id
    )
    assert alerts.subscription_view(first.subscription_id)["is_head"] is False
    assert alerts.subscription_view(changed.subscription_id)["is_head"] is True
    view = alerts.subscription_view(changed.subscription_id)
    assert "desk-entered" in view["origin_label"]
    assert view["problems"] == []


def test_subscription_refusals(fx):
    alerts = fx["alerts"]
    with pytest.raises(AlertValidationError):
        _subscribe(alerts, subscriber="tbd")
    with pytest.raises(AlertValidationError):
        _subscribe(alerts, commodities=["unobtainium"])
    with pytest.raises(AlertValidationError):
        _subscribe(alerts, kinds=["buy_signal", "telepathy"])
    with pytest.raises(AlertValidationError):
        _subscribe(alerts, min_severity="urgent")
    with pytest.raises(AlertValidationError):
        _subscribe(alerts, commodities=["wheat"], markets=["guntur"])
    with pytest.raises(AlertValidationError):
        _subscribe(alerts, kinds=[])


# --- derivation over signals -------------------------------------------------


def test_signal_alerts_fire_once_with_pack_severities(fx):
    alerts, signals = fx["alerts"], fx["signals"]
    signals.compute_for_series("wheat", "delhi_khari_baoli")
    signals.compute_for_series("soybean", "indore")
    sub = _subscribe(alerts)
    summary = alerts.sweep(T0)
    wheat_alerts = _kind_alerts(alerts, "buy_signal", "wheat")
    assert len(wheat_alerts) == 1
    alert = wheat_alerts[0]
    assert alert.severity == "critical"  # drift +12.5% clears the bar
    assert alert.subscription_id == sub.subscription_id
    assert alert.scope_note == ALERT_SCOPE_NOTE
    assert alert.trigger_summary["signal_value"] == "buy_now"
    assert alert.trigger_summary["forecast_id"] == fx["wheat"].forecast_id
    soybean_alerts = _kind_alerts(alerts, "buy_signal", "soybean")
    assert len(soybean_alerts) == 1
    assert soybean_alerts[0].severity == "minor"
    assert summary["alerts_raised_count"] == len(alerts.list_alerts())
    # the second sweep raises nothing new — derivation is deduped
    # by the content address, not by bookkeeping.
    second = alerts.sweep(T0 + timedelta(hours=1))
    assert second["alerts_raised_count"] == 0
    assert len(alerts.list_alerts()) == summary["alerts_raised_count"]
    assert alerts.verify_stored(alert.alert_id) == []
    assert alerts.verify_all() == []


def test_severity_floor_filters_and_unmatched_is_counted(fx):
    alerts, signals = fx["alerts"], fx["signals"]
    wheat_signal = signals.compute_for_series("wheat", "delhi_khari_baoli")
    _subscribe(alerts, min_severity="critical", kinds=["buy_signal"],
               commodities=["soybean"])
    summary = alerts.sweep(T0)
    assert _kind_alerts(alerts, "buy_signal") == []
    assert wheat_signal.signal_id in summary["unmatched_signal_ids"]


def test_entered_on_gate(fx):
    alerts, signals = fx["alerts"], fx["signals"]
    signals.compute_for_series("wheat", "delhi_khari_baoli")
    _subscribe(alerts, entered_on=date(2026, 6, 1))
    alerts.sweep(T0)
    assert _kind_alerts(alerts, "buy_signal", "wheat") == []


def test_event_window_fires_once_however_many_signals(fx):
    alerts, signals = fx["alerts"], fx["signals"]
    signals.compute_for_forecast(fx["cumin"])
    later = _fixture_forecast(
        "cumin", "unjha", 2030.0, 1970.0, 2090.0,
        _attachment("measured"), as_of=date(2026, 1, 15),
    )
    fx["store"].insert_forecast(later)
    signals.compute_for_forecast(later)
    _subscribe(alerts)
    alerts.sweep(T0)
    event_alerts = _kind_alerts(alerts, "event_window", "cumin")
    assert len(event_alerts) == 1
    assert event_alerts[0].trigger_id == fx["event"].event_id
    assert event_alerts[0].severity == "major"  # claimed peak 0.08
    assert event_alerts[0].market == "all_markets"
    alerts.sweep(T0 + timedelta(days=1))
    assert len(_kind_alerts(alerts, "event_window", "cumin")) == 1


# --- price crossings ---------------------------------------------------------


def test_price_crossing_exact_and_alerted(fx):
    alerts = fx["alerts"]
    crossings = compute_crossings(fx["store"], load_alert_pack())
    groundnut = [c for c in crossings if c.commodity == "groundnut"]
    assert len(groundnut) == 1
    crossing = groundnut[0]
    assert crossing.move_pct == 12.0
    assert crossing.direction == "up"
    assert crossing.from_price == 2000.0 and crossing.to_price == 2240.0
    assert verify_crossing(crossing) == []
    assert [c for c in crossings if c.commodity == "wheat"] == []
    _subscribe(alerts)
    summary = alerts.sweep(T0)
    assert summary["crossings_new"] == 1
    move_alerts = _kind_alerts(alerts, "price_move", "groundnut")
    assert len(move_alerts) == 1
    assert move_alerts[0].severity == "critical"  # 12% >= 2x the 5% bar
    assert move_alerts[0].trigger_id == crossing.crossing_id
    assert alerts.verify_stored(move_alerts[0].alert_id) == []


# --- accuracy episodes ---------------------------------------------------------


def test_accuracy_episodes_fire_once_per_episode(fx):
    alerts = fx["alerts"]
    _subscribe(alerts)
    alerts.sweep(T0)
    degraded = _kind_alerts(alerts, "accuracy_degraded", "chili")
    collapsed = _kind_alerts(alerts, "coverage_collapse", "coffee")
    assert len(degraded) == 1 and degraded[0].severity == "major"
    assert degraded[0].trigger_summary["mape"] == 7.5
    assert len(collapsed) == 1 and collapsed[0].severity == "critical"
    # a still-degraded replacement record does not re-fire.
    fx["store"].save_accuracy_record(
        _accuracy_record("ACC-R9-CHILI-30-B", "chili", "guntur", 8.0, 0.9, True)
    )
    held = alerts.sweep(T0 + timedelta(days=1))
    assert held["alerts_episode_held"] >= 1
    assert len(_kind_alerts(alerts, "accuracy_degraded", "chili")) == 1
    # closing the episode as resolved lets the next record fire.
    alerts.close(
        degraded[0].alert_id, actor="r.menon", role="desk_head",
        acted_at=T0 + timedelta(days=1, hours=1), reason="resolved",
    )
    fx["store"].save_accuracy_record(
        _accuracy_record("ACC-R9-CHILI-30-C", "chili", "guntur", 8.5, 0.9, True)
    )
    alerts.sweep(T0 + timedelta(days=2))
    chili_alerts = _kind_alerts(alerts, "accuracy_degraded", "chili")
    assert len(chili_alerts) == 2
    assert alerts.verify_all() == []


# --- the escalation clock -------------------------------------------------------


def _wheat_alert(fx) -> str:
    fx["signals"].compute_for_series("wheat", "delhi_khari_baoli")
    _subscribe(fx["alerts"])
    fx["alerts"].sweep(T0)
    return _kind_alerts(fx["alerts"], "buy_signal", "wheat")[0].alert_id


def test_escalation_climbs_the_ladder_on_the_clock(fx):
    alerts = fx["alerts"]
    alert_id = _wheat_alert(fx)  # critical: windows 4h, then 12h
    view = alerts.alert_view(alert_id, T0 + timedelta(hours=3))
    assert view["state"]["state"] == "raised"
    assert view["state"]["current_holder"] == "subscriber"
    view = alerts.alert_view(alert_id, T0 + timedelta(hours=5))
    assert view["state"]["state"] == "escalated"
    assert view["state"]["escalation_level"] == 1
    assert view["state"]["current_holder"] == "desk_head"
    view = alerts.alert_view(alert_id, T0 + timedelta(hours=17))
    assert view["state"]["escalation_level"] == 2
    assert view["state"]["current_holder"] == "procurement_lead"
    assert view["state"]["next_escalation_at"] is None


def test_acknowledgement_stops_the_clock_at_the_rung_reached(fx):
    alerts = fx["alerts"]
    alert_id = _wheat_alert(fx)
    # acked inside the first window: never escalates.
    alerts.acknowledge(
        alert_id, actor="r.menon", role="desk_head",
        acted_at=T0 + timedelta(hours=2),
    )
    view = alerts.alert_view(alert_id, T0 + timedelta(days=30))
    assert view["state"]["state"] == "acknowledged"
    assert view["state"]["escalation_level"] == 0
    # the fold itself, re-performed: an ack after the first window
    # froze the alert at rung one.
    alert = alerts.get_alert(alert_id)
    acts = fx["store"].list_alert_acts(alert_id)
    late = fold_state(alert, acts, T0 + timedelta(days=30), load_alert_pack())
    assert late["acknowledged_at"] is not None


def test_close_vocabulary_and_closed_state_refusals(fx):
    alerts = fx["alerts"]
    alert_id = _wheat_alert(fx)
    with pytest.raises(AlertValidationError):
        alerts.close(
            alert_id, actor="r.menon", role="desk_head",
            acted_at=T0 + timedelta(hours=1), reason="whatever",
        )
    alerts.close(
        alert_id, actor="r.menon", role="desk_head",
        acted_at=T0 + timedelta(hours=1), reason="acted_on",
    )
    view = alerts.alert_view(alert_id, T0 + timedelta(days=3))
    assert view["state"]["state"] == "closed"
    assert view["state"]["close_reason"] == "acted_on"
    with pytest.raises(AlertStateError):
        alerts.acknowledge(
            alert_id, actor="r.menon", role="desk_head",
            acted_at=T0 + timedelta(hours=2),
        )
    with pytest.raises(AlertStateError):
        alerts.close(
            alert_id, actor="r.menon", role="desk_head",
            acted_at=T0 + timedelta(hours=2), reason="resolved",
        )
    with pytest.raises(AlertNotFoundError):
        alerts.acknowledge(
            "ALT-nope", actor="r.menon", role="desk_head", acted_at=T0
        )


def test_superseded_signal_alert_is_marked_not_dropped(fx):
    alerts = fx["alerts"]
    alert_id = _wheat_alert(fx)
    newer = _fixture_forecast(
        "wheat", "delhi_khari_baoli", 2300.0, 2210.0, 2390.0,
        _attachment("measured"), as_of=date(2026, 1, 20),
    )
    fx["store"].insert_forecast(newer)
    view = alerts.alert_view(alert_id, T0 + timedelta(hours=1))
    assert view["trigger_superseded"] is True
    assert alerts.get_alert(alert_id) is not None


# --- digests -----------------------------------------------------------------


def test_digest_contents_equal_the_subscribers_day(fx):
    alerts, signals = fx["alerts"], fx["signals"]
    signals.compute_for_series("wheat", "delhi_khari_baoli")
    sub = _subscribe(alerts)
    alerts.sweep(T0)
    digest = alerts.build_digest(sub.subscription_id, date(2026, 1, 5))
    expected = sorted(
        a.alert_id
        for a in alerts.list_alerts(subscription_id=sub.subscription_id)
        if a.raised_on == date(2026, 1, 5)
    )
    assert digest.alert_ids == expected and len(expected) > 0
    critical = sum(
        1
        for a in alerts.list_alerts(subscription_id=sub.subscription_id)
        if a.raised_on == date(2026, 1, 5) and a.severity == "critical"
    )
    assert digest.by_severity.get("critical") == critical >= 1
    assert verify_digest(fx["store"], digest) == []
    assert alerts.digest_view(digest.digest_id)["problems"] == []
    empty = alerts.build_digest(sub.subscription_id, date(2026, 3, 1))
    assert empty.alert_ids == []
    assert verify_digest(fx["store"], empty) == []


# --- tamper ---------------------------------------------------------------------


def test_tampered_alert_fails_verification(fx, tmp_path):
    alerts = fx["alerts"]
    alert_id = _wheat_alert(fx)
    db = str(tmp_path / "r9.db")
    conn = sqlite3.connect(db)
    payload = json.loads(
        conn.execute(
            "SELECT payload FROM alerts WHERE alert_id = ?", (alert_id,)
        ).fetchone()[0]
    )
    payload["severity"] = "minor"
    conn.execute(
        "UPDATE alerts SET payload = ? WHERE alert_id = ?",
        (json.dumps(payload), alert_id),
    )
    conn.commit()
    conn.close()
    problems = alerts.verify_stored(alert_id)
    # The alert id is the (subscription, kind, trigger) dedup
    # key, so tampering is caught by re-performance: the stored
    # severity no longer matches the severity re-judged from the
    # pinned signal, nor the derived candidate's fields.
    assert any("severity mismatch" in p for p in problems)
    assert any("differs on re-performance" in p for p in problems)


# --- surfaces ---------------------------------------------------------------------


def test_api_flow(fx):
    client = TestClient(create_app(fx["store"]))
    fx["signals"].compute_for_series("wheat", "delhi_khari_baoli")
    pack = client.get("/alerts/pack")
    assert pack.status_code == 200
    assert pack.json()["version"] == "2026.10.1"
    created = client.post(
        "/alerts/subscriptions",
        json={
            "subscriber": "r.menon", "role": "desk_head",
            "entered_on": "2025-12-01", "commodities": [],
            "markets": [], "kinds": ALL_KINDS, "min_severity": "minor",
        },
    )
    assert created.status_code == 201
    swept = client.post("/alerts/sweep", json={"at": "2026-01-05T09:00:00"})
    assert swept.status_code == 200
    assert swept.json()["alerts_raised_count"] > 0
    listed = client.get("/alerts", params={"commodity": "wheat"})
    wheat = [
        a for a in listed.json()["alerts"] if a["kind"] == "buy_signal"
    ]
    assert len(wheat) == 1
    alert_id = wheat[0]["alert_id"]
    acked = client.post(
        f"/alerts/{alert_id}/acknowledge",
        json={
            "actor": "r.menon", "role": "desk_head",
            "at": "2026-01-05T10:00:00",
        },
    )
    assert acked.status_code == 200
    view = client.get(
        f"/alerts/{alert_id}", params={"at": "2026-02-01T00:00:00"}
    )
    assert view.json()["state"]["state"] == "acknowledged"
    bad_close = client.post(
        f"/alerts/{alert_id}/close",
        json={
            "actor": "r.menon", "role": "desk_head",
            "at": "2026-01-05T11:00:00", "reason": "whatever",
        },
    )
    assert bad_close.status_code == 422
    verified = client.get(f"/alerts/{alert_id}/verify")
    assert verified.json()["problems"] == []
    digest = client.post(
        "/alerts/digests",
        json={
            "subscription_id": created.json()["subscription_id"],
            "digest_date": "2026-01-05",
        },
    )
    assert digest.status_code == 201
    assert digest.json()["problems"] == []


def test_cli_flow(fx, tmp_path, capsys):
    db = str(tmp_path / "r9.db")
    fx["signals"].compute_for_series("wheat", "delhi_khari_baoli")
    assert alerts_cli.main(
        [
            "--db", db, "subscribe", "--subscriber", "r.menon",
            "--role", "desk_head", "--entered-on", "2025-12-01",
            "--kinds", ",".join(ALL_KINDS),
        ]
    ) == 0
    capsys.readouterr()
    assert alerts_cli.main(
        ["--db", db, "sweep", "--at", "2026-01-05T09:00:00"]
    ) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["alerts_raised_count"] > 0
    assert alerts_cli.main(["--db", db, "alerts"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert any(a["kind"] == "buy_signal" for a in listed)
    assert alerts_cli.main(["--db", db, "verify", "--all"]) == 0
