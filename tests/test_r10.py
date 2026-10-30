"""Round 10 tests: thin-data depth (multi-window coverage,
driver states with last observed dates, per-horizon confidence
tiers under the pack's ladder and caps, tier-claim
contradictions, tamper detection) and assisted intake with
maker–checker (pending invisibility, self-check refusal,
exactly one landed fact with both names in its provenance,
rejection landing nothing, chain tampering), API + CLI.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.api import create_app
from fmcg_forecast.forecast.engine import forecast_content_id
from fmcg_forecast.forecast.models import (
    ATTRIBUTION_ORDER,
    AccuracyAttachment,
    AccuracyRecord,
    BaselineMethod,
    ContributionLine,
    Forecast,
    ForecastDay,
    ForecastMethod,
    HorizonAccuracy,
    HorizonSummary,
    ResidualMethod,
    SparsityMethod,
)
from fmcg_forecast.intake import cli as intake_cli
from fmcg_forecast.intake.service import (
    IntakeService,
    IntakeStateError,
    IntakeValidationError,
)
from fmcg_forecast.models import Observation
from fmcg_forecast.sentiment.models import SentimentIndex
from fmcg_forecast.store import build_store
from fmcg_forecast.thin import cli as thin_cli
from fmcg_forecast.thin.engine import operating_days
from fmcg_forecast.thin.pack import load_thin_data_pack
from fmcg_forecast.thin.service import ThinDataService
from fmcg_forecast.catalogue import BY_NAME

AS_OF = date(2025, 12, 31)
T0 = datetime(2025, 12, 29, 18, 0, 0)


# --- fixtures ---------------------------------------------------------------


def _wiggle(base: float, i: int) -> float:
    return round(base * (1 + 0.012 * math.sin(i * 0.7)), 2)


def _operating(spec, start, end):
    return operating_days(spec, start, end)


def _fill_series(store, commodity, base, *, arrivals_until=None):
    """A full year of operating-day rows for one series."""
    spec = BY_NAME[commodity]
    market = spec.markets[0].market
    days = _operating(spec, date(2025, 1, 1), AS_OF)
    rows = []
    for i, day in enumerate(days):
        rows.append(
            Observation(commodity=commodity, market=market, obs_date=day,
                        driver="modal_price", value=_wiggle(base, i))
        )
        if commodity == "coffee":
            drivers = ("arrivals", "weather_index")
        else:
            drivers = (
                "arrivals", "stock_level", "import_flow",
                "export_flow", "weather_index",
            )
        for driver in drivers:
            if driver == "arrivals" and arrivals_until and day > arrivals_until:
                continue
            rows.append(
                Observation(commodity=commodity, market=market, obs_date=day,
                            driver=driver, value=10.0)
            )
    store.insert_observations(rows)
    return market


def _record(record_id, commodity, market, horizon, mape=2.0, coverage=0.9):
    return AccuracyRecord(
        record_id=record_id, commodity=commodity, market=market,
        horizon_days=horizon,
        origins=[date(2025, m, 1) for m in range(5, 11)],
        n_results=6, n_days=180, covered_days=int(180 * coverage),
        mae=42.0, mape=mape, bias=1.0, coverage=coverage,
        engine_version="fixture-1", pack_version="2026.10.1",
        degraded_threshold_mape_pct=5.0, degraded=False,
    )


def _attachment(records):
    if records is None:
        return AccuracyAttachment(
            state="unmeasured", pack_version=None,
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
    return AccuracyAttachment(
        state="measured", pack_version="2026.10.1",
        per_horizon=[
            HorizonAccuracy(
                horizon_days=r.horizon_days, state="measured",
                record_id=r.record_id, n_origins=r.n_results,
                mae=r.mae, mape=r.mape, bias=r.bias, coverage=r.coverage,
            )
            for r in records
        ],
        note="fixture attachment",
    )


def _forecast(commodity, market, bands, attachment, lines=None, missing=None):
    days = [
        ForecastDay(
            forecast_date=AS_OF + timedelta(days=i + 1),
            baseline=bands[30][1], contributions={}, events_adjustment=0.0,
            p10=bands[30][0], p50=bands[30][1], p90=bands[30][2],
        )
        for i in range(90)
    ]
    summaries = [
        HorizonSummary(
            horizon_days=h, forecast_date=days[h - 1].forecast_date,
            baseline=bands[h][1], contributions={}, events_adjustment=0.0,
            p10=bands[h][0], p50=bands[h][1], p90=bands[h][2],
        )
        for h in (7, 30, 90)
    ]
    method = ForecastMethod(
        engine_version="fixture-1",
        baseline=BaselineMethod(
            intercept=0.0, trend_per_year=0.0, seasonal_sin=0.0,
            seasonal_cos=0.0, anchor_date=AS_OF, n_obs=300,
        ),
        drivers={},
        residuals=ResidualMethod(
            sigma=0.01, rho=0.0, q10=-0.01, q90=0.01, window_obs=300
        ),
        sparsity=SparsityMethod(
            observed_days=300, calendar_days=365, multiplier=1.0
        ),
        attribution_order=list(ATTRIBUTION_ORDER),
    )
    forecast = Forecast(
        forecast_id="FCST-pending", commodity=commodity, market=market,
        as_of=AS_OF, engine_version="fixture-1", method=method,
        days=days, lines=lines or [], horizons_summary=summaries,
        missing_drivers=missing or [], accuracy=attachment,
    )
    return forecast.model_copy(
        update={"forecast_id": forecast_content_id(forecast)}
    )


def _sentiment_line(state, **summary):
    return ContributionLine(
        driver="sentiment", coefficient=0.01 if state == "estimated" else None,
        input_path=[0.0] * 90, contribution_path_inr=[0.0] * 90,
        at_horizon={"7": 0.0, "30": 0.0, "90": 0.0},
        input_summary={"state": state, **summary},
    )


@pytest.fixture()
def fx(tmp_path):
    store = build_store(str(tmp_path / "r10.db"))

    # wheat: the clean series — every driver fresh, sentiment
    # estimated, measured accuracy, bands sized to its history.
    wheat_market = _fill_series(store, "wheat", 2450.0)
    wheat_records = [
        _record(f"ACC-R10-WHEAT-{h}", "wheat", wheat_market, h)
        for h in (7, 30, 90)
    ]
    for record in wheat_records:
        store.save_accuracy_record(record)
    store.insert_index(
        SentimentIndex(
            index_id="IDX-R10-WHEAT", commodity="wheat",
            week_start=date(2025, 12, 22), week_end=date(2025, 12, 28),
            value=0.12, n_items=5, extraction_ids=[],
            aspect_values={}, pack_version="2026.10.1",
            window_days=28, half_life_days=7.0,
        )
    )
    wheat = _forecast(
        "wheat", wheat_market,
        {7: (2450.0, 2500.0, 2550.0), 30: (2296.0, 2500.0, 2504.0),
         90: (2320.0, 2500.0, 2680.0)},
        _attachment(wheat_records),
        lines=[_sentiment_line("estimated", latest_week_start="2025-12-22")],
    )
    store.insert_forecast(wheat)

    # groundnut: dense prices, but arrivals went stale in
    # November and sentiment is not estimable.
    groundnut_market = _fill_series(
        store, "groundnut", 5900.0, arrivals_until=date(2025, 11, 1)
    )
    groundnut_records = [
        _record(f"ACC-R10-GROUNDNUT-{h}", "groundnut", groundnut_market, h)
        for h in (7, 30, 90)
    ]
    for record in groundnut_records:
        store.save_accuracy_record(record)
    groundnut = _forecast(
        "groundnut", groundnut_market,
        {7: (5580.0, 6000.0, 6420.0), 30: (5580.0, 6000.0, 6420.0),
         90: (5580.0, 6000.0, 6420.0)},
        _attachment(groundnut_records),
        lines=[
            _sentiment_line(
                "not_estimable",
                reason="only 3 index-covered price days",
            )
        ],
        missing=["sentiment_not_estimable"],
    )
    store.insert_forecast(groundnut)

    # coffee: Tue/Fri reporting with three planted missing days,
    # three catalogue-missing drivers, no accuracy coverage.
    coffee_market = _fill_series(store, "coffee", 33500.0)
    coffee = _forecast(
        "coffee", coffee_market,
        {7: (31000.0, 34000.0, 37000.0), 30: (31000.0, 34000.0, 37000.0),
         90: (31000.0, 34000.0, 37000.0)},
        _attachment(None),
        missing=["stock_level", "import_flow", "export_flow"],
    )
    store.insert_forecast(coffee)

    return {
        "store": store,
        "thin": ThinDataService(store),
        "intake": IntakeService(store),
        "wheat": wheat,
        "groundnut": groundnut,
        "coffee": coffee,
        "db": str(tmp_path / "r10.db"),
    }


# --- thin-data: windows and driver states -----------------------------------


def test_windows_state_operating_day_coverage(fx):
    assessment = fx["thin"].assess_forecast(fx["groundnut"].forecast_id)
    by_days = {w.window_days: w for w in assessment.windows}
    for days in (7, 30, 90, 365):
        assert by_days[days].coverage == 1.0
        assert by_days[days].missing_operating_dates == []
    arrivals = next(d for d in assessment.drivers if d.driver == "arrivals")
    assert arrivals.status == "stale"
    assert arrivals.last_observed_date == date(2025, 11, 1)
    assert any(g.startswith("arrivals: stale") for g in assessment.named_gaps)
    assert any(g.startswith("sentiment: missing") for g in assessment.named_gaps)
    assert fx["thin"].verify_stored(assessment.assessment_id) == []


def test_coffee_windows_and_missing_drivers(fx):
    # The fixture filled every Tue/Fri operating day, so coffee's
    # windows are full on its own reporting pattern — its gaps
    # are the drivers the catalogue does not report at all.
    assessment = fx["thin"].assess_forecast(fx["coffee"].forecast_id)
    by_days = {w.window_days: w for w in assessment.windows}
    year = by_days[365]
    assert year.coverage == 1.0  # the fixture filled every Tue/Fri
    for driver in ("stock_level", "import_flow", "export_flow"):
        state = next(d for d in assessment.drivers if d.driver == driver)
        assert state.status == "missing"
        assert state.last_observed_date is None
        assert any(g.startswith(f"{driver}: missing") for g in assessment.named_gaps)


# --- thin-data: tiers ---------------------------------------------------------


def test_tiers_earned_and_capped(fx):
    wheat = fx["thin"].assess_forecast(fx["wheat"].forecast_id)
    assert [h.tier for h in wheat.horizons] == ["established"] * 3
    assert wheat.summary_tier == "established"
    assert wheat.named_gaps == []

    groundnut = fx["thin"].assess_forecast(fx["groundnut"].forecast_id)
    h30 = next(h for h in groundnut.horizons if h.horizon_days == 30)
    assert h30.tier == "thin"  # the stale-arrivals cap binds
    assert any("stale" in r and "caps" in r for r in h30.reasons)
    assert h30.accuracy_record_id == "ACC-R10-GROUNDNUT-30"
    assert h30.interval_to_realised_ratio is not None

    coffee = fx["thin"].assess_forecast(fx["coffee"].forecast_id)
    assert [h.tier for h in coffee.horizons] == ["unproven"] * 3
    assert coffee.summary_tier == "unproven"
    assert fx["thin"].verify_all() == []


def test_tier_claim_contradiction_is_graded(fx):
    thin = fx["thin"]
    problems = thin.verify_claim(fx["coffee"].forecast_id, 30, "established")
    assert problems and "overstatement" in problems[0]
    assert thin.verify_claim(fx["coffee"].forecast_id, 30, "unproven") == []
    assert thin.verify_claim(fx["wheat"].forecast_id, 30, "established") == []
    assert thin.verify_claim(fx["wheat"].forecast_id, 30, "thin") == []


def test_assessment_is_insert_only_and_tamper_is_caught(fx, tmp_path):
    thin = fx["thin"]
    first = thin.assess_forecast(fx["wheat"].forecast_id)
    again = thin.assess_forecast(fx["wheat"].forecast_id)
    assert again.assessment_id == first.assessment_id
    assert len(thin.list_assessments("wheat")) == 1
    # tamper: raise groundnut's stored 30-day tier (thin) to
    # established, in the payload only.
    conn = sqlite3.connect(fx["db"])
    groundnut = thin.assess_forecast(fx["groundnut"].forecast_id)
    payload = json.loads(
        conn.execute(
            "SELECT payload FROM thin_assessments WHERE assessment_id = ?",
            (groundnut.assessment_id,),
        ).fetchone()[0]
    )
    for horizon in payload["horizons"]:
        if horizon["horizon_days"] == 30:
            horizon["tier"] = "established"
    conn.execute(
        "UPDATE thin_assessments SET payload = ? WHERE assessment_id = ?",
        (json.dumps(payload), groundnut.assessment_id),
    )
    conn.commit()
    conn.close()
    problems = thin.verify_stored(groundnut.assessment_id)
    assert any("tier overstatement" in p for p in problems), problems
    assert any("content id mismatch" in p for p in problems), problems


# --- assisted intake ----------------------------------------------------------


def _enter(intake: IntakeService, **overrides):
    spec = dict(
        commodity="coffee", market="bengaluru",
        obs_date=date(2025, 12, 29), driver="modal_price",
        value=34100.0, entered_by="d.assist",
        entered_by_role="desk_assistant", entered_at=T0,
        source_note="phoned in by the Bengaluru market contact",
    )
    spec.update(overrides)
    return intake.enter(**spec)


def test_pending_entry_is_invisible_to_engine_reads(fx):
    intake = fx["intake"]
    entry = _enter(intake)
    rows = fx["store"].series(
        "coffee", "bengaluru", "modal_price",
        date(2025, 12, 29), date(2025, 12, 29),
    )
    assert rows == []  # 2025-12-29 is a Monday: no generated row,
    # and the pending entry must not leak one into existence.
    view = intake.entry_view(entry.entry_id)
    assert view["state"] == "pending"
    assert view["fact"] is None
    assert view["problems"] == []


def test_self_check_is_refused_both_ways(fx):
    intake = fx["intake"]
    entry = _enter(intake)
    with pytest.raises(IntakeValidationError):
        intake.confirm(
            entry.entry_id, checker="d.assist",
            checker_role="desk_head", acted_at=T0 + timedelta(hours=1),
        )
    with pytest.raises(IntakeValidationError):
        intake.reject(
            entry.entry_id, checker="D.Assist",
            checker_role="desk_head", acted_at=T0 + timedelta(hours=1),
        )
    assert intake.entry_state(entry.entry_id) == "pending"


def test_confirm_lands_exactly_one_fact_with_both_names(fx):
    intake = fx["intake"]
    entry = _enter(intake)
    act = intake.confirm(
        entry.entry_id, checker="r.menon", checker_role="desk_head",
        acted_at=T0 + timedelta(hours=2),
    )
    rows = fx["store"].series(
        "coffee", "bengaluru", "modal_price",
        date(2025, 12, 29), date(2025, 12, 29),
    )
    assert len(rows) == 1 and rows[0].value == 34100.0
    view = intake.entry_view(entry.entry_id)
    assert view["state"] == "confirmed"
    assert view["provenance"]["entered_by"] == "d.assist"
    assert view["provenance"]["confirmed_by"] == "r.menon"
    assert view["provenance"]["entry_id"] == entry.entry_id
    assert view["problems"] == []
    assert act.checker == "r.menon"
    with pytest.raises(IntakeStateError):
        intake.confirm(
            entry.entry_id, checker="a.sharma",
            checker_role="analyst", acted_at=T0 + timedelta(hours=3),
        )


def test_reject_lands_nothing_and_is_terminal(fx):
    intake = fx["intake"]
    # 2025-12-22 is a Monday — no generated coffee row stands
    # there, so a landed fact would be visible immediately.
    entry2 = _enter(
        intake, obs_date=date(2025, 12, 22), value=33800.0,
        entered_at=datetime(2025, 12, 22, 18, 0, 0),
    )
    intake.reject(
        entry2.entry_id, checker="r.menon", checker_role="desk_head",
        acted_at=datetime(2025, 12, 22, 19, 0, 0),
    )
    assert fx["store"].series(
        "coffee", "bengaluru", "modal_price",
        date(2025, 12, 22), date(2025, 12, 22),
    ) == []
    assert intake.entry_view(entry2.entry_id)["problems"] == []
    with pytest.raises(IntakeStateError):
        intake.confirm(
            entry2.entry_id, checker="a.sharma",
            checker_role="analyst",
            acted_at=datetime(2025, 12, 22, 20, 0, 0),
        )


def test_entry_refusals(fx):
    intake = fx["intake"]
    # a key the store already holds (a generated Friday row).
    with pytest.raises(IntakeValidationError):
        _enter(intake, obs_date=date(2025, 12, 26),
               entered_at=datetime(2025, 12, 26, 18, 0, 0))
    _enter(intake)
    # a second entry claiming the same key.
    with pytest.raises(IntakeValidationError):
        _enter(intake, value=34200.0)
    # identical re-entry is the same artefact, not an error.
    same = _enter(intake)
    assert same.entry_id == intake.list_entries()[0].entry_id
    with pytest.raises(IntakeValidationError):
        _enter(intake, obs_date=date(2025, 12, 30),
               entered_at=datetime(2025, 12, 29, 18, 0, 0))  # future vs entry
    with pytest.raises(IntakeValidationError):
        _enter(intake, driver="stock_level", obs_date=date(2025, 12, 29))
    with pytest.raises(IntakeValidationError):
        _enter(intake, entered_by="tbd")
    with pytest.raises(IntakeValidationError):
        _enter(intake, value=0.0)
    with pytest.raises(IntakeValidationError):
        _enter(intake, source_note="  ")


def test_intake_chain_tampering_is_caught(fx):
    intake, store = fx["intake"], fx["store"]
    entry = _enter(intake)
    intake.confirm(
        entry.entry_id, checker="r.menon", checker_role="desk_head",
        acted_at=T0 + timedelta(hours=1),
    )
    assert intake.verify_stored(entry.entry_id) == []
    # a second act smuggled past the service breaks the chain.
    from fmcg_forecast.intake.models import IntakeCheckAct, check_act_content_id

    rogue = IntakeCheckAct(
        act_id="INA-pending", entry_id=entry.entry_id, act="reject",
        checker="a.sharma", checker_role="analyst",
        acted_at=T0 + timedelta(hours=2), note="smuggled",
    )
    rogue = rogue.model_copy(
        update={"act_id": check_act_content_id(rogue)}
    )
    store.insert_intake_check_act(rogue)
    problems = intake.verify_stored(entry.entry_id)
    assert any("chain violation" in p for p in problems), problems

    # a pending entry with a leaked observation at its key.
    entry2 = _enter(
        intake, obs_date=date(2025, 12, 22), value=33800.0,
        entered_at=datetime(2025, 12, 22, 18, 0, 0),
    )
    store.insert_observations(
        [
            Observation(
                commodity="coffee", market="bengaluru",
                obs_date=date(2025, 12, 22), driver="modal_price",
                value=33800.0,
            )
        ]
    )
    problems = intake.verify_stored(entry2.entry_id)
    assert any("unconfirmed leakage" in p for p in problems), problems


# --- surfaces -------------------------------------------------------------------


def test_api_surfaces(fx):
    client = TestClient(create_app(fx["store"]))
    pack = client.get("/thin-data/pack")
    assert pack.status_code == 200
    assert pack.json()["version"] == load_thin_data_pack().version

    assessed = client.post(
        "/thin-data/assessments",
        json={"forecast_id": fx["coffee"].forecast_id},
    )
    assert assessed.status_code == 201
    body = assessed.json()
    assert body["summary_tier"] == "unproven"
    assert any("stock_level" in g for g in body["named_gaps"])
    assert body["problems"] == []

    claim = client.post(
        "/thin-data/claims/verify",
        json={
            "forecast_id": fx["coffee"].forecast_id,
            "horizon_days": 30, "claimed_tier": "established",
        },
    )
    assert claim.status_code == 200
    assert claim.json()["problems"]

    view = client.get(f"/forecasts/{fx['groundnut'].forecast_id}")
    assert view.status_code == 200
    thin_data = view.json()["thin_data"]
    assert thin_data is not None
    assert any("arrivals" in g for g in thin_data["named_gaps"])

    entered = client.post(
        "/intake/entries",
        json={
            "commodity": "coffee", "market": "bengaluru",
            "obs_date": "2025-12-29", "driver": "modal_price",
            "value": 34100.0, "entered_by": "d.assist",
            "entered_by_role": "desk_assistant",
            "entered_at": "2025-12-29T18:00:00",
            "source_note": "phoned in by the Bengaluru market contact",
        },
    )
    assert entered.status_code == 201
    entry_id = entered.json()["entry_id"]
    assert entered.json()["state"] == "pending"
    self_check = client.post(
        f"/intake/entries/{entry_id}/confirm",
        json={
            "checker": "d.assist", "checker_role": "desk_head",
            "at": "2025-12-29T19:00:00",
        },
    )
    assert self_check.status_code == 422
    confirmed = client.post(
        f"/intake/entries/{entry_id}/confirm",
        json={
            "checker": "r.menon", "checker_role": "desk_head",
            "at": "2025-12-29T19:30:00",
        },
    )
    assert confirmed.status_code == 200
    verified = client.get(f"/intake/entries/{entry_id}/verify")
    assert verified.json()["problems"] == []


def test_cli_surfaces(fx):
    db = fx["db"]
    rc = thin_cli.main(["--db", db, "assess", fx["wheat"].forecast_id])
    assert rc == 0
    rc = thin_cli.main(
        ["--db", db, "claim", fx["coffee"].forecast_id,
         "--horizon", "30", "--tier", "established"]
    )
    assert rc == 1  # the contradiction is refused, loudly
    rc = intake_cli.main(
        [
            "--db", db, "enter", "--commodity", "coffee",
            "--market", "bengaluru", "--date", "2025-12-29",
            "--driver", "modal_price", "--value", "34100",
            "--entered-by", "d.assist",
            "--entered-by-role", "desk_assistant",
            "--at", "2025-12-29T18:00:00",
            "--source-note", "phoned in by the Bengaluru market contact",
        ]
    )
    assert rc == 0
    entries = fx["intake"].list_entries()
    assert len(entries) == 1
    rc = intake_cli.main(
        [
            "--db", db, "confirm", entries[0].entry_id,
            "--checker", "r.menon", "--checker-role", "desk_head",
            "--at", "2025-12-29T19:00:00",
        ]
    )
    assert rc == 0
    assert fx["intake"].verify_all() == []
