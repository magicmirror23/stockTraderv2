"""Tests for data pipeline validation utilities."""

from pathlib import Path

import pandas as pd

from backend.prediction_engine.data_pipeline.validation import (
    validate_csv,
    validate_directory,
    align_dates,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_validate_csv_valid():
    errors = validate_csv(FIXTURES_DIR / "sample_ohlcv.csv")
    assert errors == []


def test_validate_csv_missing_file():
    errors = validate_csv(FIXTURES_DIR / "nonexistent.csv")
    assert any("not found" in e.lower() for e in errors)


def test_validate_directory_valid():
    errors = validate_directory(FIXTURES_DIR)
    assert errors == []


def test_align_dates():
    dates_a = pd.date_range("2025-01-01", periods=5, freq="B")
    dates_b = pd.date_range("2025-01-02", periods=5, freq="B")

    df_a = pd.DataFrame({
        "Date": dates_a,
        "Open": range(5),
        "High": range(5),
        "Low": range(5),
        "Close": range(5),
        "Volume": range(5),
    })
    df_b = pd.DataFrame({
        "Date": dates_b,
        "Open": range(5),
        "High": range(5),
        "Low": range(5),
        "Close": range(5),
        "Volume": range(5),
    })

    aligned = align_dates({"A": df_a, "B": df_b})
    assert len(aligned["A"]) == len(aligned["B"])
    assert set(aligned["A"]["Date"]) == set(aligned["B"]["Date"])
