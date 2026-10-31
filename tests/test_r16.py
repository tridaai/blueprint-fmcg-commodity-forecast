"""Round 16 tests: role scopes and the access audit
(F20-AS1), master data and market calendars (F20-AD1).

The pack fail-closed; the bootstrap grant and granter
discipline; the standing fold over a name's chain; the
judgement matrix — unknown principal, role barred from
the surface, market out of scope — answered over HTTP
exactly as a missing artefact is answered. Every
identified read recorded, the audit log folding
gaplessly, forged artefacts named by the verifier.
Master data: a version struck only by a desk head,
its diff re-derived, an empty strike refused; a
holiday re-deriving coverage for exactly the windows
that contain it, and a display-name edit moving no
verdict. Postgres parity runs when
FMCG_TEST_DATABASE_URL names a cluster.
"""

from __future__ import annotations

import json
import os
from datetime import date

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.access import cli as access_cli
from fmcg_forecast.access.engine import fold_grants, folded_name, judge_read
from fmcg_forecast.access.models import (
    AccessEntry,
    PrincipalGrant,
    entry_content_id,
    grant_content_id,
)
from fmcg_forecast.access.pack import load_access_pack
from fmcg_forecast.access.service import (
    AccessService,
    AccessValidationError,
)
from fmcg_forecast.access.verify import verify_access
from fmcg_forecast.api import create_app
from fmcg_forecast.backtest.harness import run_all
from fmcg_forecast.dashboards.service import DashboardService
from fmcg_forecast.forecast.service import ForecastService
from fmcg_forecast.masterdata import cli as masterdata_cli
from fmcg_forecast.masterdata.engine import genesis_state
from fmcg_forecast.masterdata.models import (
    MasterDataVersion,
    master_data_version_content_id,
)
from fmcg_forecast.masterdata.pack import load_masterdata_pack
from fmcg_forecast.masterdata.service import (
    MasterDataService,
    MasterDataValidationError,
)
from fmcg_forecast.masterdata.verify import verify_masterdata
from fmcg_forecast.events.service import EventService
from fmcg_forecast.modelport import OfflineModel
from fmcg_forecast.sentiment.service import SentimentService
from fmcg_forecast.store import build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset

SEED = 20261027
HISTORY_END = date(2025, 12, 31)
JAN2 = date(2026, 1, 2)


def _book(store) -> AccessService:
    """A small book: desk head, a scoped trader, a
    scoped viewer, an all-markets trader."""
    access = AccessService(store)
    access.strike_grant("d.kaur", "desk_head", None, "d.kaur", JAN2)
    access.strike_grant("a.sharma", "trader", ["indore"], "d.kaur", JAN2)
    access.strike_grant(
        "m.iyer", "viewer", ["indore", "kanpur"], "d.kaur", JAN2
    )
    access.strike_grant("r.menon", "trader", None, "d.kaur", JAN2)
    return access


@pytest.fixture()
def book(tmp_path):
    return build_store(str(tmp_path / "book.db"))


@pytest.fixture(scope="module")
def graded(tmp_path_factory):
    """A loaded store: the grant book struck, two wheat
    forecasts run."""
    db = str(tmp_path_factory.mktemp("r16g") / "graded.db")
    store = build_store(db)
    truth = build_truth_store(db)
    load_dataset(store, truth, SEED)
    run_all(store)
    _book(store)
    forecasts = ForecastService(store, OfflineModel())
    indore = forecasts.run_forecast("wheat", "indore")
    kanpur = forecasts.run_forecast("wheat", "kanpur")
    return {"store": store, "indore": indore, "kanpur": kanpur}


# --- the packs ---------------------------------------------------------


def test_packs_fail_closed():
    with pytest.raises(ValueError):
        load_access_pack("1999.01.1")
    with pytest.raises(ValueError):
        load_masterdata_pack("1999.01.1")
    assert load_access_pack().version == "2026.10.1"
    assert load_masterdata_pack().quintals_per_tonne == 10


# --- grants: discipline and the fold -------------------------------------


def test_bootstrap_and_granter_discipline(tmp_path):
    store = build_store(str(tmp_path / "discipline.db"))
    access = AccessService(store)
    # The first act must be its own subject's bootstrap.
    with pytest.raises(AccessValidationError):
        access.strike_grant("a.sharma", "trader", ["indore"], "d.kaur", JAN2)
    with pytest.raises(AccessValidationError):
        access.strike_grant("d.kaur", "trader", None, "d.kaur", JAN2)
    with pytest.raises(AccessValidationError):
        access.strike_grant("d.kaur", "desk_head", ["indore"], "d.kaur", JAN2)
    access.strike_grant("d.kaur", "desk_head", None, "d.kaur", JAN2)
    # A trader may not strike grants; a desk head may not
    # grant themselves; unknown markets are refused.
    access.strike_grant("a.sharma", "trader", ["indore"], "d.kaur", JAN2)
    with pytest.raises(AccessValidationError):
        access.strike_grant("m.iyer", "viewer", ["indore"], "a.sharma", JAN2)
    with pytest.raises(AccessValidationError):
        access.strike_grant("d.kaur", "viewer", None, "d.kaur", JAN2)
    with pytest.raises(AccessValidationError):
        access.strike_grant("m.iyer", "viewer", ["atlantis"], "d.kaur", JAN2)
    with pytest.raises(AccessValidationError):
        access.strike_grant("m.iyer", "superuser", None, "d.kaur", JAN2)
    with pytest.raises(AccessValidationError):
        # a repeal carries no scope
        access.strike_grant("a.sharma", None, ["indore"], "d.kaur", JAN2)


def test_standing_folds_over_the_chain(book):
    access = _book(book)
    assert access.standing_grant("A. Sharma").role == "trader"
    assert access.standing_grant("a.sharma").markets == ["indore"]
    narrowed = access.strike_grant(
        "a.sharma", "trader", ["kanpur"], "d.kaur", date(2026, 2, 1)
    )
    assert access.standing_grant("a.sharma").grant_id == narrowed.grant_id
    assert access.standing_grant("a.sharma").markets == ["kanpur"]
    access.strike_grant("a.sharma", None, None, "d.kaur", date(2026, 3, 1))
    repeal = access.standing_grant("a.sharma")
    assert repeal is not None and repeal.role is None
    # Names fold: punctuation and case are not identity.
    assert folded_name("A. Sharma") == folded_name("a  SHARMA")


def test_judgement_matrix(book):
    access = _book(book)
    pack = load_access_pack()
    trader = access.standing_grant("a.sharma")
    viewer = access.standing_grant("m.iyer")
    assert judge_read(pack, None, "forecast", ["indore"]) == (
        "hidden_unknown_principal"
    )
    assert judge_read(pack, viewer, "export", ["indore"]) == (
        "hidden_role_surface"
    )
    assert judge_read(pack, trader, "forecast", ["kanpur"]) == (
        "hidden_out_of_scope"
    )
    # A dashboard spanning two markets hides when any
    # one is out of scope.
    assert judge_read(pack, trader, "dashboard", ["indore", "kanpur"]) == (
        "hidden_out_of_scope"
    )
    assert judge_read(pack, viewer, "dashboard", ["indore", "kanpur"]) == (
        "allowed"
    )
    assert judge_read(pack, trader, "forecast", []) == "allowed"


# --- the audit ----------------------------------------------------------


def test_reads_are_recorded_and_the_log_folds(book):
    access = _book(book)
    first = access.record_read(
        "a.sharma", "forecast", "forecast", "FCST-1", ["indore"], HISTORY_END
    )
    second = access.record_read(
        "nobody", "forecast", "forecast", "FCST-1", ["indore"], HISTORY_END
    )
    assert first.outcome == "allowed"
    assert second.outcome == "hidden_unknown_principal"
    assert second.seq == first.seq + 1
    log = access.strike_access_log(date(2026, 3, 31))
    assert [line.seq for line in log.entries] == list(
        range(1, len(log.entries) + 1)
    )
    assert log.upto_seq == log.entries[-1].seq
    assert verify_access(book) == []


def test_verifier_names_forged_artefacts(tmp_path):
    store = build_store(str(tmp_path / "forged.db"))
    access = _book(store)
    entry = access.record_read(
        "a.sharma", "forecast", "forecast", "FCST-1", ["kanpur"], HISTORY_END
    )
    assert entry.outcome == "hidden_out_of_scope"
    # Flip the outcome in a direct insert, honestly addressed.
    forged = entry.model_copy(update={"outcome": "allowed"})
    forged = forged.model_copy(
        update={"entry_id": entry_content_id(forged)}
    )
    store.insert_access_entry(
        AccessEntry.model_validate(forged.model_dump(mode="json"))
    )
    problems = verify_access(store)
    assert any("re-judged" in p for p in problems)
    # A grant struck around the service by a name with no
    # granting role is named for its granter.
    store2 = build_store(str(tmp_path / "forged2.db"))
    access2 = _book(store2)
    standing = access2.standing_grant("m.iyer")
    grant = PrincipalGrant(
        grant_id="pending",
        seq=len(store2.list_principal_grants()) + 1,
        subject="x.intruder",
        role="desk_head",
        markets=None,
        granted_by="a.sharma",
        granted_on=date(2026, 4, 1),
        supersedes_grant_id=None,
        bootstrap=False,
        pack_version="2026.10.1",
    )
    grant = grant.model_copy(update={"grant_id": grant_content_id(grant)})
    store2.insert_principal_grant(grant)
    problems = verify_access(store2)
    assert any("no granting role" in p for p in problems)
    assert standing is not None


# --- governed reads over HTTP -------------------------------------------


def test_governed_forecast_reads_hide_and_record(graded):
    store = graded["store"]
    client = TestClient(create_app(store))
    indore_id = graded["indore"].forecast_id
    kanpur_id = graded["kanpur"].forecast_id
    # No principal: the local posture, unjudged.
    assert client.get(f"/forecasts/{indore_id}").status_code == 200
    entries_before = len(store.list_access_entries())
    # In scope: allowed, and recorded.
    ok = client.get(
        f"/forecasts/{indore_id}", headers={"x-desk-actor": "a.sharma"}
    )
    assert ok.status_code == 200
    # Out of scope: the identical answer a missing
    # forecast gets — same status, same body shape.
    hidden = client.get(
        f"/forecasts/{kanpur_id}", headers={"x-desk-actor": "a.sharma"}
    )
    missing = client.get(
        "/forecasts/FCST-nope", headers={"x-desk-actor": "a.sharma"}
    )
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == {"detail": f"unknown forecast {kanpur_id}"}
    assert missing.json() == {"detail": "unknown forecast FCST-nope"}
    # Unknown principal: hidden too.
    unknown = client.get(
        f"/forecasts/{indore_id}", headers={"x-desk-actor": "ghost"}
    )
    assert unknown.status_code == 404
    entries = store.list_access_entries()[entries_before:]
    assert [e.outcome for e in entries] == [
        "allowed",
        "hidden_out_of_scope",
        "hidden_unknown_principal",
    ]
    assert verify_access(store) == []


def test_governed_export_surface(graded):
    store = graded["store"]
    dashboards = DashboardService(
        store,
        OfflineModel(),
        EventService(store),
        SentimentService(store, OfflineModel()),
    )
    spec = dashboards.ask(
        "wheat forecast at indore",
        asked_by="a.sharma",
        created_on=date(2026, 1, 5),
    )
    assembly = dashboards.assemble(spec.spec_id, assembled_on=date(2026, 1, 5))
    client = TestClient(create_app(store))
    # A viewer may read the assembly but not export it.
    read = client.get(
        f"/dashboards/assemblies/{assembly.assembly_id}",
        headers={"x-desk-actor": "m.iyer"},
    )
    assert read.status_code == 200
    export = client.get(
        f"/dashboards/assemblies/{assembly.assembly_id}/html",
        headers={"x-desk-actor": "m.iyer"},
    )
    assert export.status_code == 404
    trader_export = client.get(
        f"/dashboards/assemblies/{assembly.assembly_id}/html",
        headers={"x-desk-actor": "a.sharma"},
    )
    assert trader_export.status_code == 200
    outcomes = [e.outcome for e in store.list_access_entries()]
    assert outcomes[-3:] == ["allowed", "hidden_role_surface", "allowed"]


# --- master data -----------------------------------------------------------


def _state_with(mutate) -> object:
    state = genesis_state().model_copy(deep=True)
    mutate(state)
    return state


def test_masterdata_strike_discipline(book):
    md = MasterDataService(book)
    state = _state_with(
        lambda s: setattr(
            s.calendar("kanpur"), "holidays", [date(2025, 12, 25)]
        )
    )
    # An ungranted editor and a trader are refused.
    with pytest.raises(MasterDataValidationError):
        md.strike_version("v1", state, "ghost", JAN2)
    _book(book)
    with pytest.raises(MasterDataValidationError):
        md.strike_version("v1", state, "a.sharma", JAN2)
    version = md.strike_version("christmas-closure", state, "d.kaur", JAN2)
    assert [d.field for d in version.diff] == ["calendars.kanpur.holidays"]
    assert md.standing()["label"] == "christmas-closure"
    # An empty strike and a reused label are refused.
    with pytest.raises(MasterDataValidationError):
        md.strike_version("v2", md.standing_state(), "d.kaur", JAN2)
    changed = _state_with(
        lambda s: s.commodity_displays.update({"chili": "Dry Red Chili"})
    )
    with pytest.raises(MasterDataValidationError):
        md.strike_version("christmas-closure", changed, "d.kaur", JAN2)
    assert verify_masterdata(book) == []


def test_verifier_names_a_tampered_masterdata_diff(book, tmp_path):
    _book(book)
    md = MasterDataService(book)
    state = _state_with(
        lambda s: setattr(
            s.calendar("kanpur"), "holidays", [date(2025, 12, 25)]
        )
    )
    version = md.strike_version("closure", state, "d.kaur", JAN2)
    tampered = version.model_copy(update={"diff": []})
    tampered = tampered.model_copy(
        update={"version_id": master_data_version_content_id(tampered)}
    )
    store = build_store(str(tmp_path / "tampered.db"))
    store.insert_master_data_version(
        MasterDataVersion.model_validate(tampered.model_dump(mode="json"))
    )
    problems = verify_masterdata(store)
    assert any("does not re-derive" in p for p in problems)


def test_calendar_change_rederives_coverage_exactly(graded):
    store = graded["store"]
    md = MasterDataService(store)
    baseline = md.coverage("wheat", "kanpur", HISTORY_END)
    christmas = date(2025, 12, 25)  # a Thursday: kanpur sits
    state = _state_with(
        lambda s: setattr(s.calendar("kanpur"), "holidays", [christmas])
    )
    version = md.strike_version("christmas-closure", state, "d.kaur", JAN2)
    report = md.coverage(
        "wheat", "kanpur", HISTORY_END, version_id=version.version_id
    )
    assert report["after_label"] == "christmas-closure"
    for window, base in zip(report["windows"], baseline["windows"]):
        assert [c["date"] for c in window["changed_operating_dates"]] == [
            christmas
        ]
        assert window["after"]["operating_days"] == (
            window["before"]["operating_days"] - 1
        )
        assert window["verdict_changed"] is True
        assert base["after"] == window["before"]  # genesis is the base
    # A coffee holiday on a day coffee never sits moves
    # nothing: 2025-12-25 is a Thursday, coffee sits
    # Tuesday/Friday.
    coffee = md.coverage("coffee", "bengaluru", HISTORY_END)
    for window in coffee["windows"]:
        assert window["changed_operating_dates"] == []
        assert window["verdict_changed"] is False


def test_display_edit_moves_no_coverage(graded):
    store = graded["store"]
    md = MasterDataService(store)
    state = _state_with(
        lambda s: s.commodity_displays.update({"chili": "Dry Red Chili"})
    )
    version = md.strike_version("chili-display", state, "d.kaur", JAN2)
    report = md.coverage(
        "wheat", "kanpur", HISTORY_END, version_id=version.version_id
    )
    assert all(not w["verdict_changed"] for w in report["windows"])
    assert all(w["changed_operating_dates"] == [] for w in report["windows"])


# --- API + CLI surfaces ------------------------------------------------------


def test_access_api_round_trip(tmp_path):
    store = build_store(str(tmp_path / "api.db"))
    client = TestClient(create_app(store))
    struck = client.post(
        "/access/grants",
        json={
            "subject": "d.kaur",
            "role": "desk_head",
            "granted_by": "d.kaur",
            "granted_on": "2026-01-02",
        },
    )
    assert struck.status_code == 201
    assert struck.json()["bootstrap"] is True
    refused = client.post(
        "/access/grants",
        json={
            "subject": "a.sharma",
            "role": "trader",
            "markets": ["atlantis"],
            "granted_by": "d.kaur",
            "granted_on": "2026-01-02",
        },
    )
    assert refused.status_code == 422
    standing = client.get("/access/standing/D.%20Kaur")
    assert standing.status_code == 200
    assert client.get("/access/verify").json() == {"problems": []}


def test_clis(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    build_store(db).close()
    assert (
        access_cli.main(
            [
                "--db", db, "grant", "d.kaur", "--role", "desk_head",
                "--by", "d.kaur", "--on", "2026-01-02",
            ]
        )
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["bootstrap"] is True
    assert access_cli.main(["--db", db, "verify"]) == 0
    assert json.loads(capsys.readouterr().out) == {"problems": []}
    assert masterdata_cli.main(["--db", db, "standing"]) == 0
    standing = json.loads(capsys.readouterr().out)
    assert standing["label"] == "genesis"
    assert len(standing["state"]["calendars"]) == 12


# --- Postgres parity ---------------------------------------------------------


PG_DSN = os.environ.get("FMCG_TEST_DATABASE_URL")


def _access_walk(store) -> dict:
    access = _book(store)
    e1 = access.record_read(
        "a.sharma", "forecast", "forecast", "FCST-1", ["indore"], HISTORY_END
    )
    e2 = access.record_read(
        "a.sharma", "forecast", "forecast", "FCST-2", ["kanpur"], HISTORY_END
    )
    log = access.strike_access_log(date(2026, 3, 31))
    md = MasterDataService(store)
    state = _state_with(
        lambda s: setattr(
            s.calendar("kanpur"), "holidays", [date(2025, 12, 25)]
        )
    )
    version = md.strike_version("christmas-closure", state, "d.kaur", JAN2)
    return {
        "grants": [
            g.model_dump(mode="json") for g in store.list_principal_grants()
        ],
        "e1": e1.model_dump(mode="json"),
        "e2": e2.model_dump(mode="json"),
        "log": log.model_dump(mode="json"),
        "version": md.version_view(version),
        "access_problems": verify_access(store),
        "masterdata_problems": verify_masterdata(store),
    }


@pytest.mark.skipif(not PG_DSN, reason="FMCG_TEST_DATABASE_URL not set")
def test_postgres_parity(tmp_path):
    lite = build_store(str(tmp_path / "lite.db"))
    pg = build_store(database_url=os.environ["FMCG_TEST_DATABASE_URL"])
    lite_walk = _access_walk(lite)
    pg_walk = _access_walk(pg)
    assert lite_walk == pg_walk
    assert pg_walk["access_problems"] == []
    assert pg_walk["masterdata_problems"] == []
