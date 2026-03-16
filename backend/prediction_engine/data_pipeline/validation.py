"""Data validation utilities for raw OHLCV files.

Provides schema checks, missing-value detection, anomaly detection,
checksums, data lineage/provenance, and time-alignment helpers.
Can be run as a standalone script (``python -m backend.prediction_engine.data_pipeline.validation``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"Date", "Open", "High", "Low", "Close", "Volume"}
MIN_ROWS = 50

# Anomaly detection thresholds
MAX_DAILY_PRICE_CHANGE_PCT = 20.0  # flag >20% daily moves
MIN_VOLUME_THRESHOLD = 1  # flag zero-volume days


def validate_csv(path: Path) -> list[str]:
    """Return a list of error strings for a single CSV file.

    An empty list means the file is valid.
    """
    errors: list[str] = []

    if not path.exists():
        errors.append(f"File not found: {path}")
        return errors

    try:
        df = pd.read_csv(path)
    except Exception as exc:
        errors.append(f"Cannot parse {path.name}: {exc}")
        return errors

    # --- Column checks ---
    missing_cols = REQUIRED_COLUMNS - set(df.columns)
    if missing_cols:
        errors.append(f"{path.name}: missing columns {missing_cols}")
        return errors  # can't do further checks

    # --- Row count ---
    if len(df) < MIN_ROWS:
        errors.append(
            f"{path.name}: only {len(df)} rows (expected >= {MIN_ROWS})"
        )

    # --- Null checks ---
    null_counts = df[list(REQUIRED_COLUMNS)].isnull().sum()
    cols_with_nulls = null_counts[null_counts > 0]
    if not cols_with_nulls.empty:
        errors.append(
            f"{path.name}: nulls in {dict(cols_with_nulls)}"
        )

    # --- Numeric checks ---
    for col in ("Open", "High", "Low", "Close"):
        if not pd.api.types.is_numeric_dtype(df[col]):
            errors.append(f"{path.name}: column {col} is not numeric")

    # --- Negative prices ---
    for col in ("Open", "High", "Low", "Close"):
        if pd.api.types.is_numeric_dtype(df[col]) and (df[col] < 0).any():
            errors.append(f"{path.name}: negative values in {col}")

    # --- Date parseable ---
    try:
        pd.to_datetime(df["Date"])
    except Exception:
        errors.append(f"{path.name}: 'Date' column is not parseable as datetime")

    return errors


def validate_directory(data_dir: str | Path) -> list[str]:
    """Validate every CSV in *data_dir*. Returns aggregated errors."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        return [f"Directory does not exist: {data_dir}"]

    csv_files = sorted(data_dir.glob("*.csv"))
    if not csv_files:
        return [f"No CSV files found in {data_dir}"]

    all_errors: list[str] = []
    for csv_path in csv_files:
        all_errors.extend(validate_csv(csv_path))

    return all_errors


def align_dates(
    frames: dict[str, pd.DataFrame],
    date_col: str = "Date",
) -> dict[str, pd.DataFrame]:
    """Align multiple ticker DataFrames to a common date index.

    Drops dates that are not present in *all* DataFrames (inner join).
    """
    if not frames:
        return {}

    common_dates: set | None = None
    for df in frames.values():
        dates = set(pd.to_datetime(df[date_col]))
        common_dates = dates if common_dates is None else common_dates & dates

    aligned: dict[str, pd.DataFrame] = {}
    for ticker, df in frames.items():
        df = df.copy()
        df[date_col] = pd.to_datetime(df[date_col])
        aligned[ticker] = (
            df[df[date_col].isin(common_dates)]
            .sort_values(date_col)
            .reset_index(drop=True)
        )

    return aligned


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------


def detect_anomalies(df: pd.DataFrame, ticker: str = "") -> list[str]:
    """Detect data anomalies: price jumps, zero volume, repeated ticks."""
    warnings: list[str] = []
    prefix = f"{ticker}: " if ticker else ""

    if "Close" not in df.columns:
        return warnings

    # Large price jumps
    pct_change = df["Close"].pct_change().abs() * 100
    large_moves = pct_change[pct_change > MAX_DAILY_PRICE_CHANGE_PCT]
    if not large_moves.empty:
        warnings.append(
            f"{prefix}{len(large_moves)} days with >{MAX_DAILY_PRICE_CHANGE_PCT}% price change"
        )

    # Zero volume
    if "Volume" in df.columns:
        zero_vol = (df["Volume"] < MIN_VOLUME_THRESHOLD).sum()
        if zero_vol > 0:
            warnings.append(f"{prefix}{zero_vol} days with zero volume")

    # Repeated identical ticks (same OHLCV for consecutive days)
    if len(df) > 1:
        cols = ["Open", "High", "Low", "Close", "Volume"]
        available = [c for c in cols if c in df.columns]
        dupes = df[available].diff().abs().sum(axis=1)
        repeated = (dupes == 0).sum() - 1  # first row always 0
        if repeated > 3:
            warnings.append(f"{prefix}{repeated} consecutive duplicate rows")

    return warnings


# ---------------------------------------------------------------------------
# Checksums and provenance
# ---------------------------------------------------------------------------


def compute_file_checksum(path: Path) -> str:
    """Compute SHA-256 checksum for a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def write_provenance_log(
    data_dir: Path,
    ticker: str,
    source: str,
    start: str,
    end: str,
    row_count: int,
    checksum: str,
) -> Path:
    """Write a provenance JSON alongside a data file."""
    log_path = data_dir / f"{ticker}.provenance.json"
    record = {
        "ticker": ticker,
        "source": source,
        "download_timestamp": datetime.now(timezone.utc).isoformat(),
        "start_date": start,
        "end_date": end,
        "row_count": row_count,
        "sha256": checksum,
    }
    with open(log_path, "w") as f:
        json.dump(record, f, indent=2)
    return log_path


def validate_provenance(data_dir: Path) -> list[str]:
    """Verify checksums in provenance logs match actual files."""
    errors: list[str] = []
    for prov_file in sorted(data_dir.glob("*.provenance.json")):
        with open(prov_file) as f:
            prov = json.load(f)
        csv_path = data_dir / f"{prov['ticker']}.csv"
        if not csv_path.exists():
            errors.append(f"Provenance references missing file: {csv_path.name}")
            continue
        actual = compute_file_checksum(csv_path)
        if actual != prov.get("sha256"):
            errors.append(
                f"{csv_path.name}: checksum mismatch (file modified since download)"
            )
    return errors


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate raw OHLCV CSVs")
    parser.add_argument(
        "data_dir",
        nargs="?",
        default="storage/raw",
        help="Directory containing CSV files to validate",
    )
    args = parser.parse_args()

    errors = validate_directory(args.data_dir)
    if errors:
        for err in errors:
            logger.error(err)
            print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)
    else:
        print("All files valid ✓")
        sys.exit(0)
