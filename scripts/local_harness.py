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
