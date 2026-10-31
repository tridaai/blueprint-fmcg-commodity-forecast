"""Local harness: boot the real API server and exercise it over HTTP.

Loads the dataset into a throwaway database, starts uvicorn on a
local port, and checks /health, /readiness, /manifest, /events and
a /series read — the same contract a desk client would use. Round 4
adds the sentiment surface: corpus manifest, items, the weekly
index, a forecast's sentiment line (estimated for wheat, named
not-estimable for groundnut). Round 5 adds the event registry: the
seeded planted shocks with their transmission verdicts, the
drought's what-happened view, an analyst declaration over HTTP,
and the declared event landing on a forecast as its own line.
Round 6 adds the scenario studio: the pack read, a typed what-if
parsed and refused over HTTP, the fork run with its diff, and
the adoption gate from placeholder refusal to the adopted view.
Round 14 adds geospatial basis & netting: the geo pack, a desk
cost line landing with its provenance (and an uncatalogued line
refused), a basis reading against the reference market, a
landed comparison naming its missing handling line, and the
market map inside the planted tariff window carrying the
event overlay. Round 15 adds desk policy, approvals, config:
the standing pack read, a proposal landing proposed with its
diff, the two-person chain refusing its own proposer, the
completing sign-off standing the version, the gapless
decision log, and a comment and follow-up task pinned to the
forecast. Round 16 adds identity, scopes, the access audit,
and master data: the access pack, the bootstrap grant landing
flagged, a scoped trader's in-scope read served and their
out-of-scope read hidden as the same 404 a missing forecast
gets, the unnamed local posture intact, the audit log folding
gaplessly, a master data version struck by the desk head (and
refused to the trader), and the kanpur holiday re-deriving
coverage for exactly the windows containing it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PORT = 8137
BASE = f"http://127.0.0.1:{PORT}"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fmcg-harness-"))
    env = dict(os.environ)
    env["FMCG_SQLITE_PATH"] = str(tmp / "harness.db")
    env["FMCG_PORT"] = str(PORT)
    env["PYTHONPATH"] = str(ROOT / "src")
    proc = subprocess.Popen(
        [sys.executable, "-m", "fmcg_forecast.serve"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    client = httpx.Client(trust_env=False, timeout=5)
    try:
        deadline = time.time() + 120
        while True:
            try:
                r = client.get(f"{BASE}/health")
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.time() > deadline:
                raise SystemExit("server did not come up in time")
            time.sleep(0.5)

        checks = []
        r = client.get(f"{BASE}/readiness")
        checks.append(("readiness", r.status_code == 200 and r.json()["status"] == "ready"))
        r = client.get(f"{BASE}/manifest")
        checks.append(("manifest", r.status_code == 200 and r.json()["history_rows"] > 0))
        r = client.get(f"{BASE}/events")
        checks.append(("events", r.status_code == 200 and len(r.json()["events"]) == 2))
        r = client.get(
            f"{BASE}/series",
            params={
                "commodity": "wheat",
                "market": "indore",
                "driver": "modal_price",
                "start": "2025-01-01",
                "end": "2025-01-31",
            },
        )
        checks.append(("series", r.status_code == 200 and len(r.json()["points"]) > 20))
        r = client.get(f"{BASE}/coverage/coffee")
        checks.append(
            ("coffee coverage names gaps", r.status_code == 200 and "stock_level" in r.json()["missing_drivers"])
        )
        r = client.post(
            f"{BASE}/forecasts/run",
            json={"commodity": "wheat", "market": "indore"},
        )
        forecast_id = r.json()["forecast_id"] if r.status_code == 200 else None
        checks.append(
            ("forecast run", r.status_code == 200 and r.json()["status"] == "draft" and len(r.json()["days"]) == 90)
        )
        r = client.get(f"{BASE}/forecasts/{forecast_id}/contributions")
        checks.append(
            ("contribution breakdown", r.status_code == 200 and len(r.json()["lines"]) == 6)
        )
        r = client.get(f"{BASE}/sentiment/manifest")
        checks.append(
            ("sentiment corpus manifest", r.status_code == 200 and r.json()["item_count"] == 583)
        )
        r = client.get(f"{BASE}/sentiment/items", params={"commodity": "coffee"})
        checks.append(
            ("coffee corpus is exactly four items", r.status_code == 200 and len(r.json()["items"]) == 4)
        )
        r = client.get(f"{BASE}/sentiment/items", params={"commodity": "wheat"})
        first_wheat_item = r.json()["items"][0]["item_id"] if r.status_code == 200 else None
        r = client.get(f"{BASE}/sentiment/items/{first_wheat_item}")
        checks.append(
            (
                "one item read with its extraction",
                r.status_code == 200 and r.json()["extraction"] is not None,
            )
        )
        r = client.get(f"{BASE}/sentiment/index/wheat")
        checks.append(
            ("wheat weekly indices listed", r.status_code == 200 and len(r.json()["indices"]) > 100)
        )
        r = client.get(f"{BASE}/sentiment/verify")
        checks.append(
            ("sentiment re-performance clean", r.status_code == 200 and r.json()["problems"] == [])
        )
        r = client.get(f"{BASE}/forecasts/{forecast_id}/sentiment")
        checks.append(
            (
                "wheat forecast sentiment line is estimated",
                r.status_code == 200 and r.json()["state"] == "estimated",
            )
        )
        r = client.post(
            f"{BASE}/forecasts/run", json={"commodity": "groundnut", "market": "rajkot"}
        )
        groundnut_id = r.json()["forecast_id"] if r.status_code == 200 else None
        r = client.get(f"{BASE}/forecasts/{groundnut_id}/sentiment")
        checks.append(
            (
                "groundnut sentiment line is named not-estimable",
                r.status_code == 200 and r.json()["state"] == "not_estimable",
            )
        )
        r = client.get(f"{BASE}/forecasts/{forecast_id}/verify")
        checks.append(
            ("stored forecast verifies", r.status_code == 200 and r.json()["problems"] == [])
        )
        r = client.post(f"{BASE}/forecasts/{forecast_id}/commentary")
        checks.append(("commentary drafted + verified", r.status_code == 200 and bool(r.json()["text"])))
        r = client.post(
            f"{BASE}/forecasts/{forecast_id}/approve",
            json={"approver": "r.menon", "role": "Head of Trading Desk", "decided_on": "2026-01-02"},
        )
        checks.append(("approval act", r.status_code == 200 and r.json()["forecast_id"] == forecast_id))
        r = client.post(
            f"{BASE}/forecasts/run",
            json={"commodity": "wheat", "market": "indore", "as_of": "2026-02-01"},
        )
        checks.append(("sealed window refused over HTTP", r.status_code == 403))
        r = client.post(
            f"{BASE}/forecasts/run", json={"commodity": "chili", "market": "guntur"}
        )
        pre_accuracy = r.json()["accuracy"]["state"] if r.status_code == 200 else None
        checks.append(
            ("forecast before backtests is named unmeasured", pre_accuracy == "unmeasured")
        )
        with httpx.Client(trust_env=False, timeout=180) as slow:
            r = slow.post(f"{BASE}/backtests/run", json={})
        checks.append(
            (
                "backtest harness run",
                r.status_code == 200
                and r.json()["results_stored"] == 405
                and r.json()["ledger_records"] == 42
                and len(r.json()["skipped"]) == 5,
            )
        )
        r = client.get(f"{BASE}/accuracy/chili/guntur/30")
        checks.append(
            (
                "chili/guntur 30d record is degraded",
                r.status_code == 200 and r.json()["degraded"] is True and r.json()["mape"] > 5.0,
            )
        )
        r = client.get(f"{BASE}/accuracy/wheat/delhi_khari_baoli/30")
        checks.append(
            (
                "wheat/delhi 30d record is measured, not degraded",
                r.status_code == 200 and r.json()["degraded"] is False,
            )
        )
        checksel = client.get(f"{BASE}/backtests", params={"commodity": "coffee"})
        checks.append(
            ("coffee backtest results listed", checksel.status_code == 200 and len(checksel.json()["results"]) == 15)
        )
        r = client.post(
            f"{BASE}/forecasts/run", json={"commodity": "chili", "market": "guntur"}
        )
        chili_id = r.json()["forecast_id"] if r.status_code == 200 else None
        checks.append(
            (
                "fresh chili forecast carries the degraded flag",
                r.status_code == 200 and r.json()["accuracy"]["state"] == "degraded",
            )
        )
        r = client.get(f"{BASE}/forecasts/{chili_id}/accuracy")
        checks.append(
            (
                "forecast accuracy read",
                r.status_code == 200 and r.json()["accuracy"]["state"] == "degraded",
            )
        )
        r = client.get(f"{BASE}/forecasts/{chili_id}", params={"view": "clean"})
        checks.append(
            (
                "the flag cannot be suppressed by a view parameter",
                r.status_code == 200 and r.json()["accuracy"]["state"] == "degraded",
            )
        )
        r = client.get(f"{BASE}/market-events")
        seeded_events = r.json()["events"] if r.status_code == 200 else []
        checks.append(
            (
                "event registry seeded with the three planted shocks",
                r.status_code == 200 and len(seeded_events) == 3,
            )
        )
        tariff_view = next(
            (e for e in seeded_events if e["source_record_id"] == "EVT-2025-TARIFF-SOYBEAN"),
            None,
        )
        checks.append(
            (
                "the planted tariff's transmission verifies on its face",
                tariff_view is not None
                and tariff_view["verification"]["status"] == "verified"
                and tariff_view["verification"]["measured_ratio"] is not None
                and 1.06 <= tariff_view["verification"]["measured_ratio"] <= 1.24,
            )
        )
        drought_view = next(
            (e for e in seeded_events if e["event_class"] == "weather_shock"),
            None,
        )
        r = client.get(
            f"{BASE}/market-events/{drought_view['event_id']}/impact",
            params={"market": "guntur"},
        )
        checks.append(
            (
                "drought what-happened view is measured",
                drought_view is not None
                and r.status_code == 200
                and r.json()["state"] == "measured"
                and r.json()["mean_price_ratio"] > 1.0,
            )
        )
        r = client.post(
            f"{BASE}/market-events",
            json={
                "event_class": "logistics_disruption",
                "commodity": "cumin",
                "window_start": "2026-01-20",
                "window_end": "2026-02-10",
                "channel": "arrivals",
                "peak_log_price_effect": 0.05,
                "basis": "desk_estimate",
                "basis_detail": "Desk estimate: the corridor disruption "
                "thins arrivals at the reference market for three weeks",
                "decay_days": 10,
                "description": "Transport corridor disruption expected "
                "to thin arrivals",
                "declared_by": "a.sharma",
                "declared_on": "2026-01-02",
            },
        )
        declared_id = r.json()["event_id"] if r.status_code == 201 else None
        checks.append(("event declaration accepted as an analyst act", declared_id is not None))
        r = client.post(
            f"{BASE}/forecasts/run", json={"commodity": "cumin", "market": "unjha"}
        )
        cumin_id = r.json()["forecast_id"] if r.status_code == 200 else None
        r = client.get(f"{BASE}/forecasts/{cumin_id}/events")
        checks.append(
            (
                "declared event lands on the forecast as its own line",
                r.status_code == 200
                and r.json()["state"] == "shocked"
                and declared_id in r.json()["events_applied"]
                and r.json()["interval_widening"] == 1.25,
            )
        )
        r = client.get(f"{BASE}/forecasts/{cumin_id}/verify")
        checks.append(
            (
                "shocked forecast verifies clean",
                r.status_code == 200 and r.json()["problems"] == [],
            )
        )
        r = client.get(f"{BASE}/scenarios/pack")
        checks.append(
            (
                "scenario pack states the bounded lever catalogue",
                r.status_code == 200
                and "arrivals_shift_pct" in r.json()["levers"]
                and r.json()["levers"]["arrivals_shift_pct"]["max_value"] == 40.0,
            )
        )
        r = client.post(
            f"{BASE}/scenarios/requests",
            json={
                "commodity": "wheat",
                "market": "indore",
                "text": "what if arrivals drop 10% and stock cover rises by 5 days?",
                "base_forecast_id": forecast_id,
            },
        )
        scenario_request = r.json() if r.status_code == 201 else {}
        checks.append(
            (
                "typed what-if parses into the bounded lever set",
                r.status_code == 201
                and [l["lever"] for l in scenario_request.get("levers", [])]
                == ["arrivals_shift_pct", "stock_cover_days"],
            )
        )
        r = client.post(
            f"{BASE}/scenarios/requests",
            json={
                "commodity": "wheat",
                "market": "indore",
                "text": "what if the monsoon fails completely?",
                "base_forecast_id": forecast_id,
            },
        )
        checks.append(
            (
                "an out-of-catalogue what-if is refused with its clause",
                r.status_code == 422
                and r.json()["detail"]["clause"] == "the monsoon fails completely",
            )
        )
        r = client.post(
            f"{BASE}/scenarios",
            json={
                "request_id": scenario_request.get("request_id"),
                "base_forecast_id": forecast_id,
                "author": "a.sharma",
                "created_on": "2026-01-03",
            },
        )
        scenario_view = r.json() if r.status_code == 201 else {}
        scenario_id = scenario_view.get("scenario_id")
        checks.append(
            (
                "scenario run is a labelled draft fork",
                r.status_code == 201
                and scenario_view.get("view_kind") == "scenario_draft"
                and scenario_view.get("base", {}).get("forecast_id") == forecast_id,
            )
        )
        r = client.get(f"{BASE}/scenarios/{scenario_id}/diff")
        diff_body = r.json() if r.status_code == 200 else {}
        checks.append(
            (
                "scenario diff sums to the P50 difference",
                r.status_code == 200
                and abs(
                    sum(diff_body.get("driver_totals", {}).values())
                    + diff_body.get("events_total", 0.0)
                    - diff_body.get("p50_total", 0.0)
                )
                < 0.005,
            )
        )
        r = client.get(f"{BASE}/scenarios/{scenario_id}/verify")
        checks.append(
            (
                "stored scenario re-performs clean",
                r.status_code == 200 and r.json()["problems"] == [],
            )
        )
        r = client.get(f"{BASE}/scenarios/adopted/wheat/indore")
        checks.append(
            (
                "no adopted view before the adoption act",
                r.status_code == 200 and r.json()["state"] == "none",
            )
        )
        r = client.post(
            f"{BASE}/scenarios/{scenario_id}/adopt",
            json={"adopter": "unknown", "role": "Head of Trading Desk"},
        )
        checks.append(("placeholder adopter refused", r.status_code == 422))
        r = client.post(
            f"{BASE}/scenarios/{scenario_id}/adopt",
            json={
                "adopter": "r.menon",
                "role": "Head of Trading Desk",
                "decided_on": "2026-01-04",
            },
        )
        checks.append(
            (
                "adoption act lands",
                r.status_code == 200 and r.json()["scenario_id"] == scenario_id,
            )
        )
        r = client.get(f"{BASE}/scenarios/adopted/wheat/indore")
        checks.append(
            (
                "adopted view reads as the adopted scenario",
                r.status_code == 200
                and r.json()["state"] == "adopted"
                and r.json()["scenario"]["view_kind"] == "adopted_scenario",
            )
        )
        r = client.post(
            f"{BASE}/scenarios/{scenario_id}/adopt",
            json={
                "adopter": "r.menon",
                "role": "Head of Trading Desk",
                "decided_on": "2026-01-05",
            },
        )
        checks.append(("re-adoption refused as a state error", r.status_code == 409))

        # --- R13: operator console -------------------------------------
        r = client.get(f"{BASE}/console/pack")
        checks.append(
            ("console pack served", r.status_code == 200 and r.json()["version"] == "2026.10.1")
        )
        r = client.post(
            f"{BASE}/console/preflights",
            json={"commodity": "coffee", "market": "bengaluru"},
        )
        preflight_body = r.json() if r.status_code == 201 else {}
        checks.append(
            (
                "coffee pre-flight names the catalogue gaps",
                r.status_code == 201
                and preflight_body.get("state") == "gapped"
                and any(
                    "does not report it" in g
                    for g in preflight_body.get("gaps", [])
                )
                and preflight_body.get("problems") == [],
            )
        )
        r = client.post(
            f"{BASE}/forecasts/run",
            json={"commodity": "coffee", "market": "bengaluru",
                  "preflight_id": preflight_body.get("report_id")},
        )
        checks.append(
            (
                "run-anyway pins the pre-flight gaps on the artefact",
                r.status_code == 200
                and r.json()["preflight"]["gaps"] == preflight_body.get("gaps"),
            )
        )
        r = client.post(
            f"{BASE}/forecasts/run",
            json={"commodity": "cumin", "market": "unjha", "as_of": "2025-12-18"},
        )
        cumin_id = r.json()["forecast_id"] if r.status_code == 200 else None
        r = client.post(
            f"{BASE}/forecasts/{cumin_id}/reject",
            json={"rejected_by": "d.kaur", "role": "desk_head",
                  "decided_on": "2026-01-03", "reason": "stale_inputs"},
        )
        checks.append(
            ("rejection act lands", r.status_code == 200 and r.json()["forecast_id"] == cumin_id)
        )
        r = client.post(
            f"{BASE}/forecasts/{cumin_id}/approve",
            json={"approver": "d.kaur", "role": "desk_head", "decided_on": "2026-01-04"},
        )
        checks.append(
            ("a rejected draft cannot be approved", r.status_code == 409 and "rejected" in r.json()["detail"])
        )
        r = client.post(
            f"{BASE}/market-events",
            json={
                "event_class": "tariff_change", "commodity": "soybean",
                "window_start": "2025-06-15", "window_end": "2025-07-15",
                "channel": "import_flow", "peak_log_price_effect": 0.60,
                "basis": "desk_estimate",
                "basis_detail": "A desk estimate, stated for the harness",
                "decay_days": 10,
                "description": "A claimed tariff step on oilseed imports",
                "declared_by": "a.sharma", "declared_on": "2025-06-10",
            },
        )
        forged_id = r.json()["event_id"] if r.status_code == 201 else None
        checks.append(("forged declaration registered", r.status_code == 201))
        r = client.post(
            f"{BASE}/forecasts/run",
            json={"commodity": "soybean", "market": "indore", "as_of": "2025-05-31"},
        )
        shocked13_id = r.json()["forecast_id"] if r.status_code == 200 else None
        checks.append(
            (
                "the unverified claim still contributes to the draft",
                r.status_code == 200 and forged_id in r.json()["method"]["events_applied"],
            )
        )
        r = client.post(
            f"{BASE}/forecasts/{shocked13_id}/approve",
            json={"approver": "d.kaur", "role": "desk_head", "decided_on": "2025-06-02"},
        )
        checks.append(
            ("triage gate refuses the approval", r.status_code == 409 and forged_id in r.json()["detail"])
        )
        r = client.post(
            f"{BASE}/market-events/{forged_id}/triage/confirm",
            json={"actor": "a.sharma", "role": "analyst",
                  "acted_on": "2025-06-02", "note": "circular checked"},
        )
        checks.append(("triage confirm act lands", r.status_code == 200))
        r = client.post(
            f"{BASE}/forecasts/{shocked13_id}/approve",
            json={"approver": "d.kaur", "role": "desk_head", "decided_on": "2025-06-02"},
        )
        checks.append(("approval stands after triage confirm", r.status_code == 200))
        r = client.get(f"{BASE}/console")
        checks.append(
            ("console view composes clean", r.status_code == 200 and r.json()["problems"] == [])
        )
        r = client.get(f"{BASE}/console/html")
        checks.append(("desktop console renders", r.status_code == 200 and "Operator console" in r.text))
        r = client.get(f"{BASE}/console/phone")
        checks.append(("phone console renders", r.status_code == 200 and "Desk inbox" in r.text))
        r = client.post(
            f"{BASE}/forecasts/run",
            json={"commodity": "wheat", "market": "indore", "as_of": "2025-12-22"},
        )
        phone_draft_id = r.json()["forecast_id"] if r.status_code == 200 else None
        r = client.post(
            f"{BASE}/console/actions",
            json={"kind": "approve_forecast", "forecast_id": phone_draft_id,
                  "approver": "d.kaur", "role": "desk_head",
                  "decided_on": "2026-01-05"},
        )
        checks.append(
            (
                "the phone's action door strikes the approval act",
                r.status_code == 200 and r.json()["forecast_id"] == phone_draft_id,
            )
        )
        r = client.get(f"{BASE}/console/review-queue")
        checks.append(
            (
                "the phone-approved draft leaves the review queue",
                r.status_code == 200
                and phone_draft_id
                not in [row["forecast_id"] for row in r.json()["rows"]],
            )
        )
        r = client.get(f"{BASE}/console/verify")
        checks.append(
            ("console re-performs clean", r.status_code == 200 and r.json()["problems"] == [])
        )
        # --- Round 14: geospatial basis & netting over HTTP ---------------
        r = client.get(f"{BASE}/geo/pack")
        checks.append(
            ("geo pack reads", r.status_code == 200 and r.json()["version"] == "2026.10.1")
        )
        r = client.post(
            f"{BASE}/geo/cost-lines",
            json={"commodity": "wheat", "market": "indore", "line": "freight",
                  "rate_paise_per_quintal": 45000, "entered_by": "a.rao",
                  "entered_on": "2025-12-30"},
        )
        checks.append(
            ("desk cost line lands with its provenance",
             r.status_code == 201 and r.json()["origin"] == "desk_entered")
        )
        r = client.post(
            f"{BASE}/geo/cost-lines",
            json={"commodity": "wheat", "market": "indore", "line": "insurance",
                  "rate_paise_per_quintal": 100, "entered_by": "a.rao",
                  "entered_on": "2025-12-30"},
        )
        checks.append(("an uncatalogued cost line is refused", r.status_code == 422))
        r = client.post(
            f"{BASE}/geo/basis-readings",
            json={"commodity": "wheat", "as_of": "2025-12-31"},
        )
        basis_rows = {row["market"]: row for row in r.json()["rows"]} if r.status_code == 201 else {}
        checks.append(
            (
                "basis reading strikes against the reference market",
                r.status_code == 201
                and basis_rows.get("delhi_khari_baoli", {}).get("classification") == "reference"
                and basis_rows.get("indore", {}).get("paired_days", 0) >= 60
                and r.json()["problems"] == [],
            )
        )
        r = client.post(
            f"{BASE}/geo/landed-comparisons",
            json={"commodity": "wheat", "as_of": "2025-12-31",
                  "priced_for": "verdanta_plant"},
        )
        landed_rows = {row["market"]: row for row in r.json()["rows"]} if r.status_code == 201 else {}
        checks.append(
            (
                "landed names the missing handling line",
                r.status_code == 201
                and landed_rows.get("indore", {}).get("state") == "not_computable"
                and landed_rows.get("indore", {}).get("missing_lines") == ["handling"]
                and landed_rows.get("indore", {}).get("landed_paise") is None,
            )
        )
        r = client.get(f"{BASE}/market-events")
        tariff_id = next(
            (
                e["event_id"] for e in r.json()["events"]
                if e.get("source_record_id") == "EVT-2025-TARIFF-SOYBEAN"
            ),
            None,
        )
        r = client.post(
            f"{BASE}/geo/maps",
            json={"commodity": "soybean", "as_of": "2025-06-20"},
        )
        map_id = r.json()["map_id"] if r.status_code == 201 else None
        checks.append(
            (
                "the map inside the tariff window carries the event overlay",
                r.status_code == 201
                and tariff_id
                in [e["event_id"] for e in r.json()["active_events"]]
                and r.json()["problems"] == [],
            )
        )
        r = client.get(f"{BASE}/geo/maps/{map_id}/html")
        checks.append(
            ("the map page renders its markets",
             r.status_code == 200 and "Indore" in r.text and "Nagpur" in r.text)
        )
        r = client.get(f"{BASE}/geo/verify")
        checks.append(
            ("geo layer re-performs clean", r.status_code == 200 and r.json()["problems"] == [])
        )
        # --- Round 15: desk policy, approvals, config over HTTP -----------
        r = client.get(f"{BASE}/desk/pack")
        standing_pack = r.json()["pack"] if r.status_code == 200 else {}
        checks.append(
            ("the standing desk pack reads",
             r.status_code == 200 and r.json()["label"] == "2026.10.1")
        )
        new_pack = dict(standing_pack)
        new_pack["version"] = "2026.11.1"
        new_pack["exposure_threshold_inr"] = 1000000.0
        r = client.post(
            f"{BASE}/desk/policy-versions",
            json={"label": "2026.11.1", "pack": new_pack,
                  "proposed_by": "a.sharma", "proposed_on": "2026-01-02"},
        )
        version_id = r.json()["version_id"] if r.status_code == 201 else None
        checks.append(
            (
                "a pack proposal lands proposed, not standing",
                r.status_code == 201
                and r.json()["status"] == "proposed"
                and [d["field"] for d in r.json()["diff"]]
                == ["exposure_threshold_inr"]
                and r.json()["problems"] == [],
            )
        )
        r = client.post(
            f"{BASE}/desk/decisions",
            json={"kind": "pack_change", "target_id": version_id,
                  "opened_by": "a.sharma", "opened_on": "2026-01-02",
                  "purpose": "tighten the exposure bar"},
        )
        decision_id = r.json()["decision_id"] if r.status_code == 201 else None
        checks.append(
            (
                "the pack change resolves its two-person chain",
                r.status_code == 201
                and [s["step"] for s in r.json()["steps"]]
                == ["review", "sign_off"],
            )
        )
        r = client.post(
            f"{BASE}/desk/decisions/{decision_id}/acts",
            json={"actor": "a.sharma", "role": "analyst",
                  "outcome": "approve", "decided_on": "2026-01-03"},
        )
        checks.append(("the proposer cannot act on their own change", r.status_code == 422))
        r = client.post(
            f"{BASE}/desk/decisions/{decision_id}/acts",
            json={"actor": "m.iyer", "role": "analyst",
                  "outcome": "approve", "decided_on": "2026-01-03"},
        )
        checks.append(
            ("the review act lands and the decision stays open",
             r.status_code == 201 and r.json()["state"] == "in_progress")
        )
        r = client.post(
            f"{BASE}/desk/decisions/{decision_id}/acts",
            json={"actor": "d.kaur", "role": "desk_head",
                  "outcome": "approve", "decided_on": "2026-01-04"},
        )
        checks.append(
            ("the sign-off completes the chain",
             r.status_code == 201 and r.json()["state"] == "approved")
        )
        r = client.get(f"{BASE}/desk/pack")
        checks.append(
            ("the approved version now stands",
             r.status_code == 200 and r.json()["label"] == "2026.11.1")
        )
        r = client.post(
            f"{BASE}/desk/decision-logs", json={"struck_on": "2026-01-31"},
        )
        checks.append(
            (
                "the decision log folds both acts, gapless",
                r.status_code == 201
                and [e["seq"] for e in r.json()["entries"]] == [1, 2]
                and r.json()["problems"] == [],
            )
        )
        r = client.post(
            f"{BASE}/desk/comments",
            json={"target_kind": "forecast", "target_id": forecast_id,
                  "author": "m.iyer",
                  "text": "check the arrivals figure with the market contact",
                  "commented_on": "2026-01-03"},
        )
        checks.append(
            ("a comment pins to the forecast",
             r.status_code == 201 and r.json()["target_id"] == forecast_id)
        )
        r = client.post(
            f"{BASE}/desk/tasks",
            json={"target_kind": "forecast", "target_id": forecast_id,
                  "title": "confirm the indore arrivals",
                  "opened_by": "d.kaur", "assignee": "m.iyer",
                  "opened_on": "2026-01-03"},
        )
        task_id = r.json()["task_id"] if r.status_code == 201 else None
        r = client.post(
            f"{BASE}/desk/tasks/{task_id}/acts",
            json={"action": "close", "actor": "m.iyer", "acted_on": "2026-01-05"},
        )
        checks.append(
            ("the follow-up task closes through its act",
             r.status_code == 201 and r.json()["state"] == "closed")
        )
        r = client.get(f"{BASE}/desk/verify")
        checks.append(
            ("desk layer re-performs clean", r.status_code == 200 and r.json()["problems"] == [])
        )
        # --- Round 16: identity, scopes, audit, master data over HTTP -----
        r = client.get(f"{BASE}/access/pack")
        checks.append(
            ("the access pack reads",
             r.status_code == 200 and r.json()["version"] == "2026.10.1")
        )
        r = client.post(
            f"{BASE}/access/grants",
            json={"subject": "d.kaur", "role": "desk_head",
                  "granted_by": "d.kaur", "granted_on": "2026-01-02"},
        )
        checks.append(
            ("the bootstrap grant lands flagged",
             r.status_code == 201 and r.json()["bootstrap"] is True)
        )
        r = client.post(
            f"{BASE}/access/grants",
            json={"subject": "a.sharma", "role": "trader",
                  "markets": ["indore"], "granted_by": "d.kaur",
                  "granted_on": "2026-01-02"},
        )
        checks.append(
            ("a scoped trader grant lands",
             r.status_code == 201 and r.json()["markets"] == ["indore"])
        )
        r = client.get(
            f"{BASE}/forecasts/{forecast_id}",
            headers={"x-desk-actor": "a.sharma"},
        )
        checks.append(
            ("an in-scope governed read is served", r.status_code == 200)
        )
        r = client.get(
            f"{BASE}/forecasts/{groundnut_id}",
            headers={"x-desk-actor": "a.sharma"},
        )
        checks.append(
            ("an out-of-scope governed read hides as a missing forecast",
             r.status_code == 404
             and r.json() == {"detail": f"unknown forecast {groundnut_id}"})
        )
        r = client.get(f"{BASE}/forecasts/{groundnut_id}")
        checks.append(
            ("an unnamed read keeps the local posture", r.status_code == 200)
        )
        r = client.get(f"{BASE}/access/entries")
        checks.append(
            ("the governed reads are on the audit record",
             r.status_code == 200
             and [e["outcome"] for e in r.json()["entries"]]
             == ["allowed", "hidden_out_of_scope"])
        )
        r = client.post(
            f"{BASE}/access/logs", json={"struck_on": "2026-01-31"}
        )
        checks.append(
            ("the audit log folds gaplessly",
             r.status_code == 201
             and [line["seq"] for line in r.json()["entries"]] == [1, 2]
             and r.json()["upto_seq"] == 2)
        )
        r = client.get(f"{BASE}/access/verify")
        checks.append(
            ("access layer re-performs clean", r.status_code == 200 and r.json()["problems"] == [])
        )
        r = client.get(f"{BASE}/masterdata")
        md_state = r.json()["state"] if r.status_code == 200 else {}
        for calendar in md_state.get("calendars", []):
            if calendar["market"] == "kanpur":
                calendar["holidays"] = ["2025-12-25"]
        r = client.post(
            f"{BASE}/masterdata/versions",
            json={"label": "christmas-closure", "state": md_state,
                  "edited_by": "a.sharma", "edited_on": "2026-01-02"},
        )
        checks.append(
            ("a trader's master data strike is refused",
             r.status_code == 422)
        )
        r = client.post(
            f"{BASE}/masterdata/versions",
            json={"label": "christmas-closure", "state": md_state,
                  "edited_by": "d.kaur", "edited_on": "2026-01-02"},
        )
        md_version_id = r.json()["version_id"] if r.status_code == 201 else None
        checks.append(
            ("the desk head's master data version lands with its diff",
             r.status_code == 201
             and [d["field"] for d in r.json()["diff"]]
             == ["calendars.kanpur.holidays"])
        )
        r = client.get(
            f"{BASE}/masterdata/coverage/wheat/kanpur",
            params={"as_of": "2025-12-31", "version_id": md_version_id},
        )
        checks.append(
            ("the holiday re-derives coverage for its windows only",
             r.status_code == 200
             and all(
                 w["verdict_changed"]
                 and [c["date"] for c in w["changed_operating_dates"]]
                 == ["2025-12-25"]
                 for w in r.json()["windows"]
             ))
        )
        r = client.get(f"{BASE}/masterdata/verify")
        checks.append(
            ("master data layer re-performs clean", r.status_code == 200 and r.json()["problems"] == [])
        )
        for name, ok in checks:
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        return 0 if all(ok for _, ok in checks) else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
