"""Local harness: boot the real API server and exercise it over HTTP.

Loads the dataset into a throwaway database, starts uvicorn on a
local port, and checks /health, /readiness, /manifest, /events and
a /series read — the same contract a desk client would use.
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
