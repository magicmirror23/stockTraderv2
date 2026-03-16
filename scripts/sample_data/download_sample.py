#!/usr/bin/env python
"""Download 1 year of OHLCV data for the 50 NSE tickers listed in tickers.txt.

Usage
-----
    python scripts/sample_data/download_sample.py

Output is written to ``storage/raw/``.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ensure repo root is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.prediction_engine.data_pipeline.connector_yahoo import YahooConnector  # noqa: E402
from backend.prediction_engine.data_pipeline.validation import validate_directory  # noqa: E402

TICKERS_FILE = Path(__file__).with_name("tickers.txt")
OUTPUT_DIR = REPO_ROOT / "storage" / "raw"


def load_tickers() -> list[str]:
    return [
        line.strip()
        for line in TICKERS_FILE.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def main() -> None:
    tickers = load_tickers()
    print(f"Downloading data for {len(tickers)} tickers → {OUTPUT_DIR}")

    end = datetime.now()
    start = end - timedelta(days=365)

    connector = YahooConnector()
    failed: list[str] = []

    for i, ticker in enumerate(tickers, 1):
        try:
            path = connector.fetch_to_csv(ticker, start, end, OUTPUT_DIR)
            print(f"  [{i}/{len(tickers)}] {ticker} → {path}")
        except Exception as exc:
            print(f"  [{i}/{len(tickers)}] {ticker} FAILED: {exc}")
            failed.append(ticker)

    if failed:
        print(f"\n⚠  Failed tickers ({len(failed)}): {', '.join(failed)}")

    # Validate
    print("\nValidating downloaded data…")
    errors = validate_directory(OUTPUT_DIR)
    if errors:
        for err in errors:
            print(f"  ERROR: {err}", file=sys.stderr)
        sys.exit(1)
    else:
        print("All files valid ✓")


if __name__ == "__main__":
    main()
