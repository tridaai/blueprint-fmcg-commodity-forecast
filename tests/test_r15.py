"""Round 15 tests: desk policy pack, approvals, config
(F20-AD2, F20-CA2, F20-CA1).

The genesis pack fail-closed; a proposal carrying its
exact field-by-field diff and refused when it changes
nothing; a version that stands only when its pack-change
chain completes — and the decisions opened before it
keeping the old pack on their face. The chain discipline
graded act by act: no skipping, no re-roling, no
self-approval, no actor striking twice, a rejection
closing the case. Chain resolution judged from the
target's own face: the degraded chili forecast grows a
desk-head step the measured wheat forecast does not; a
coverage assessment above the pack's exposure threshold
grows one a small assessment does not. The decision log
folding gaplessly with its as-of respected. Comments
that render on their pinned artefact or nowhere; a task
flagged when its scenario is superseded, never moved.
Tampered artefacts named by the verifier. Postgres
parity runs when FMCG_TEST_DATABASE_URL names a cluster.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.api import create_app
from fmcg_forecast.backtest.harness import run_all
from fmcg_forecast.desk import cli as desk_cli
from fmcg_forecast.desk.pack import DeskPolicyPack, load_desk_pack
from fmcg_forecast.desk.service import (
    DeskService,
    DeskValidationError,
)
from fmcg_forecast.desk.verify import (
    verify_decision,
    verify_decision_log,
    verify_desk,
    verify_policy_version,
)
from fmcg_forecast.events.service import EventService
from fmcg_forecast.forecast.service import ForecastService
from fmcg_forecast.modelport import OfflineModel
from fmcg_forecast.planning.models import (
    CoverageAssessment,
    assessment_content_id,
)
from fmcg_forecast.scenarios.service import ScenarioService
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
    db = str(tmp_path_factory.mktemp("r15") / "test.db")
    store = build_store(db)
    truth = build_truth_store(db)
    load_dataset(store, truth, SEED)
    run_all(store)
    grading = build_sentiment_grading_store(db)
    load_sentiment_corpus(store, grading, SEED)
    sentiment = SentimentService(store, OfflineModel())
    sentiment.run_pipeline()
    events = EventService(store)
    events.seed_historical(store.get_manifest())
    forecasts = ForecastService(
        store,
        OfflineModel(),
        sentiment_provider=sentiment.forecast_input,
        sentiment_claim_verifier=sentiment.verify_claims,
        events_provider=events.forecast_adjustments,
    )
    scenarios = ScenarioService(
        store,
        OfflineModel(),
        forecasts,
        events,
        sentiment_provider=sentiment.forecast_input,
    )
    return {
        "store": store,
        "db": db,
        "forecasts": forecasts,
        "scenarios": scenarios,
        "desk": DeskService(store),
    }


def _pack_with(**changes) -> DeskPolicyPack:
    return load_desk_pack().model_copy(update=changes)


def _propose_and_activate(desk: DeskService, label="2026.11.1", **changes):
    """Drive one pack version all the way to standing."""
    if not changes:
        changes = {"exposure_threshold_inr": 1_000_000.0}
    pack = _pack_with(version=label, **changes)
    version = desk.propose_policy_version(
        label, pack, "a.sharma", date(2026, 1, 2)
    )
    decision = desk.open_decision(
        "pack_change", version.version_id, "a.sharma",
        date(2026, 1, 2), "tighten the desk's rules",
    )
    desk.strike_act(
        decision.decision_id, "m.iyer", "analyst", "approve",
        date(2026, 1, 3),
    )
    desk.strike_act(
        decision.decision_id, "d.kaur", "desk_head", "approve",
        date(2026, 1, 4),
    )
    return version


def _assessment(store, exposure_inr: float, marker: str) -> CoverageAssessment:
    assessment = CoverageAssessment(
        assessment_id="",
        plan_id=f"PLAN-{marker}",
        commodity="wheat",
        market="indore",
        basis_kind="official_forecast",
        forecast_id=f"FCST-{marker}",
        scenario_id=None,
        scenario_status_at_assessment=None,
        as_of=HISTORY_END,
        spot_inr=2400.0,
        spot_date=HISTORY_END,
        signal_id=f"SIG-{marker}",
        signal_value="phased",
        pack_version="2026.10.1",
        signal_pack_version="2026.10.1",
        coverage_days=30.0,
        stockout_month=None,
        months=[],
        total_required_tonnes=100.0,
        total_uncovered_tonnes=50.0,
        total_exposure_inr=exposure_inr,
        unvalued_months=[],
        options=[],
        figures=[],
        notes=[],
        scope_note="fabricated for the desk layer's resolution tests",
    )
    assessment = assessment.model_copy(
        update={"assessment_id": assessment_content_id(assessment)}
    )
    store.insert_coverage_assessment(assessment)
    return assessment


# --- the pack (F20-AD2) ------------------------------------------------------


def test_genesis_pack_is_versioned_and_fail_closed():
    pack = load_desk_pack()
    assert pack.version == "2026.10.1"
    assert {c.kind for c in pack.chains} == {
        "pack_change", "scenario_adoption",
        "forecast_approval", "coverage_commitment",
    }
    with pytest.raises(ValueError):
        load_desk_pack("1999.1.1")
    payload = pack.model_dump(mode="json")
    payload["surprise_field"] = True
    with pytest.raises(Exception):
        DeskPolicyPack.model_validate(payload)
    thinned = pack.model_dump(mode="json")
    thinned["chains"] = thinned["chains"][:3]
    with pytest.raises(Exception):
        DeskPolicyPack.model_validate(thinned)


def test_proposal_carries_its_exact_diff(tmp_path):
    desk = DeskService(build_store(str(tmp_path / "t.db")))
    pack = _pack_with(
        version="2026.11.1", exposure_threshold_inr=1_000_000.0
    )
    version = desk.propose_policy_version(
        "2026.11.1", pack, "a.sharma", date(2026, 1, 2)
    )
    assert version.status == "proposed"
    assert version.supersedes_label == "2026.10.1"
    assert version.supersedes_version_id is None
    assert [d.field for d in version.diff] == ["exposure_threshold_inr"]
    assert version.diff[0].before == 5_000_000.0
    assert version.diff[0].after == 1_000_000.0
    # Proposing changes nothing about what governs.
    assert desk.standing()["label"] == "2026.10.1"
    assert verify_policy_version(desk.store, version) == []


def test_proposal_refusals(tmp_path):
    desk = DeskService(build_store(str(tmp_path / "t.db")))
    identical = _pack_with(version="2026.11.1")
    with pytest.raises(DeskValidationError, match="changes nothing"):
        desk.propose_policy_version(
            "2026.11.1", identical, "a.sharma", date(2026, 1, 2)
        )
    changed = _pack_with(
        version="2026.11.1", exposure_threshold_inr=1.0
    )
    with pytest.raises(DeskValidationError, match="does not match"):
        desk.propose_policy_version(
            "2026.12.9", changed, "a.sharma", date(2026, 1, 2)
        )
    with pytest.raises(DeskValidationError, match="genesis"):
        desk.propose_policy_version(
            "2026.10.1",
            _pack_with(exposure_threshold_inr=1.0),
            "a.sharma",
            date(2026, 1, 2),
        )
    desk.propose_policy_version(
        "2026.11.1", changed, "a.sharma", date(2026, 1, 2)
    )
    with pytest.raises(DeskValidationError, match="already on record"):
        desk.propose_policy_version(
            "2026.11.1", changed, "m.iyer", date(2026, 1, 3)
        )
    payload = changed.model_dump(mode="json")
    payload["version"] = "2026.12.1"
    payload["bogus"] = 1
    with pytest.raises(DeskValidationError, match="does not validate"):
        desk.propose_policy_version(
            "2026.12.1", payload, "a.sharma", date(2026, 1, 2)
        )


def test_activation_only_through_the_chain(tmp_path):
    desk = DeskService(build_store(str(tmp_path / "t.db")))
    version = _propose_and_activate(
        desk, exposure_threshold_inr=1_000_000.0
    )
    assert desk.get_policy_version(version.version_id).status == "standing"
    assert desk.standing()["label"] == "2026.11.1"
    # The next proposal diffs against the new standing pack.
    follow = desk.propose_policy_version(
        "2026.12.1",
        _pack_with(
            version="2026.12.1", exposure_threshold_inr=500_000.0
        ).model_copy(update={
            "chains": desk.standing_pack().chains,
        }),
        "m.iyer",
        date(2026, 2, 1),
    )
    # The follow-up was built from the genesis chains but a
    # threshold below the standing one: its diff is judged
    # against 2026.11.1, whose threshold it must first match.
    assert follow.supersedes_label == "2026.11.1"
    assert follow.supersedes_version_id == version.version_id
    assert verify_desk(desk.store) == []


def test_decisions_keep_the_pack_they_opened_under(tmp_path):
    store = build_store(str(tmp_path / "t.db"))
    desk = DeskService(store)
    small = _assessment(store, 2_000_000.0, "keeppack")
    before = desk.open_decision(
        "coverage_commitment", small.assessment_id, "r.menon",
        date(2026, 1, 2), "commit under the old bar",
    )
    assert before.pack_version == "2026.10.1"
    # 2,000,000 is below the genesis bar: one step.
    assert [s.step for s in before.steps] == ["commit_review"]
    _propose_and_activate(desk, exposure_threshold_inr=1_000_000.0)
    # The same exposure now clears the standing bar.
    after = desk.open_decision(
        "coverage_commitment", small.assessment_id, "r.menon",
        date(2026, 2, 2), "commit under the new bar",
    )
    assert after.pack_version == "2026.11.1"
    assert [s.step for s in after.steps] == [
        "commit_review", "desk_head_sign_off",
    ]
    assert desk.decision_view(before.decision_id)["state"] == "open"
    assert verify_desk(store) == []


def test_pack_change_over_a_standing_version_is_refused(tmp_path):
    desk = DeskService(build_store(str(tmp_path / "t.db")))
    version = _propose_and_activate(desk)
    with pytest.raises(DeskValidationError, match="already stands"):
        desk.open_decision(
            "pack_change", version.version_id, "m.iyer",
            date(2026, 2, 1), "govern the standing version",
        )
    with pytest.raises(DeskValidationError, match="on record"):
        desk.open_decision(
            "pack_change", "POL-ghost", "m.iyer",
            date(2026, 2, 1), "govern nothing",
        )


# --- the chains (F20-CA2) ------------------------------------------------------


def test_chain_cannot_be_skipped_or_reroled(tmp_path):
    desk = DeskService(build_store(str(tmp_path / "t.db")))
    version = desk.propose_policy_version(
        "2026.11.1",
        _pack_with(
            version="2026.11.1", exposure_threshold_inr=1_000_000.0
        ),
        "a.sharma",
        date(2026, 1, 2),
    )
    decision = desk.open_decision(
        "pack_change", version.version_id, "a.sharma",
        date(2026, 1, 2), "tighten the bar",
    )
    with pytest.raises(DeskValidationError, match="cannot be skipped"):
        desk.strike_act(
            decision.decision_id, "d.kaur", "desk_head",
            "approve", date(2026, 1, 3),
        )
    with pytest.raises(DeskValidationError, match="cannot be skipped"):
        desk.strike_act(
            decision.decision_id, "m.iyer", "viewer",
            "approve", date(2026, 1, 3),
        )
    assert desk.decision_view(decision.decision_id)["state"] == "open"


def test_two_person_rule_and_no_self_approval(tmp_path):
    desk = DeskService(build_store(str(tmp_path / "t.db")))
    version = desk.propose_policy_version(
        "2026.11.1",
        _pack_with(
            version="2026.11.1", exposure_threshold_inr=1_000_000.0
        ),
        "a.sharma",
        date(2026, 1, 2),
    )
    decision = desk.open_decision(
        "pack_change", version.version_id, "a.sharma",
        date(2026, 1, 2), "tighten the bar",
    )
    with pytest.raises(DeskValidationError, match="self-approval"):
        desk.strike_act(
            decision.decision_id, "A. Sharma", "analyst",
            "approve", date(2026, 1, 3),
        )
    desk.strike_act(
        decision.decision_id, "m.iyer", "analyst", "approve",
        date(2026, 1, 3),
    )
    with pytest.raises(DeskValidationError, match="two-person"):
        desk.strike_act(
            decision.decision_id, "M.  Iyer", "desk_head",
            "approve", date(2026, 1, 4),
        )
    with pytest.raises(DeskValidationError, match="predate"):
        desk.strike_act(
            decision.decision_id, "d.kaur", "desk_head",
            "approve", date(2026, 1, 1),
        )
    desk.strike_act(
        decision.decision_id, "d.kaur", "desk_head", "approve",
        date(2026, 1, 4),
    )
    assert desk.decision_view(decision.decision_id)["state"] == "approved"
    with pytest.raises(DeskValidationError, match="already approved"):
        desk.strike_act(
            decision.decision_id, "r.menon", "analyst",
            "approve", date(2026, 1, 5),
        )


def test_rejection_closes_the_decision(tmp_path):
    desk = DeskService(build_store(str(tmp_path / "t.db")))
    version = desk.propose_policy_version(
        "2026.11.1",
        _pack_with(
            version="2026.11.1", exposure_threshold_inr=1_000_000.0
        ),
        "a.sharma",
        date(2026, 1, 2),
    )
    decision = desk.open_decision(
        "pack_change", version.version_id, "a.sharma",
        date(2026, 1, 2), "tighten the bar",
    )
    desk.strike_act(
        decision.decision_id, "m.iyer", "analyst", "reject",
        date(2026, 1, 3), note="the diff is not justified",
    )
    view = desk.decision_view(decision.decision_id)
    assert view["state"] == "rejected"
    assert view["next_step"] is None
    # A rejected proposal never stands.
    assert desk.standing()["label"] == "2026.10.1"
    assert desk.get_policy_version(version.version_id).status == "proposed"
    with pytest.raises(DeskValidationError, match="already rejected"):
        desk.strike_act(
            decision.decision_id, "d.kaur", "desk_head",
            "approve", date(2026, 1, 4),
        )
    assert verify_desk(desk.store) == []


def test_forecast_chain_resolution_follows_measured_accuracy(graded):
    store, desk = graded["store"], graded["desk"]
    forecasts = graded["forecasts"]
    chili = forecasts.run_forecast("chili", "guntur")
    assert chili.accuracy is not None
    assert chili.accuracy.state == "degraded"
    degraded = desk.open_decision(
        "forecast_approval", chili.forecast_id, "r.menon",
        date(2026, 1, 2), "approve the chili draft",
    )
    assert [s.step for s in degraded.steps] == [
        "review", "desk_head_sign_off",
    ]
    assert degraded.resolution[0].name == "accuracy_state"
    assert degraded.resolution[0].value == "degraded"
    wheat = forecasts.run_forecast("wheat", "indore")
    assert wheat.accuracy is not None
    assert wheat.accuracy.state == "measured"
    measured = desk.open_decision(
        "forecast_approval", wheat.forecast_id, "r.menon",
        date(2026, 1, 2), "approve the wheat draft",
    )
    assert [s.step for s in measured.steps] == ["review"]
    assert verify_desk(store) == []


def test_coverage_chain_resolution_follows_exposure(tmp_path):
    store = build_store(str(tmp_path / "t.db"))
    desk = DeskService(store)
    big = _assessment(store, 16_000_000.0, "big")
    decision = desk.open_decision(
        "coverage_commitment", big.assessment_id, "r.menon",
        date(2026, 1, 2), "commit the quarter",
    )
    assert [s.step for s in decision.steps] == [
        "commit_review", "desk_head_sign_off",
    ]
    facts = {f.name: f.value for f in decision.resolution}
    assert facts["exposure_inr"] == "16000000.00"
    assert facts["exposure_threshold_inr"] == "5000000.00"
    small = _assessment(store, 400_000.0, "small")
    decision = desk.open_decision(
        "coverage_commitment", small.assessment_id, "r.menon",
        date(2026, 1, 2), "commit a small top-up",
    )
    assert [s.step for s in decision.steps] == ["commit_review"]
    assert verify_desk(store) == []


def test_scenario_adoption_chain(graded):
    desk, scenarios = graded["desk"], graded["scenarios"]
    forecasts = graded["forecasts"]
    base = forecasts.run_forecast("soybean", "indore")
    request = scenarios.parse_request(
        "soybean", "indore", "what if arrivals drop 10%?",
        base_forecast_id=base.forecast_id,
    )
    run = scenarios.run_scenario(
        request.request_id, base.forecast_id, "a.sharma",
        date(2026, 1, 3),
    )
    decision = desk.open_decision(
        "scenario_adoption", run.scenario_id, "r.menon",
        date(2026, 1, 4), "adopt the arrivals fork",
    )
    assert [s.step for s in decision.steps] == [
        "adoption_review", "adoption_confirm",
    ]
    desk.strike_act(
        decision.decision_id, "m.iyer", "analyst", "approve",
        date(2026, 1, 5),
    )
    desk.strike_act(
        decision.decision_id, "d.kaur", "desk_head", "approve",
        date(2026, 1, 6),
    )
    assert desk.decision_view(decision.decision_id)["state"] == "approved"
    assert verify_desk(graded["store"]) == []


# --- the decision log (F20-CA2) -------------------------------------------------


def test_decision_log_folds_gaplessly_with_its_as_of(tmp_path):
    desk = DeskService(build_store(str(tmp_path / "t.db")))
    version = desk.propose_policy_version(
        "2026.11.1",
        _pack_with(
            version="2026.11.1", exposure_threshold_inr=1_000_000.0
        ),
        "a.sharma",
        date(2026, 1, 2),
    )
    decision = desk.open_decision(
        "pack_change", version.version_id, "a.sharma",
        date(2026, 1, 2), "tighten the bar",
    )
    desk.strike_act(
        decision.decision_id, "m.iyer", "analyst", "approve",
        date(2026, 1, 3),
    )
    early = desk.strike_decision_log(date(2026, 1, 3))
    assert [e.seq for e in early.entries] == [1]
    assert early.entries[0].step == "review"
    desk.strike_act(
        decision.decision_id, "d.kaur", "desk_head", "approve",
        date(2026, 1, 10),
    )
    # The early log is a snapshot: it does not grow.
    assert len(desk.get_decision_log(early.log_id).entries) == 1
    full = desk.strike_decision_log(date(2026, 1, 31))
    assert [e.seq for e in full.entries] == [1, 2]
    assert [e.step for e in full.entries] == ["review", "sign_off"]
    assert full.entries[1].kind == "pack_change"
    assert full.entries[1].target_id == version.version_id
    assert verify_decision_log(desk.store, full) == []
    assert verify_desk(desk.store) == []


# --- annotations (F20-CA1) -------------------------------------------------------


def test_comments_pin_to_their_artefact(graded):
    desk, forecasts = graded["desk"], graded["forecasts"]
    wheat = forecasts.run_forecast("wheat", "indore")
    coffee = forecasts.run_forecast("coffee", "bengaluru")
    comment = desk.add_comment(
        "forecast", wheat.forecast_id, "m.iyer",
        "check the arrivals figure with the market contact",
        date(2026, 1, 3),
    )
    assert desk.list_comments("forecast", wheat.forecast_id) == [comment]
    assert desk.list_comments("forecast", coffee.forecast_id) == []
    with pytest.raises(DeskValidationError, match="on record"):
        desk.add_comment(
            "forecast", "FCST-ghost", "m.iyer", "on nothing",
            date(2026, 1, 3),
        )
    with pytest.raises(DeskValidationError, match="cannot be annotated"):
        desk.add_comment(
            "policy_version", wheat.forecast_id, "m.iyer",
            "wrong kind", date(2026, 1, 3),
        )
    with pytest.raises(DeskValidationError, match="must be named"):
        desk.add_comment(
            "forecast", wheat.forecast_id, "  ", "unnamed",
            date(2026, 1, 3),
        )
    assert verify_desk(graded["store"]) == []


def test_task_lifecycle_folds_from_its_acts(graded):
    desk, forecasts = graded["desk"], graded["forecasts"]
    wheat = forecasts.run_forecast("wheat", "kanpur")
    task = desk.open_task(
        "forecast", wheat.forecast_id,
        "confirm the kanpur arrivals with the mandi contact",
        "d.kaur", "m.iyer", date(2026, 1, 3),
    )
    view = desk.task_view(task.task_id)
    assert view["state"] == "open"
    assert view["target_superseded"] is False
    with pytest.raises(DeskValidationError, match="already open"):
        desk.strike_task_act(
            task.task_id, "reopen", "m.iyer", date(2026, 1, 4)
        )
    desk.strike_task_act(
        task.task_id, "close", "m.iyer", date(2026, 1, 5),
        note="contact confirmed the figure",
    )
    assert desk.task_view(task.task_id)["state"] == "closed"
    with pytest.raises(DeskValidationError, match="already closed"):
        desk.strike_task_act(
            task.task_id, "close", "m.iyer", date(2026, 1, 6)
        )
    desk.strike_task_act(
        task.task_id, "reopen", "d.kaur", date(2026, 1, 7),
        note="the figure moved again",
    )
    assert desk.task_view(task.task_id)["state"] == "open"
    assert verify_desk(graded["store"]) == []


def test_task_on_a_superseded_scenario_is_flagged_never_moved(graded):
    desk, scenarios = graded["desk"], graded["scenarios"]
    forecasts = graded["forecasts"]
    base = forecasts.run_forecast("soybean", "indore")
    first_req = scenarios.parse_request(
        "soybean", "indore", "what if arrivals drop 10%?",
        base_forecast_id=base.forecast_id,
    )
    first = scenarios.run_scenario(
        first_req.request_id, base.forecast_id, "a.sharma",
        date(2026, 1, 3),
    )
    scenarios.adopt(first.scenario_id, "d.kaur", "desk_head",
                    date(2026, 1, 4))
    task = desk.open_task(
        "scenario", first.scenario_id,
        "re-check the fork if arrivals recover",
        "d.kaur", "m.iyer", date(2026, 1, 5),
    )
    assert desk.task_view(task.task_id)["target_superseded"] is False
    second_req = scenarios.parse_request(
        "soybean", "indore", "what if arrivals drop 25%?",
        base_forecast_id=base.forecast_id,
    )
    second = scenarios.run_scenario(
        second_req.request_id, base.forecast_id, "a.sharma",
        date(2026, 1, 6),
    )
    scenarios.adopt(second.scenario_id, "d.kaur", "desk_head",
                    date(2026, 1, 7))
    assert graded["store"].get_scenario(
        first.scenario_id
    ).status == "superseded"
    view = desk.task_view(task.task_id)
    assert view["target_superseded"] is True
    # Flagged, not moved: the pin still names the first run.
    assert view["target_id"] == first.scenario_id
    assert verify_desk(graded["store"]) == []


# --- tamper evidence ----------------------------------------------------------------


def _tamper(db: str, table: str, key_col: str, key: str, mutate) -> None:
    conn = sqlite3.connect(db)
    row = conn.execute(
        f"SELECT payload FROM {table} WHERE {key_col} = ?", (key,)
    ).fetchone()
    payload = json.loads(row[0])
    mutate(payload)
    conn.execute(
        f"UPDATE {table} SET payload = ? WHERE {key_col} = ?",
        (json.dumps(payload), key),
    )
    conn.commit()
    conn.close()


def test_tampered_desk_artefacts_are_detected(tmp_path):
    db = str(tmp_path / "t.db")
    store = build_store(db)
    desk = DeskService(store)
    version = _propose_and_activate(desk)
    decision = next(
        d for d in desk.list_decisions(kind="pack_change")
    )
    log = desk.strike_decision_log(date(2026, 1, 31))
    assert verify_desk(store) == []

    # A rewritten diff is named against the recomputed one.
    _tamper(
        db, "policy_versions", "version_id", version.version_id,
        lambda p: p["diff"][0].update({"after": 42.0}),
    )
    problems = verify_policy_version(store, desk.get_policy_version(
        version.version_id
    ))
    assert any("diff disagrees" in p for p in problems)
    _tamper(
        db, "policy_versions", "version_id", version.version_id,
        lambda p: p["diff"][0].update({"after": 1_000_000.0}),
    )
    assert verify_desk(store) == []

    # An act re-stepped after the fact breaks the chain fold.
    act = store.list_decision_acts(decision.decision_id)[0]
    _tamper(
        db, "decision_acts", "act_id", act.act_id,
        lambda p: p.update({"step": "sign_off"}),
    )
    problems = verify_decision(store, desk.get_decision(
        decision.decision_id
    ))
    assert any("skipped" in p or "strikes step" in p for p in problems)
    _tamper(
        db, "decision_acts", "act_id", act.act_id,
        lambda p: p.update({"step": "review"}),
    )
    assert verify_desk(store) == []

    # A dropped log entry is named against the re-fold.
    _tamper(
        db, "decision_logs", "log_id", log.log_id,
        lambda p: p.update({"entries": p["entries"][:1]}),
    )
    problems = verify_decision_log(store, desk.get_decision_log(log.log_id))
    assert any("entries disagree" in p for p in problems)


def test_standing_without_a_chain_is_named(tmp_path):
    db = str(tmp_path / "t.db")
    store = build_store(db)
    desk = DeskService(store)
    version = desk.propose_policy_version(
        "2026.11.1",
        _pack_with(
            version="2026.11.1", exposure_threshold_inr=1_000_000.0
        ),
        "a.sharma",
        date(2026, 1, 2),
    )
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE policy_versions SET status = 'standing' "
        "WHERE version_id = ?",
        (version.version_id,),
    )
    conn.commit()
    conn.close()
    problems = verify_policy_version(
        store, desk.get_policy_version(version.version_id)
    )
    assert any("no completed pack-change chain" in p for p in problems)


# --- surfaces -------------------------------------------------------------------------


def test_api_desk_surface(graded):
    client = TestClient(create_app(graded["store"]))
    r = client.get("/desk/pack")
    assert r.status_code == 200
    assert r.json()["label"] == "2026.10.1"
    pack = load_desk_pack().model_dump(mode="json")
    pack["version"] = "2026.11.1"
    pack["exposure_threshold_inr"] = 250_000.0
    r = client.post(
        "/desk/policy-versions",
        json={
            "label": "2026.11.1", "pack": pack,
            "proposed_by": "a.sharma", "proposed_on": "2026-01-02",
        },
    )
    assert r.status_code == 201
    version_id = r.json()["version_id"]
    assert r.json()["problems"] == []
    r = client.post(
        "/desk/decisions",
        json={
            "kind": "pack_change", "target_id": version_id,
            "opened_by": "a.sharma", "opened_on": "2026-01-02",
            "purpose": "tighten the bar",
        },
    )
    assert r.status_code == 201
    decision_id = r.json()["decision_id"]
    # A skip over HTTP is a 422, not a state change.
    r = client.post(
        f"/desk/decisions/{decision_id}/acts",
        json={
            "actor": "d.kaur", "role": "desk_head",
            "outcome": "approve", "decided_on": "2026-01-03",
        },
    )
    assert r.status_code == 422
    r = client.post(
        f"/desk/decisions/{decision_id}/acts",
        json={
            "actor": "m.iyer", "role": "analyst",
            "outcome": "approve", "decided_on": "2026-01-03",
        },
    )
    assert r.status_code == 201
    r = client.post(
        f"/desk/decisions/{decision_id}/acts",
        json={
            "actor": "d.kaur", "role": "desk_head",
            "outcome": "approve", "decided_on": "2026-01-04",
        },
    )
    assert r.status_code == 201
    assert client.get("/desk/pack").json()["label"] == "2026.11.1"
    r = client.post(
        "/desk/decision-logs", json={"struck_on": "2026-01-31"}
    )
    assert r.status_code == 201
    entries = r.json()["entries"]
    # Gapless from 1 across the whole graded record, and
    # this decision's two acts are in it, in chain order.
    assert [e["seq"] for e in entries] == list(
        range(1, len(entries) + 1)
    )
    own = [e for e in entries if e["decision_id"] == decision_id]
    assert [e["step"] for e in own] == ["review", "sign_off"]
    r = client.get("/desk/decisions/DEC-ghost")
    assert r.status_code == 404
    wheat = graded["forecasts"].run_forecast("wheat", "indore")
    r = client.post(
        "/desk/comments",
        json={
            "target_kind": "forecast",
            "target_id": wheat.forecast_id,
            "author": "m.iyer", "text": "check the arrivals figure",
            "commented_on": "2026-01-03",
        },
    )
    assert r.status_code == 201
    assert r.json()["body"] == "check the arrivals figure"
    r = client.get(
        "/desk/comments",
        params={
            "target_kind": "forecast",
            "target_id": wheat.forecast_id,
        },
    )
    assert r.status_code == 200
    assert len(r.json()["comments"]) == 1
    r = client.post(
        "/desk/comments",
        json={
            "target_kind": "forecast", "target_id": "FCST-ghost",
            "author": "m.iyer", "text": "on nothing",
            "commented_on": "2026-01-03",
        },
    )
    assert r.status_code == 422
    assert client.get("/desk/verify").json()["problems"] == []


def test_cli_desk_surface(graded, tmp_path, capsys):
    db = graded["db"]
    pack_file = tmp_path / "pack.json"
    pack = load_desk_pack().model_dump(mode="json")
    pack["version"] = "2027.1.1"
    pack["exposure_threshold_inr"] = 750_000.0
    pack_file.write_text(json.dumps(pack), encoding="utf-8")
    assert desk_cli.main([
        "--db", db, "propose", "--label", "2027.1.1",
        "--pack-file", str(pack_file), "--by", "a.sharma",
        "--on", "2026-02-02",
    ]) == 0
    out = json.loads(capsys.readouterr().out)
    version_id = out["version_id"]
    assert desk_cli.main([
        "--db", db, "open-decision", "pack_change", version_id,
        "--by", "a.sharma", "--on", "2026-02-02",
        "--purpose", "tighten again",
    ]) == 0
    out = json.loads(capsys.readouterr().out)
    decision_id = out["decision_id"]
    assert desk_cli.main([
        "--db", db, "act", decision_id, "--by", "m.iyer",
        "--role", "analyst", "--outcome", "approve",
        "--on", "2026-02-03",
    ]) == 0
    capsys.readouterr()
    assert desk_cli.main([
        "--db", db, "act", decision_id, "--by", "d.kaur",
        "--role", "desk_head", "--outcome", "approve",
        "--on", "2026-02-04",
    ]) == 0
    capsys.readouterr()
    assert desk_cli.main(["--db", db, "pack"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["label"] == "2027.1.1"
    assert desk_cli.main(["--db", db, "verify"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["problems"] == []


# --- Postgres parity ---------------------------------------------------------------------


PG_DSN = os.environ.get("FMCG_TEST_DATABASE_URL")


def _desk_walk(store) -> dict:
    desk = DeskService(store)
    version = _propose_and_activate(
        desk, exposure_threshold_inr=1_000_000.0
    )
    small = _assessment(store, 2_000_000.0, "parity")
    decision = desk.open_decision(
        "coverage_commitment", small.assessment_id, "r.menon",
        date(2026, 2, 2), "commit under the new bar",
    )
    desk.strike_act(
        decision.decision_id, "m.iyer", "analyst", "approve",
        date(2026, 2, 3),
    )
    desk.strike_act(
        decision.decision_id, "d.kaur", "desk_head", "approve",
        date(2026, 2, 4),
    )
    log = desk.strike_decision_log(date(2026, 2, 28))
    comment = desk.add_comment(
        "coverage_assessment", small.assessment_id, "m.iyer",
        "exposure checked against the plan", date(2026, 2, 5),
    )
    task = desk.open_task(
        "coverage_assessment", small.assessment_id,
        "re-run when the plan is revised",
        "d.kaur", "m.iyer", date(2026, 2, 5),
    )
    desk.strike_task_act(
        task.task_id, "close", "m.iyer", date(2026, 2, 6)
    )
    return {
        "version": desk.get_policy_version(
            version.version_id
        ).model_dump(mode="json"),
        "decision": desk.get_decision(
            decision.decision_id
        ).model_dump(mode="json"),
        "acts": [
            a.model_dump(mode="json")
            for a in store.list_decision_acts(decision.decision_id)
        ],
        "log": log.model_dump(mode="json"),
        "comment": comment.model_dump(mode="json"),
        "task": desk.get_task(task.task_id).model_dump(mode="json"),
        "task_view_state": desk.task_view(task.task_id)["state"],
        "problems": verify_desk(store),
    }


@pytest.mark.skipif(not PG_DSN, reason="FMCG_TEST_DATABASE_URL not set")
def test_postgres_parity(tmp_path):
    lite = build_store(str(tmp_path / "lite.db"))
    pg = build_store(database_url=PG_DSN)
    lite_walk = _desk_walk(lite)
    pg_walk = _desk_walk(pg)
    assert lite_walk == pg_walk
    assert pg_walk["problems"] == []
