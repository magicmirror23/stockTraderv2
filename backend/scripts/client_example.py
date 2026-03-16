#!/usr/bin/env python
"""Example client script showing how a trading bot calls /predict.

Usage
-----
    python backend/scripts/client_example.py
"""

from __future__ import annotations

import requests

BASE_URL = "http://localhost:8000/api/v1"


def predict(ticker: str, horizon: int = 5) -> dict:
    resp = requests.post(
        f"{BASE_URL}/predict",
        json={"ticker": ticker, "horizon_days": horizon},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def map_to_order_intent(prediction: dict) -> dict | None:
    """Convert a prediction response to a trade order intent."""
    entry = prediction["prediction"]
    action = entry["action"]

    if action == "hold":
        return None

    return {
        "ticker": entry["ticker"],
        "side": "buy" if action == "buy" else "sell",
        "quantity": 10,  # placeholder fixed size
        "order_type": "market",
    }


def main():
    tickers = ["RELIANCE", "TCS", "INFY"]

    for ticker in tickers:
        print(f"\n--- {ticker} ---")
        try:
            result = predict(ticker)
            print(f"  Prediction: {result['prediction']['action']} "
                  f"(confidence={result['prediction']['confidence']})")
            intent = map_to_order_intent(result)
            if intent:
                print(f"  Order intent: {intent}")
            else:
                print("  No trade (hold)")
        except requests.RequestException as exc:
            print(f"  Error: {exc}")


if __name__ == "__main__":
    main()
