"""Round 19 — the integration surface: scoped tokens,
signed webhooks, export jobs, checksum-manifest board
packs, and the MCP-shaped read tools (F20-IA1 +
F20-IA2 + F20-DR2).

Acceptance gates probed here:

- IA1: a webhook payload verifies against its
  signature (re-derived from the subscription's
  secret and the bytes alone) and equals the artefact
  read; a token scoped to forecasts cannot read admin
  surfaces (403 over HTTP); unknown and revoked
  secrets are refused 401; token artefacts store the
  secret's hash and never the secret.
- IA2: an export job's output is byte-identical to
  the synchronous pack for the same as-of (same
  content address, same file bytes); tool responses
  carry an artefact id for every figure.
- DR2: export figures match artefact reads exactly
  (the pack's CSVs are re-performed against the
  artefacts); the checksum manifest detects a
  tampered export file, named by the verifier.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import threading
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.alerts.models import AlertInstance, alert_content_id
from fmcg_forecast.api import create_app
from fmcg_forecast.config import Settings
from fmcg_forecast.console.service import ConsoleService
from fmcg_forecast.dashboards.models import (
    DashboardAssembly,
    DashboardFigure,
    LineageFact,
    ResolvedPanel,
)
from fmcg_forecast.events.service import EventService
from fmcg_forecast.forecast.models import AccuracyRecord
from fmcg_forecast.forecast.service import ForecastService
from fmcg_forecast.integrations import cli as integrations_cli
from fmcg_forecast.integrations.engine import file_bytes
from fmcg_forecast.integrations.models import (
    canonical_payload,
    hash_secret,
    sign_payload,
)
from fmcg_forecast.integrations.pack import load_integrations_pack
from fmcg_forecast.integrations.port import RecordingWebhookPort, UrllibWebhookPort
from fmcg_forecast.integrations.service import (
    IntegrationError,
    IntegrationsService,
    public_subscription,
)
from fmcg_forecast.integrations.tools import TOOL_CATALOGUE, call_tool
from fmcg_forecast.integrations.verify import verify_integrations
from fmcg_forecast.modelport import OfflineModel
from fmcg_forecast.signals.service import SignalService
from fmcg_forecast.store import SqlStore, build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset

PG_DSN = os.environ.get("FMCG_TEST_DATABASE_URL")
AS_OF = date(2026, 1, 5)


@pytest.fixture()
def store(tmp_path) -> SqlStore:
    return build_store(str(tmp_path / "r19.db"))


@pytest.fixture()
def client(store) -> TestClient:
    app = create_app(store)
    return TestClient(app)


@pytest.fixture(scope="module")
def loaded(tmp_path_factory) -> dict:
    """One store with the dataset and a desk's worth of
    artefacts: an approved wheat/indore forecast, its
    buy signal, a planted accuracy record, an active
    soybean event, a retired wheat event, a planted
    alert, and a planted dashboard assembly."""
    db = str(tmp_path_factory.mktemp("r19-loaded") / "loaded.db")
    store = build_store(db)
    load_dataset(store, build_truth_store(db), 20261027)
    forecasts = ForecastService(store, OfflineModel())
    forecast = forecasts.run_forecast("wheat", "indore")
    approval = forecasts.approve(
        forecast.forecast_id, "Asha Rao", "desk_head", AS_OF
    )
    signal = SignalService(store).compute_for_forecast(forecast)
    record = AccuracyRecord(
        record_id="ACC-planted-wheat-indore-30",
        commodity="wheat",
        market="indore",
        horizon_days=30,
        origins=[date(2025, 11, 1), date(2025, 12, 1)],
        n_results=2,
        n_days=60,
        covered_days=57,
        mae=112.5,
        mape=4.25,
        bias=-18.0,
        coverage=0.95,
        engine_version="planted",
        pack_version="planted",
        degraded_threshold_mape_pct=12.0,
        degraded=False,
    )
    store.save_accuracy_record(record)
    events = EventService(store)
    manifest = store.get_manifest()
    events.seed_historical(manifest)
    active = events.register_event(
        event_class="tariff_change",
        commodity="soybean",
        window_start=date(2026, 1, 1),
        window_end=date(2026, 1, 20),
        channel="import_flow",
        peak_log_price_effect=0.08,
        basis="announced_measure",
        basis_detail="a stated duty change in the test fixture",
        decay_days=21,
        description="a duty change over the pack date",
        declared_by="Asha Rao",
        declared_on=date(2025, 12, 30),
    )
    retired = events.register_event(
        event_class="export_restriction",
        commodity="wheat",
        window_start=date(2026, 1, 1),
        window_end=date(2026, 1, 20),
        channel="export_flow",
        peak_log_price_effect=-0.05,
        basis="announced_measure",
        basis_detail="a stated restriction in the test fixture",
        decay_days=14,
        description="a restriction the desk later retires",
        declared_by="Asha Rao",
        declared_on=date(2025, 12, 30),
    )
    console = ConsoleService(store, events)
    console.retire_event(
        retired.event_id, "Asha Rao", "desk_head", date(2026, 1, 2),
        "superseded by the duty change",
    )
    alert = AlertInstance(
        alert_id=alert_content_id("ALS-planted", "signal_buy", signal.signal_id),
        subscription_id="ALS-planted",
        subscriber="Asha Rao",
        kind="signal_buy",
        commodity="wheat",
        market="indore",
        severity="high",
        trigger_id=signal.signal_id,
        trigger_summary={"value": signal.value},
        raised_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
        pack_version="planted",
        scope_note="planted by the R19 tests",
    )
    store.insert_alert(alert)
    assembly = DashboardAssembly(
        assembly_id="DASM-planted-r19",
        spec_id="DSPEC-planted-r19",
        seq=1,
        supersedes=None,
        assembled_on=AS_OF,
        pack_version="planted",
        panels=[
            ResolvedPanel(
                panel_no=1,
                kind="forecast",
                title="Wheat at Indore",
                state="rendered",
                figures=[
                    DashboardFigure(
                        key="p50_30d",
                        label="P50 at 30 days",
                        value=2674.52,
                        unit="INR/quintal",
                        artefact_id=forecast.forecast_id,
                        lineage=[
                            LineageFact(
                                kind="forecast",
                                ref=forecast.forecast_id,
                                detail="the approved forecast's 30-day P50",
                                source="the forecast artefact",
                                fact_date=forecast.as_of,
                            )
                        ],
                    )
                ],
                artefact_ids=[forecast.forecast_id],
            )
        ],
        diff=[],
        html="<html></html>",
    )
    store.insert_dashboard_assembly(assembly)
    return {
        "store": store,
        "forecast": forecast,
        "approval": approval,
        "signal": signal,
        "record": record,
        "active_event": active,
        "retired_event": retired,
        "alert": alert,
        "assembly": assembly,
    }


# ---------------------------------------------------------------- pack


def test_pack_loader_fail_closed(tmp_path):
    target = tmp_path / "pack.json"
    pack = load_integrations_pack()
    data = json.loads(pack.model_dump_json())
    data["version"] = "1999.1.1"
    target.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_integrations_pack(target)


def test_pack_states_the_surface_map_and_sections():
    pack = load_integrations_pack()
    assert pack.version == "2026.10.1"
    assert "forecasts" in pack.surfaces and "admin" in pack.surfaces
    assert [s.name for s in pack.sections] == [
        "official_forecasts",
        "accuracy_summary",
        "active_events",
        "buy_signals",
    ]


# --------------------------------------------------------------- tokens


def test_token_issue_stores_hash_only(store):
    service = IntegrationsService(store)
    token, secret = service.issue_token(
        "erp-bridge", ["signals", "forecasts"], "Asha Rao"
    )
    assert token.scopes == ["forecasts", "signals"]  # sorted, stated
    assert token.secret_hash == hash_secret(secret)
    assert secret not in json.dumps(
        store.get_integration_token(token.token_id).model_dump(mode="json")
    )
    assert service.authenticate(secret).token_id == token.token_id
    assert service.authenticate("not-the-secret") is None
    assert service.authenticate("") is None


def test_token_issue_rejects_unknown_and_repeated_scopes(store):
    service = IntegrationsService(store)
    with pytest.raises(IntegrationError, match="closed vocabulary"):
        service.issue_token("bad", ["root"], "Asha Rao")
    with pytest.raises(IntegrationError, match="may not repeat"):
        service.issue_token("bad", ["forecasts", "forecasts"], "Asha Rao")
    with pytest.raises(IntegrationError, match="at least one scope"):
        service.issue_token("bad", [], "Asha Rao")
    assert store.list_integration_tokens() == []


def test_token_revoke_folds_and_refuses_repeats(store):
    service = IntegrationsService(store)
    token, secret = service.issue_token("crm", ["board"], "Asha Rao")
    assert service.token_state(token) == "standing"
    act = service.revoke_token(token.token_id, "Asha Rao", "bridge replaced")
    assert act.act == "revoke"
    standing = store.get_integration_token(token.token_id)
    assert service.token_state(standing) == "revoked"
    assert service.authenticate(secret) is None
    with pytest.raises(IntegrationError, match="already revoked"):
        service.revoke_token(token.token_id, "Asha Rao", "again")
    with pytest.raises(IntegrationError, match="no integration token"):
        service.revoke_token("TOK-missing", "Asha Rao", "nope")


def test_http_token_scope_judgement(loaded):
    store = loaded["store"]
    app = create_app(store)
    http = TestClient(app)
    forecast_id = loaded["forecast"].forecast_id
    # No token presented: the local posture.
    assert http.get(f"/forecasts/{forecast_id}").status_code == 200
    # Issue a forecasts-scoped token over HTTP.
    issued = http.post(
        "/integrations/tokens",
        json={
            "name": "erp",
            "scopes": ["forecasts"],
            "issued_by": "Asha Rao",
        },
    )
    assert issued.status_code == 201
    secret = issued.json()["secret_shown_once"]
    headers = {"Authorization": f"Bearer {secret}"}
    # In scope: the forecast reads.
    assert http.get(f"/forecasts/{forecast_id}", headers=headers).status_code == 200
    # Out of scope: admin surfaces refuse 403 — the pack,
    # the token list itself, access and desk surfaces.
    for path in ("/integrations/pack", "/integrations/tokens",
                 "/access/pack", "/desk/pack"):
        denied = http.get(path, headers=headers)
        assert denied.status_code == 403, (path, denied.status_code)
        assert "forecasts" in denied.json()["detail"] or "scoped" in denied.json()["detail"]
    # Unknown secret: 401 anywhere.
    bad = {"Authorization": "Bearer not-a-secret"}
    assert http.get(f"/forecasts/{forecast_id}", headers=bad).status_code == 401
    # Open paths stay open without a token.
    assert http.get("/health").status_code == 200
    # Revoke: the same secret is refused 401 afterwards.
    token_id = issued.json()["token"]["token_id"]
    revoked = http.post(
        f"/integrations/tokens/{token_id}/revoke",
        json={"actor": "Asha Rao", "reason": "rotation"},
    )
    assert revoked.status_code == 200
    assert http.get(f"/forecasts/{forecast_id}", headers=headers).status_code == 401


def test_http_token_list_never_carries_a_secret(client):
    issued = client.post(
        "/integrations/tokens",
        json={"name": "crm", "scopes": ["board"], "issued_by": "Asha Rao"},
    )
    secret = issued.json()["secret_shown_once"]
    listed = client.get("/integrations/tokens")
    assert listed.status_code == 200
    assert secret not in listed.text
    assert '"secret":' not in listed.text  # the hash stands; no secret field


# ---------------------------------------------------------- subscriptions


def test_subscription_reads_are_redacted(store):
    service = IntegrationsService(store)
    subscription, secret = service.create_subscription(
        "crm", "https://example.invalid/hook", ["alert_raised"], "Asha Rao"
    )
    read = public_subscription(subscription)
    assert read["secret"] is None
    assert read["secret_set"] is True
    assert read["secret_hash_prefix"] == hash_secret(secret)[:12]
    assert secret not in json.dumps(read)


def test_subscription_kinds_validated(store):
    service = IntegrationsService(store)
    with pytest.raises(IntegrationError, match="closed vocabulary"):
        service.create_subscription(
            "crm", "https://example.invalid/hook", ["everything"], "Asha Rao"
        )
    with pytest.raises(IntegrationError, match="endpoint"):
        service.create_subscription(
            "crm", "ftp://example.invalid/hook", ["alert_raised"], "Asha Rao"
        )
    assert store.list_webhook_subscriptions() == []


# -------------------------------------------------------------- dispatch


def test_dispatch_signs_the_artefact_read_and_dedups(loaded):
    store = loaded["store"]
    service = IntegrationsService(store)
    subscription, secret = service.create_subscription(
        "crm",
        "https://example.invalid/hook",
        ["forecast_approved"],
        "Asha Rao",
    )
    port = RecordingWebhookPort()
    struck = service.dispatch(port)
    assert len(struck) == 1
    delivery = struck[0]
    approval = loaded["approval"]
    assert delivery.event_kind == "forecast_approved"
    assert delivery.source_artefact_id == approval.approval_id
    assert delivery.outcome == "delivered"
    call = port.calls[0]
    # The payload IS the artefact read, byte for byte.
    assert call["body"].decode() == delivery.payload
    assert delivery.payload == canonical_payload(
        store.get_approval(loaded["forecast"].forecast_id).model_dump(mode="json")
    )
    # The signature re-derives from the secret and the bytes.
    assert call["headers"]["x-fmcg-signature"] == sign_payload(
        secret, delivery.payload
    )
    assert call["headers"]["x-fmcg-delivery"] == delivery.delivery_id
    assert call["headers"]["x-fmcg-event"] == "forecast_approved"
    # A delivered pair is never delivered twice.
    assert service.dispatch(port) == []
    assert verify_integrations(store) == []


def test_dispatch_filters_by_kind_and_covers_all_three(loaded):
    store = loaded["store"]
    service = IntegrationsService(store)
    service.create_subscription(
        "ops", "https://example.invalid/ops", ["alert_raised"], "Asha Rao"
    )
    service.create_subscription(
        "desk",
        "https://example.invalid/desk",
        ["event_triaged"],
        "Asha Rao",
    )
    port = RecordingWebhookPort()
    struck = service.dispatch(port)
    kinds = {(d.subscription_id, d.event_kind) for d in struck}
    assert ("alert_raised") in {k for _, k in kinds}
    assert ("event_triaged") in {k for _, k in kinds}
    # The retire act is a triage source; the alert is its own.
    triage = [d for d in struck if d.event_kind == "event_triaged"]
    assert triage[0].source_artefact_id.startswith("TRI-")
    alerts = [d for d in struck if d.event_kind == "alert_raised"]
    assert alerts[0].source_artefact_id == loaded["alert"].alert_id
    assert verify_integrations(store) == []


def test_dispatch_failure_is_recorded_and_retried(loaded):
    store = loaded["store"]
    service = IntegrationsService(store)
    service.create_subscription(
        "crm",
        "https://example.invalid/hook",
        ["forecast_approved"],
        "Asha Rao",
    )
    failing = RecordingWebhookPort(status=503)
    struck = service.dispatch(failing)
    assert len(struck) == 1
    assert struck[0].outcome == "failed"
    assert struck[0].http_status == 503
    assert "503" in (struck[0].error or "")
    assert struck[0].attempt == 1
    # The pair is still owed: the next dispatch retries
    # with the next ordinal and delivers.
    ok = RecordingWebhookPort(status=200)
    retried = service.dispatch(ok)
    assert len(retried) == 1
    assert retried[0].attempt == 2
    assert retried[0].outcome == "delivered"
    assert service.dispatch(ok) == []
    assert verify_integrations(store) == []


def test_dispatch_over_real_http(loaded):
    received: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - the stdlib's name
            length = int(self.headers["Content-Length"])
            received["body"] = self.rfile.read(length)
            received["signature"] = self.headers.get("x-fmcg-signature")
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):  # keep the test log clean
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        store = loaded["store"]
        service = IntegrationsService(store)
        subscription, secret = service.create_subscription(
            "local",
            f"http://127.0.0.1:{server.server_port}/hook",
            ["forecast_approved"],
            "Asha Rao",
        )
        struck = service.dispatch(UrllibWebhookPort())
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert len(struck) == 1 and struck[0].outcome == "delivered"
    assert received["body"].decode() == struck[0].payload
    assert received["signature"] == sign_payload(secret, struck[0].payload)


# ------------------------------------------------------------ board pack


def _rows(board, name: str) -> list[dict]:
    for file in board.files:
        if file.name == name:
            return list(
                csv.DictReader(io.StringIO(file_bytes(file).decode()))
            )
    raise AssertionError(f"pack carries no {name}")


def test_board_pack_folds_from_artefacts(loaded):
    store = loaded["store"]
    service = IntegrationsService(store)
    board = service.build_pack(AS_OF)
    names = [f.name for f in board.files]
    assert names == [
        "official_forecasts.csv",
        "accuracy_summary.csv",
        "active_events.csv",
        "buy_signals.csv",
        "pack.pdf",
        "manifest.json",
    ]
    # Official forecasts: one row per day of the approved
    # forecast, figures exactly the artefact's.
    forecast = loaded["forecast"]
    official = _rows(board, "official_forecasts.csv")
    assert len(official) == len(forecast.days)
    first = official[0]
    assert first["forecast_id"] == forecast.forecast_id
    assert float(first["p50_inr"]) == forecast.days[0].p50
    assert first["approved_by"] == "Asha Rao"
    # Accuracy: the planted record, figures exact.
    accuracy = _rows(board, "accuracy_summary.csv")
    planted = [r for r in accuracy if r["record_id"] == loaded["record"].record_id]
    assert len(planted) == 1
    assert float(planted[0]["mape_pct"]) == loaded["record"].mape
    assert planted[0]["degraded"] == "false"
    # Events: the active event stands; the retired one
    # does not.
    events = _rows(board, "active_events.csv")
    event_ids = {r["event_id"] for r in events}
    assert loaded["active_event"].event_id in event_ids
    assert loaded["retired_event"].event_id not in event_ids
    # Signals: the computed signal, value exact.
    signals = _rows(board, "buy_signals.csv")
    mine = [r for r in signals if r["signal_id"] == loaded["signal"].signal_id]
    assert len(mine) == 1
    assert mine[0]["value"] == loaded["signal"].value
    assert board.section_rows["official_forecasts"] == len(forecast.days)
    # The PDF is a real PDF.
    pdf = next(f for f in board.files if f.name == "pack.pdf")
    assert file_bytes(pdf).startswith(b"%PDF-1.4")
    assert verify_integrations(store) == []


def test_board_pack_build_is_idempotent(loaded):
    service = IntegrationsService(loaded["store"])
    first = service.build_pack(AS_OF)
    second = service.build_pack(AS_OF)
    assert first.pack_id == second.pack_id
    assert [f.sha256 for f in first.files] == [f.sha256 for f in second.files]


def test_manifest_detects_a_tampered_file(store, loaded):
    source = IntegrationsService(loaded["store"])
    board = source.build_pack(AS_OF)
    # A copy of the board whose first CSV has one figure
    # altered, its stored hash left as struck: the
    # manifest and the verifier must name it.
    files = []
    for file in board.files:
        if file.name == "official_forecasts.csv":
            import base64

            raw = bytearray(file_bytes(file))
            raw[-2] = ord("9") if raw[-2] != ord("9") else ord("8")
            file = file.model_copy(
                update={
                    "content_b64": base64.b64encode(bytes(raw)).decode(),
                    "size_bytes": len(raw),
                }
            )
        files.append(file)
    doctored = board.model_copy(update={"files": files})
    store.insert_board_pack(doctored)
    problems = verify_integrations(store)
    assert any(
        "official_forecasts.csv" in p and "hashes differently" in p
        for p in problems
    ), problems
    assert any("content id mismatch" in p for p in problems), problems


def test_verify_names_a_forged_token_scope(store, tmp_path):
    service = IntegrationsService(store)
    token, _secret = service.issue_token("crm", ["board"], "Asha Rao")
    forged = token.model_copy(update={"scopes": ["board", "root"]})
    other = build_store(str(tmp_path / "forged.db"))
    other.insert_integration_token(forged)
    problems = verify_integrations(other)
    assert any("root" in p and "closed vocabulary" in p for p in problems), problems
    assert any("content id mismatch" in p for p in problems), problems


def test_verify_names_a_doctored_delivery(store, loaded):
    source = IntegrationsService(loaded["store"])
    subscription, _secret = source.create_subscription(
        "crm",
        "https://example.invalid/hook",
        ["forecast_approved"],
        "Asha Rao",
    )
    struck = source.dispatch(RecordingWebhookPort())
    delivery = struck[0]
    forged = delivery.model_copy(update={"signature": "0" * 64})
    store.insert_webhook_subscription(subscription)
    store.insert_webhook_delivery(forged)
    problems = verify_integrations(store)
    assert any("signature does not re-derive" in p for p in problems), problems


# ------------------------------------------------------------ export job


def test_job_output_is_the_sync_pack(loaded):
    store = loaded["store"]
    service = IntegrationsService(store)
    board = service.build_pack(AS_OF)
    job = service.request_job("Asha Rao", AS_OF)
    assert service.job_state(job) == "requested"
    # The same request again is the same job.
    assert service.request_job("Asha Rao", AS_OF).job_id == job.job_id
    act = service.run_job(job.job_id)
    assert act.act == "complete"
    assert act.board_pack_id == board.pack_id
    # Byte-identical: the job's pack is the sync pack,
    # file for file.
    job_pack = store.get_board_pack(act.board_pack_id)
    assert [f.content_b64 for f in job_pack.files] == [
        f.content_b64 for f in board.files
    ]
    standing = store.get_export_job(job.job_id)
    assert service.job_state(standing) == "complete"
    with pytest.raises(IntegrationError, match="runs once"):
        service.run_job(job.job_id)
    with pytest.raises(IntegrationError, match="no export job"):
        service.run_job("JOB-missing")
    assert verify_integrations(store) == []


# ----------------------------------------------------------------- tools


def test_tools_carry_artefact_ids_for_every_figure(loaded):
    store = loaded["store"]
    forecast = call_tool(
        store, "get_forecast", {"forecast_id": loaded["forecast"].forecast_id}
    )
    assert forecast["figures"]
    assert all(
        f["artefact_id"] == loaded["forecast"].forecast_id
        for f in forecast["figures"]
    )
    p50 = {f["name"]: f["value"] for f in forecast["figures"]}
    summary = {h.horizon_days: h.p50 for h in loaded["forecast"].horizons_summary}
    assert p50["p50_30d_inr"] == summary[30]
    accuracy = call_tool(
        store,
        "get_accuracy",
        {"commodity": "wheat", "market": "indore", "horizon_days": 30},
    )
    assert all(
        f["artefact_id"] == loaded["record"].record_id
        for f in accuracy["figures"]
    )
    signal = call_tool(
        store, "get_signal", {"signal_id": loaded["signal"].signal_id}
    )
    assert {f["name"] for f in signal["figures"]} >= {"value", "drift_pct"}
    event = call_tool(
        store, "get_event", {"event_id": loaded["active_event"].event_id}
    )
    assert event["figures"][0]["artefact_id"] == loaded["active_event"].event_id
    assembly = call_tool(
        store,
        "get_dashboard_assembly",
        {"assembly_id": loaded["assembly"].assembly_id},
    )
    assert assembly["figures"] == [
        {
            "name": "panel_1:p50_30d",
            "value": 2674.52,
            "artefact_id": loaded["forecast"].forecast_id,
        }
    ]
    assert {t["name"] for t in TOOL_CATALOGUE} == {
        "get_forecast",
        "get_accuracy",
        "get_signal",
        "get_event",
        "get_dashboard_assembly",
    }


def test_tools_refuse_unknown_missing_and_unbuilt(loaded):
    store = loaded["store"]
    with pytest.raises(IntegrationError, match="no tool"):
        call_tool(store, "delete_everything", {})
    with pytest.raises(IntegrationError, match="forecast_id"):
        call_tool(store, "get_forecast", {})
    with pytest.raises(IntegrationError, match="no forecast"):
        call_tool(store, "get_forecast", {"forecast_id": "FCST-nope"})
    with pytest.raises(IntegrationError, match="no dashboard assembly"):
        call_tool(
            store, "get_dashboard_assembly", {"assembly_id": "DASM-nope"}
        )


# ------------------------------------------------------------------- API


def test_api_pack_files_and_verify(loaded):
    store = loaded["store"]
    app = create_app(store)
    http = TestClient(app)
    built = http.post("/integrations/packs", json={"as_of": "2026-01-05"})
    assert built.status_code == 201
    pack_id = built.json()["pack_id"]
    manifest = http.get(f"/integrations/packs/{pack_id}/files/manifest.json")
    assert manifest.status_code == 200
    named = json.loads(manifest.content)
    assert named["pack_id"] == pack_id
    csv_file = http.get(
        f"/integrations/packs/{pack_id}/files/official_forecasts.csv"
    )
    assert csv_file.status_code == 200
    digest = hashlib.sha256(csv_file.content).hexdigest()
    entry = next(
        f for f in named["files"] if f["name"] == "official_forecasts.csv"
    )
    assert entry["sha256"] == digest
    assert entry["size_bytes"] == len(csv_file.content)
    assert http.get("/integrations/packs/BPK-nope").status_code == 404
    assert (
        http.get(f"/integrations/packs/{pack_id}/files/nope.csv").status_code
        == 404
    )
    assert http.get("/integrations/verify").json() == {"problems": []}
    tools = http.get("/integrations/tools").json()["tools"]
    assert len(tools) == 5
    called = http.post(
        "/integrations/tools/get_forecast/call",
        json={"args": {"forecast_id": loaded["forecast"].forecast_id}},
    )
    assert called.status_code == 200
    assert called.json()["figures"]


def test_api_jobs_round_trip(client):
    requested = client.post(
        "/integrations/jobs",
        json={"requested_by": "Asha Rao", "as_of": "2026-01-05"},
    )
    assert requested.status_code == 201
    assert requested.json()["state"] == "requested"
    job_id = requested.json()["job_id"]
    ran = client.post(f"/integrations/jobs/{job_id}/run")
    assert ran.status_code == 200
    assert ran.json()["act"] == "complete"
    fetched = client.get(f"/integrations/jobs/{job_id}")
    assert fetched.json()["state"] == "complete"
    assert client.post(f"/integrations/jobs/{job_id}/run").status_code == 422
    assert client.get("/integrations/jobs/JOB-nope").status_code == 404


def test_api_subscriptions_redacted_and_dispatch_empty(client):
    created = client.post(
        "/integrations/subscriptions",
        json={
            "name": "crm",
            "endpoint_url": "https://example.invalid/hook",
            "event_kinds": ["alert_raised"],
            "created_by": "Asha Rao",
        },
    )
    assert created.status_code == 201
    secret = created.json()["secret_shown_once"]
    listed = client.get("/integrations/subscriptions")
    assert secret not in listed.text
    assert listed.json()["subscriptions"][0]["secret"] is None
    # No sources stand in the empty store: nothing to send.
    dispatched = client.post("/integrations/dispatch")
    assert dispatched.json() == {"deliveries": []}


# ------------------------------------------------------------------- CLI


def test_cli_round_trip(tmp_path):
    db = str(tmp_path / "cli.db")
    assert integrations_cli.main(["--db", db, "pack"]) == 0
    assert (
        integrations_cli.main(
            [
                "--db", db, "issue-token", "erp",
                "--scopes", "forecasts,signals", "--by", "Asha Rao",
            ]
        )
        == 0
    )
    assert integrations_cli.main(["--db", db, "tokens"]) == 0
    assert (
        integrations_cli.main(
            ["--db", db, "build-pack", "--as-of", "2026-01-05"]
        )
        == 0
    )
    assert (
        integrations_cli.main(
            [
                "--db", db, "request-job",
                "--by", "Asha Rao", "--as-of", "2026-01-05",
            ]
        )
        == 0
    )
    assert integrations_cli.main(["--db", db, "jobs"]) == 0
    assert integrations_cli.main(["--db", db, "tools"]) == 0
    assert integrations_cli.main(["--db", db, "verify"]) == 0
    # An unknown scope is a stated refusal, exit 2.
    assert (
        integrations_cli.main(
            [
                "--db", db, "issue-token", "bad",
                "--scopes", "root", "--by", "Asha Rao",
            ]
        )
        == 2
    )


# ---------------------------------------------------------------- parity


def _parity_walk(store, truth_path: str) -> dict:
    load_dataset(store, build_truth_store(truth_path), 20261027)
    forecasts = ForecastService(store, OfflineModel())
    forecast = forecasts.run_forecast("wheat", "indore")
    forecasts.approve(forecast.forecast_id, "Asha Rao", "desk_head", AS_OF)
    service = IntegrationsService(store)
    subscription, _secret = service.create_subscription(
        "crm",
        "https://example.invalid/hook",
        ["forecast_approved"],
        "Asha Rao",
    )
    port = RecordingWebhookPort()
    struck = service.dispatch(port)
    board = service.build_pack(AS_OF)
    job = service.request_job("Asha Rao", AS_OF)
    act = service.run_job(job.job_id)
    return {
        "deliveries": [
            (d.event_kind, d.source_artefact_id, d.outcome, d.payload)
            for d in struck
        ],
        "pack_id": board.pack_id,
        "section_rows": board.section_rows,
        "file_hashes": {f.name: f.sha256 for f in board.files},
        "job_pack": act.board_pack_id,
        "job_state": service.job_state(store.get_export_job(job.job_id)),
        "problems": verify_integrations(store),
    }


@pytest.mark.skipif(PG_DSN is None, reason="FMCG_TEST_DATABASE_URL not set")
def test_postgres_parity(tmp_path):
    # The walk compares ACROSS stores, and the pack folds
    # its store's whole artefact set — so both sides need
    # a clean room: a fresh file on SQLite, a fresh
    # database on the cluster (the suite's shared
    # database already holds every earlier file's
    # artefacts, which are the pack's rightful contents
    # there, not a parity difference).
    import secrets as _secrets

    import psycopg as _psycopg

    sqlite_walk = _parity_walk(
        build_store(str(tmp_path / "parity.db")), str(tmp_path / "truth-a.db")
    )
    fresh_db = f"fmcg_r19_{_secrets.token_hex(6)}"
    admin = _psycopg.connect(
        PG_DSN.rsplit("/", 1)[0] + "/postgres", autocommit=True
    )
    admin.execute(
        f'CREATE DATABASE "{fresh_db}" '
        "WITH ENCODING 'UTF8' TEMPLATE template0"
    )
    fresh_dsn = PG_DSN.rsplit("/", 1)[0] + f"/{fresh_db}"
    pg_store = build_store(database_url=fresh_dsn)
    try:
        pg_walk = _parity_walk(pg_store, str(tmp_path / "truth-b.db"))
    finally:
        pg_store.close()
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (fresh_db,),
        )
        admin.execute(f'DROP DATABASE "{fresh_db}"')
        admin.close()
    assert pg_walk == sqlite_walk
