"""Round 7 tests: dashboard pack, the deterministic prompt
grammar (fixtures exact, gaps named, hypothetical discipline),
specs and saved views, verified assembly (lineage completeness,
tamper detection), the computed re-run diff, the morning desk
board (exceptions backed by artefacts), API + CLI surfaces,
truth isolation."""

from __future__ import annotations

import ast
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.api import create_app
from fmcg_forecast.backtest.harness import run_all as run_backtest_harness
from fmcg_forecast.backtest.pack import load_accuracy_pack
from fmcg_forecast.dashboards import cli as dashboard_cli
from fmcg_forecast.dashboards.assemble import compute_assembly_diff
from fmcg_forecast.dashboards.models import (
    DashboardFigure,
    LineageFact,
    ResolvedPanel,
)
from fmcg_forecast.dashboards.pack import DASHBOARD_PACK_V1, load_dashboard_pack
from fmcg_forecast.dashboards.service import (
    DashboardNotFoundError,
    DashboardParseError,
    DashboardService,
    DashboardValidationError,
)
from fmcg_forecast.events.service import EventService
from fmcg_forecast.forecast.service import ForecastService
from fmcg_forecast.modelport import ModelNotConfiguredError, OfflineModel, _HostedRefusal
from fmcg_forecast.scenarios.service import ScenarioService
from fmcg_forecast.sentiment.grading import build_sentiment_grading_store
from fmcg_forecast.sentiment.load import load_sentiment_corpus
from fmcg_forecast.sentiment.service import SentimentService
from fmcg_forecast.store import build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset

SEED = 20261027
PACK = DASHBOARD_PACK_V1
HISTORY_END = date(2025, 12, 31)
BOARD_DATE = date(2026, 2, 15)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db = str(tmp_path_factory.mktemp("r7") / "test.db")
    store = build_store(db)
    truth = build_truth_store(db)
    load_dataset(store, truth, SEED)
    manifest = store.get_manifest()
    grading = build_sentiment_grading_store(db)
    load_sentiment_corpus(store, grading, SEED)
    model = OfflineModel()
    sentiment = SentimentService(store, model)
    sentiment.run_pipeline()
    events = EventService(store)
    events.seed_historical(manifest)
    tariff = events.register_event(
        event_class="tariff_change",
        commodity="soybean",
        window_start=date(2026, 2, 1),
        window_end=date(2026, 2, 28),
        channel="import_flow",
        peak_log_price_effect=0.08,
        basis="announced_measure",
        basis_detail="Import duty on oilseeds raised by 10 "
        "percentage points in a ministry notification",
        decay_days=20,
        description="Import tariff increase on oilseeds for February",
        declared_by="a.sharma",
        declared_on=date(2026, 1, 2),
    )
    forecasts = ForecastService(
        store,
        model,
        sentiment_provider=sentiment.forecast_input,
        sentiment_claim_verifier=sentiment.verify_claims,
        events_provider=events.forecast_adjustments,
    )
    # the harness runs before the desk forecasts, so their pinned
    # accuracy attachments carry the measured states (chili degraded)
    run_backtest_harness(store, load_accuracy_pack())
    soy = forecasts.run_forecast("soybean", "indore")
    wheat = forecasts.run_forecast("wheat", "delhi_khari_baoli")
    wheat_early = forecasts.run_forecast(
        "wheat", "delhi_khari_baoli", as_of=date(2025, 11, 30)
    )
    coffee = forecasts.run_forecast("coffee", "bengaluru")
    chili = forecasts.run_forecast("chili", "guntur")
    scenarios = ScenarioService(
        store,
        model,
        forecasts,
        events,
        sentiment_provider=sentiment.forecast_input,
    )
    request = scenarios.parse_request(
        "soybean", "indore", "what if arrivals drop 10%?",
        base_forecast_id=soy.forecast_id,
    )
    scenario_run = scenarios.run_scenario(
        request.request_id, soy.forecast_id, author="a.sharma",
        created_on=date(2026, 1, 3),
    )
    dashboards = DashboardService(store, model, events, sentiment)
    return {
        "db": db,
        "store": store,
        "model": model,
        "events": events,
        "forecasts": forecasts,
        "scenarios": scenarios,
        "dashboards": dashboards,
        "tariff": tariff,
        "soy": soy,
        "wheat": wheat,
        "wheat_early": wheat_early,
        "coffee": coffee,
        "chili": chili,
        "scenario_run": scenario_run,
    }


def _ask(env, prompt, by="a.sharma"):
    return env["dashboards"].ask(prompt, by, date(2026, 1, 5))


# --- the pack ---------------------------------------------------------------


def test_dashboard_pack_loads():
    pack = load_dashboard_pack()
    assert pack.version == "2026.10.1"
    assert set(pack.panels) == {
        "forecast", "accuracy", "sentiment", "events", "scenario_diff",
    }
    assert pack.board_sections == [
        "degraded", "pending_gate", "active_event",
        "forecast_change", "data_gap",
    ]
    assert "reference market" in pack.default_market_rule
    assert "not a rainfall reading" in pack.unstateable_subjects["rainfall"]


# --- the grammar --------------------------------------------------------------


def test_grammar_fixture_exact(env):
    spec = _ask(
        env,
        "wheat prices at delhi for the next quarter; soybean sentiment; "
        "maize stock position; wheat accuracy; declared events for coffee; "
        f"scenario {env['scenario_run'].scenario_id.lower()}; groundnut arrivals",
    )
    kinds = [(p.kind, p.scope.get("commodity"), p.scope.get("market")) for p in spec.panels]
    assert kinds == [
        ("forecast", "wheat", "delhi_khari_baoli"),
        ("sentiment", "soybean", None),
        ("gap", None, None),
        ("accuracy", "wheat", "delhi_khari_baoli"),
        ("events", "coffee", None),
        ("scenario_diff", None, None),
        ("gap", None, None),
    ]
    gaps = [p for p in spec.panels if p.kind == "gap"]
    assert "stock cover is a contribution line" in gaps[0].gap_needed
    assert "contribution line inside the forecast artefact" in gaps[1].gap_needed
    scenario_panel = spec.panels[5]
    assert scenario_panel.scope["scenario_id"] == env["scenario_run"].scenario_id


def test_grammar_gap_fixtures(env):
    cases = {
        "tea prices": "a commodity the desk covers",
        "show me the scenario": "renders a fork only "
        "when the prompt names it",
        "wheat rainfall": "not a rainfall reading",
        "coffee stock position": "stock cover is a contribution line",
        "the monsoon outlook": "not a stored series",
    }
    for prompt, fragment in cases.items():
        spec = _ask(env, prompt)
        assert len(spec.panels) == 1, prompt
        panel = spec.panels[0]
        assert panel.kind == "gap", prompt
        assert fragment in panel.gap_needed, (prompt, panel.gap_needed)


def test_unknown_scenario_id_gaps_at_assembly(env):
    dash = env["dashboards"]
    spec = _ask(env, "scenario SCN-000000000000")
    assert spec.panels[0].kind == "scenario_diff"  # named, so stated
    assembly = dash.assemble(spec.spec_id, date(2026, 1, 5))
    panel = assembly.panels[0]
    assert panel.state == "gap"
    assert "no such run is on record" in panel.gap_needed


def test_grammar_inheritance_and_case(env):
    spec = _ask(env, "SOYBEAN forecast and accuracy")
    assert [p.kind for p in spec.panels] == ["forecast", "accuracy"]
    assert spec.panels[1].scope == {"commodity": "soybean", "market": "indore"}


def test_grammar_empty_prompt_refused(env):
    with pytest.raises(DashboardParseError):
        env["dashboards"].ask("   ", "a.sharma", date(2026, 1, 5))


def test_ask_placeholder_asker_refused(env):
    with pytest.raises(DashboardValidationError):
        env["dashboards"].ask("wheat forecast", "unknown", date(2026, 1, 5))


def test_hosted_profile_fails_closed(env):
    hosted = DashboardService(
        env["store"], _HostedRefusal("anthropic"), env["events"],
        SentimentService(env["store"], OfflineModel()),
    )
    with pytest.raises(ModelNotConfiguredError):
        hosted.ask("wheat forecast", "a.sharma", date(2026, 1, 5))


# --- specs, views, assembly ---------------------------------------------------


def test_spec_is_content_addressed_with_bindings(env):
    dash = env["dashboards"]
    spec = _ask(env, "wheat forecast at delhi")
    again = _ask(env, "wheat forecast at delhi")
    assert spec.spec_id == again.spec_id
    assert spec.panels[0].binding_artefact_ids == [env["wheat"].forecast_id]
    other = _ask(env, "wheat forecast at delhi", by="r.menon")
    assert other.spec_id != spec.spec_id  # the asker is part of the ask


def test_save_view(env):
    dash = env["dashboards"]
    spec = _ask(env, "soybean sentiment")
    view = dash.save_view(spec.spec_id, "soy watch", "a.sharma", date(2026, 1, 5))
    assert view.name == "soy watch"
    assert dash.save_view(spec.spec_id, "soy watch", "a.sharma", date(2026, 1, 5)).view_id == view.view_id
    assert [v.view_id for v in dash.list_views("soy watch")] == [view.view_id]
    with pytest.raises(DashboardNotFoundError):
        dash.save_view("DSPEC-nope", "x", "a.sharma", date(2026, 1, 5))


def test_assemble_renders_verified_page(env):
    dash = env["dashboards"]
    spec = _ask(
        env,
        "wheat forecast at delhi and soybean sentiment and chili forecast at guntur",
    )
    assembly = dash.assemble(spec.spec_id, date(2026, 1, 5))
    assert assembly.seq == 1
    assert dash.verify_stored(assembly.assembly_id) == []
    assert all(p.state == "rendered" for p in assembly.panels)
    html = assembly.html
    assert env["wheat"].forecast_id in html
    assert "Provenance appendix" in html
    assert "https://trida.ai/" in html and "View all blueprints" in html
    # the degraded flag rides on the chili panel and cannot be suppressed
    assert "degraded" in html
    chili_panel = assembly.panels[2]
    states = {f.key: f.value for f in chili_panel.figures}
    assert states["accuracy_state"] == "degraded"


def test_assemble_noop_returns_same_artefact(env):
    dash = env["dashboards"]
    spec = _ask(env, "coffee forecast")
    first = dash.assemble(spec.spec_id, date(2026, 1, 5))
    second = dash.assemble(spec.spec_id, date(2026, 1, 6))
    assert second.assembly_id == first.assembly_id
    assert len(dash.list_assemblies(spec.spec_id)) == 1


def test_appendix_lineage_is_complete(env):
    dash = env["dashboards"]
    spec = _ask(env, "wheat forecast at delhi and soybean sentiment")
    assembly = dash.assemble(spec.spec_id, date(2026, 1, 5))
    appendix = dash.appendix(assembly.assembly_id)
    figures = [f for p in appendix["panels"] for f in p["figures"]]
    assert figures
    for figure in figures:
        lineage = figure["lineage"]
        assert lineage, figure["key"]
        assert figure["artefact_id"] in {fact["ref"] for fact in lineage}
        assert any(
            fact["kind"] in (
                "observation_series", "sentiment_item",
                "event_declaration", "manifest",
            )
            for fact in lineage
        ), figure["key"]


def test_gap_panel_for_unrun_series(env):
    dash = env["dashboards"]
    spec = _ask(env, "groundnut forecast at rajkot")
    assembly = dash.assemble(spec.spec_id, date(2026, 1, 5))
    panel = assembly.panels[0]
    assert panel.state == "gap"
    assert "none is on record" in panel.gap_needed
    assert "Groundnut" in assembly.html  # the gap renders; the ask is not dropped


def test_hypothetical_discipline(env):
    dash = env["dashboards"]
    plain = _ask(env, "soybean forecast at indore")
    assert all(p.kind != "scenario_diff" for p in plain.panels)
    run = env["scenario_run"]
    spec = _ask(env, f"scenario {run.scenario_id}")
    assembly = dash.assemble(spec.spec_id, date(2026, 1, 5))
    panel = assembly.panels[0]
    assert panel.state == "rendered"
    diff = env["scenarios"].diff(run.scenario_id)
    figures = {f.key: f.value for f in panel.figures}
    assert figures["p50_diff_30d"] == diff.at_horizons["30"]
    assert figures["view_kind"] == "scenario_draft"  # unadopted stays a draft
    assert run.scenario_id in assembly.html


# --- the re-run diff --------------------------------------------------------


def test_rerun_diff_gap_to_rendered(env):
    dash = env["dashboards"]
    spec = _ask(env, "cumin forecast at jodhpur")
    first = dash.assemble(spec.spec_id, date(2026, 1, 5))
    assert first.panels[0].state == "gap"
    env["forecasts"].run_forecast("cumin", "jodhpur")
    second = dash.assemble(spec.spec_id, date(2026, 1, 6))
    assert second.seq == 2 and second.supersedes == first.assembly_id
    flips = [d for d in second.diff if d.kind == "panel_state_changed"]
    assert len(flips) == 1
    assert flips[0].before == "gap" and flips[0].after == "rendered"


def test_rerun_diff_binding_superseded(env):
    dash = env["dashboards"]
    spec = _ask(env, "declared events for groundnut")
    first = dash.assemble(spec.spec_id, date(2026, 1, 5))
    before_ids = set(first.panels[0].artefact_ids)
    new_event = env["events"].register_event(
        event_class="export_restriction",
        commodity="groundnut",
        window_start=date(2026, 3, 1),
        window_end=date(2026, 3, 31),
        channel="export_flow",
        peak_log_price_effect=0.05,
        basis="announced_measure",
        basis_detail="Export of groundnut oil restricted by a DGFT notification",
        decay_days=15,
        description="Groundnut export restriction for March",
        declared_by="a.sharma",
        declared_on=date(2026, 1, 6),
    )
    second = dash.assemble(spec.spec_id, date(2026, 1, 7))
    entries = [d for d in second.diff if d.kind == "binding_superseded"]
    assert len(entries) == 1
    assert set(entries[0].before) == before_ids
    assert new_event.event_id in entries[0].after


def test_diff_figure_changed_unit():
    def panel(value):
        return ResolvedPanel(
            panel_no=1,
            kind="forecast",
            title="Wheat — forecast (Delhi Khari Baoli)",
            state="rendered",
            figures=[
                DashboardFigure(
                    key="p50_30d", label="P50 @ 30d", value=value,
                    unit="p50_paise", artefact_id="FCST-x",
                    lineage=[
                        LineageFact(
                            kind="forecast", ref="FCST-x",
                            detail="the series' head forecast",
                            source="forecast artefact", fact_date=None,
                        )
                    ],
                )
            ],
            artefact_ids=["FCST-x"],
        )

    class FakeAssembly:
        panels = [panel(100)]

    entries = compute_assembly_diff(FakeAssembly(), [panel(120)])
    assert len(entries) == 1
    assert entries[0].kind == "figure_changed"
    assert entries[0].before == 100 and entries[0].after == 120


# --- the verifier refuses tampering ------------------------------------------


def _tamper(env, assembly_id, mutate):
    conn = sqlite3.connect(env["db"])
    row = conn.execute(
        "SELECT payload FROM dashboard_assemblies WHERE assembly_id = ?",
        (assembly_id,),
    ).fetchone()
    payload = json.loads(row[0])
    mutate(payload)
    conn.execute(
        "UPDATE dashboard_assemblies SET payload = ? WHERE assembly_id = ?",
        (json.dumps(payload), assembly_id),
    )
    conn.commit()
    conn.close()


def test_verifier_catches_tampered_figure(env):
    dash = env["dashboards"]
    spec = _ask(env, "wheat accuracy at delhi")
    assembly = dash.assemble(spec.spec_id, date(2026, 1, 5))
    assert dash.verify_stored(assembly.assembly_id) == []

    def inflate(payload):
        for panel in payload["panels"]:
            for figure in panel["figures"]:
                if figure["key"] == "mape_30d":
                    figure["value"] = 0.01

    _tamper(env, assembly.assembly_id, inflate)
    problems = dash.verify_stored(assembly.assembly_id)
    assert any("mape_30d" in p for p in problems), problems


def test_verifier_catches_fake_lineage(env):
    dash = env["dashboards"]
    spec = _ask(env, "soybean events")
    assembly = dash.assemble(spec.spec_id, date(2026, 1, 5))

    def fake_item(payload):
        for panel in payload["panels"]:
            for figure in panel["figures"]:
                for fact in figure["lineage"]:
                    if fact["kind"] == "observation_series":
                        fact["count"] = 1

    _tamper(env, assembly.assembly_id, fake_item)
    problems = dash.verify_stored(assembly.assembly_id)
    assert any("the store holds" in p for p in problems), problems


def test_verifier_catches_html_mismatch(env):
    dash = env["dashboards"]
    spec = _ask(env, "coffee sentiment")
    assembly = dash.assemble(spec.spec_id, date(2026, 1, 5))

    def rewrite(payload):
        payload["html"] = payload["html"].replace(
            "Provenance appendix", "Appendix"
        )

    _tamper(env, assembly.assembly_id, rewrite)
    problems = dash.verify_stored(assembly.assembly_id)
    assert any("byte-for-byte" in p for p in problems), problems


# --- the morning board ---------------------------------------------------------


def test_board_exceptions(env):
    dash = env["dashboards"]
    board = dash.board(BOARD_DATE)
    by_kind: dict[str, list] = {}
    for row in board.rows:
        by_kind.setdefault(row.kind, []).append(row)
    # chili/guntur degraded must appear, linked to its head forecast
    degraded = by_kind["degraded"]
    assert any(
        r.commodity == "chili" and r.market == "guntur" for r in degraded
    )
    chili_row = next(r for r in degraded if r.commodity == "chili")
    assert chili_row.artefact_id == env["chili"].forecast_id
    # coffee's named gaps appear
    gaps = by_kind["data_gap"]
    coffee_gap = next(r for r in gaps if r.commodity == "coffee")
    assert "stock_level" in coffee_gap.headline
    # the February tariff is active, verdict on its face
    active = by_kind["active_event"]
    tariff_row = next(r for r in active if r.artefact_id == env["tariff"].event_id)
    assert "in its window" in tariff_row.headline
    assert "not_measurable" in tariff_row.headline or "unverified" in tariff_row.headline
    # pending gates: the draft scenario run awaits adoption
    pending = by_kind["pending_gate"]
    assert any(
        r.artefact_id == env["scenario_run"].scenario_id for r in pending
    )
    # a clean series does not appear in the exception sections
    assert not any(
        r.commodity == "wheat" for r in degraded + gaps
    )
    # forecast_change rows match the artefacts exactly
    store = env["store"]
    for row in by_kind.get("forecast_change", []):
        runs = [
            f for f in store.list_forecasts(row.commodity, row.market)
            if f.as_of <= BOARD_DATE
        ]
        by_asof: dict[date, object] = {}
        for f in runs:
            current = by_asof.get(f.as_of)
            if current is None or (f.status, f.forecast_id) > (
                current.status, current.forecast_id
            ):
                by_asof[f.as_of] = f
        ordered = [by_asof[d] for d in sorted(by_asof)]
        assert len(ordered) >= 2

        def p50_30(forecast):
            return next(
                s.p50 for s in forecast.horizons_summary
                if s.horizon_days == 30
            )

        expected = round(p50_30(ordered[-1]) - p50_30(ordered[-2]), 2)
        assert expected != 0
        assert row.figures["delta_p50_30"] == expected
        assert row.artefact_id == ordered[-1].forecast_id
    # every row's artefact resolves in the store
    for row in board.rows:
        resolved = (
            store.get_forecast(row.artefact_id)
            or store.get_scenario(row.artefact_id)
            or store.get_market_event(row.artefact_id)
        )
        assert resolved is not None, row
    # the board is an artefact: rebuilding is a no-op
    assert dash.board(BOARD_DATE).board_id == board.board_id


# --- surfaces -------------------------------------------------------------------


def _client(env):
    app = create_app(env["store"], env["model"])
    return TestClient(app)


def test_api_surface(env):
    client = _client(env)
    pack = client.get("/dashboards/pack")
    assert pack.status_code == 200
    assert pack.json()["version"] == "2026.10.1"
    asked = client.post(
        "/dashboards/ask",
        json={
            "prompt": "chili forecast at guntur",
            "asked_by": "a.sharma",
            "created_on": "2026-01-05",
        },
    )
    assert asked.status_code == 200
    spec = asked.json()
    saved = client.post(
        f"/dashboards/specs/{spec['spec_id']}/save",
        json={"name": "chili watch", "saved_by": "a.sharma",
              "saved_on": "2026-01-05"},
    )
    assert saved.status_code == 200
    views = client.get("/dashboards/views", params={"name": "chili watch"})
    assert len(views.json()["views"]) == 1
    assembled = client.post(
        f"/dashboards/specs/{spec['spec_id']}/assemble",
        json={"assembled_on": "2026-01-05"},
    )
    assert assembled.status_code == 200
    assembly = assembled.json()
    # no clean view: even an explicit ?view=clean cannot hide the flag
    page = client.get(
        f"/dashboards/assemblies/{assembly['assembly_id']}/html",
        params={"view": "clean"},
    )
    assert page.status_code == 200
    assert "degraded" in page.text
    appendix = client.get(
        f"/dashboards/assemblies/{assembly['assembly_id']}/appendix"
    )
    assert appendix.status_code == 200
    assert appendix.json()["panels"][0]["figures"]
    verified = client.get(
        f"/dashboards/assemblies/{assembly['assembly_id']}/verify"
    )
    assert verified.json()["problems"] == []
    board = client.get("/board", params={"board_date": "2026-02-15"})
    assert board.status_code == 200
    assert any(
        r["commodity"] == "chili"
        for r in board.json()["sections"]["degraded"]
    )
    board_page = client.get("/board/html", params={"board_date": "2026-02-15"})
    assert "Morning desk board" in board_page.text
    missing = client.get("/dashboards/specs/DSPEC-nope")
    assert missing.status_code == 404
    refused = client.post(
        "/dashboards/ask",
        json={"prompt": "wheat forecast", "asked_by": "unknown"},
    )
    assert refused.status_code == 422


def test_cli_surface(env, capsys):
    db = env["db"]
    rc = dashboard_cli.main(
        ["--db", db, "ask", "--by", "a.sharma", "--on", "2026-01-05",
         "--text", "wheat forecast at delhi"]
    )
    assert rc == 0
    spec = json.loads(capsys.readouterr().out)
    rc = dashboard_cli.main(
        ["--db", db, "assemble", spec["spec_id"], "--on", "2026-01-05"]
    )
    assert rc == 0
    assembly = json.loads(capsys.readouterr().out)
    rc = dashboard_cli.main(["--db", db, "verify", assembly["assembly_id"]])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["problems"] == []
    rc = dashboard_cli.main(["--db", db, "board", "--on", "2026-02-15"])
    assert rc == 0
    board = json.loads(capsys.readouterr().out)
    assert board["sections"]["data_gap"]
    rc = dashboard_cli.main(
        ["--db", db, "ask", "--by", "unknown", "--text", "wheat forecast"]
    )
    assert rc == 2
    capsys.readouterr()


# --- truth isolation ----------------------------------------------------------


def test_dashboards_package_is_truth_isolated():
    base = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "fmcg_forecast"
        / "dashboards"
    )
    for path in base.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "truth" not in alias.name
            elif isinstance(node, ast.ImportFrom):
                assert "truth" not in (node.module or "")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "truth_observations" not in node.value
