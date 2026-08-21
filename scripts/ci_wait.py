#!/usr/bin/env python3
"""Poll a GitHub Actions run until it completes, then summarize job results.

Usage:
    python scripts/ci_wait.py <run_id> [--interval 20] [--max-polls 36]

Requires network; works for public repos without authentication.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request

BASE = "https://api.github.com/repos/RayJoeMan/VideoAssistantXbotGo/actions/runs"


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--interval", type=int, default=20)
    parser.add_argument("--max-polls", type=int, default=36)
    args = parser.parse_args()

    run_url = f"{BASE}/{args.run_id}"
    for i in range(args.max_polls):
        run = get(run_url)
        status = run["status"]
        conclusion = run.get("conclusion")
        print(f"[ci_wait] poll {i + 1}: {status} conclusion={conclusion}", flush=True)
        if status == "completed":
            print("[ci_wait] --- job results ---", flush=True)
            jobs = get(f"{run_url}/jobs")
            for j in jobs["jobs"]:
                print(f"[ci_wait] {j['name']}: {j.get('conclusion')}", flush=True)
                for s in j["steps"]:
                    c = s.get("conclusion") or s["status"]
                    if c not in ("success", "skipped"):
                        print(
                            f"[ci_wait]   step {s['number']} {s['name']}: {c}",
                            flush=True,
                        )
            print(f"[ci_wait] FINAL: {conclusion}", flush=True)
            return 0 if conclusion == "success" else 1
        time.sleep(args.interval)
    print("[ci_wait] timed out waiting for completion", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
