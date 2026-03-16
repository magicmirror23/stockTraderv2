#!/usr/bin/env python
"""Smoke test for deployed API.

Usage
-----
    python scripts/smoke_test.py [BASE_URL]
"""

from __future__ import annotations

import sys

import requests

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"


def check(name: str, response: requests.Response, expected_status: int = 200):
    ok = response.status_code == expected_status
    symbol = "PASS" if ok else "FAIL"
    print(f"  [{symbol}] {name} → {response.status_code}")
    if not ok:
        print(f"         Body: {response.text[:200]}")
    return ok


def main():
    print(f"Smoke testing {BASE_URL} …\n")
    all_ok = True

    # Health
    try:
        r = requests.get(f"{BASE_URL}/api/v1/health", timeout=10)
        if not check("GET /health", r):
            all_ok = False
        elif r.json().get("status") != "ok":
            print("    FAIL: unexpected body")
            all_ok = False
    except requests.ConnectionError:
        print("  [FAIL] Cannot connect to API")
        sys.exit(1)

    # Model status
    r = requests.get(f"{BASE_URL}/api/v1/model/status", timeout=10)
    check("GET /model/status", r)

    # Metrics (Prometheus)
    r = requests.get(f"{BASE_URL}/api/v1/metrics", timeout=10)
    check("GET /metrics", r)

    print()
    if all_ok:
        print("All smoke tests passed ✓")
    else:
        print("Some smoke tests FAILED ✗")
        sys.exit(1)


if __name__ == "__main__":
    main()
