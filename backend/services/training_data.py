"""Training data refresh helpers for admin-triggered model retraining."""

from __future__ import annotations

import logging
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from backend.core.config import settings
from backend.prediction_engine.data_pipeline.connector_yahoo import YahooConnector


logger = logging.getLogger(__name__)
RefreshProgressCallback = Callable[[int, int, str], None]


@dataclass
class TrainingDataRefreshReport:
    tickers: list[str]
    downloaded: list[str]
    refreshed: list[str]
    reused: list[str]
    deleted: list[str]
    failed: dict[str, str]
    start_date: str
    end_date: str
    data_dir: str

    def to_dict(self) -> dict:
        return asdict(self)


def load_training_tickers(tickers: list[str] | None = None) -> list[str]:
    """Resolve the training ticker universe from args or the configured file."""
    if tickers:
        return [ticker.strip().upper() for ticker in tickers if ticker.strip()]

    ticker_file = settings.training_tickers_file
    if not ticker_file.exists():
        raise FileNotFoundError(f"Training ticker file not found at {ticker_file}")

    return [line.strip().upper() for line in ticker_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def ensure_training_data(
    tickers: list[str] | None = None,
    data_dir: str | Path | None = None,
    lookback_days: int | None = None,
    max_age_days: int | None = None,
    progress_callback: RefreshProgressCallback | None = None,
) -> TrainingDataRefreshReport:
    """Refresh missing or stale training CSV files before model training."""
    resolved_tickers = load_training_tickers(tickers)
    output_dir = Path(data_dir) if data_dir is not None else settings.raw_data_path
    output_dir.mkdir(parents=True, exist_ok=True)

    lookback = lookback_days if lookback_days is not None else settings.TRAINING_DATA_LOOKBACK_DAYS
    max_age = max_age_days if max_age_days is not None else settings.TRAINING_DATA_MAX_AGE_DAYS

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=lookback)
    connector = YahooConnector()

    report = TrainingDataRefreshReport(
        tickers=resolved_tickers,
        downloaded=[],
        refreshed=[],
        reused=[],
        deleted=[],
        failed={},
        start_date=start_dt.date().isoformat(),
        end_date=end_dt.date().isoformat(),
        data_dir=str(output_dir),
    )

    valid_names = {f"{ticker}.csv" for ticker in resolved_tickers}
    total = len(resolved_tickers)
    if progress_callback and total > 0:
        progress_callback(0, total, "Checking training CSV cache")
    for stale_path in output_dir.glob("*.csv"):
        if stale_path.name not in valid_names:
            stale_path.unlink(missing_ok=True)
            report.deleted.append(stale_path.stem.upper())
            logger.info("Deleted stale training CSV not in ticker list: %s", stale_path.name)

    for index, ticker in enumerate(resolved_tickers, start=1):
        path = output_dir / f"{ticker}.csv"
        needs_refresh = not path.exists()
        reason = "missing"

        if path.exists():
            is_fresh, freshness_reason = _is_csv_fresh(path, max_age_days=max_age)
            needs_refresh = not is_fresh
            reason = freshness_reason

        if not needs_refresh:
            report.reused.append(ticker)
            continue

        try:
            refreshed = _download_to_temp(
                connector=connector,
                ticker=ticker,
                start_dt=start_dt,
                end_dt=end_dt,
                output_dir=output_dir,
            )
            if path.exists():
                backup_path = path.with_suffix(".csv.bak")
                shutil.copy2(path, backup_path)
                try:
                    path.unlink(missing_ok=True)
                    refreshed.replace(path)
                    backup_path.unlink(missing_ok=True)
                    report.deleted.append(ticker)
                except Exception:
                    if not path.exists() and backup_path.exists():
                        backup_path.replace(path)
                    refreshed.unlink(missing_ok=True)
                    raise
            else:
                refreshed.replace(path)
            if reason == "missing":
                report.downloaded.append(ticker)
            else:
                report.refreshed.append(ticker)
            logger.info("Fetched fresh training CSV for %s", ticker)
        except Exception as exc:
            report.failed[ticker] = str(exc)
            logger.warning("Failed to refresh training CSV for %s: %s", ticker, exc)
            if path.exists():
                report.reused.append(ticker)
        finally:
            if progress_callback:
                progress_callback(index, total, f"Processed training data for {ticker}")

    if report.failed and len(report.failed) == len(resolved_tickers):
        raise RuntimeError("Unable to refresh any training CSV files")

    return report


def _download_to_temp(
    connector: YahooConnector,
    ticker: str,
    start_dt: datetime,
    end_dt: datetime,
    output_dir: Path,
) -> Path:
    temp_dir = output_dir / ".refresh_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = connector.fetch_to_csv(ticker, start_dt, end_dt, temp_dir)
    is_fresh, freshness_reason = _is_csv_fresh(temp_path, max_age_days=max(settings.TRAINING_DATA_MAX_AGE_DAYS, 1_000))
    if not is_fresh and freshness_reason in {"empty", "invalid_dates", "missing_columns", "unreadable"}:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"downloaded_csv_invalid:{freshness_reason}")
    return temp_path


def _is_csv_fresh(path: Path, max_age_days: int) -> tuple[bool, str]:
    """Check file freshness by modified time and by the last row's date."""
    max_age_delta = timedelta(days=max_age_days)
    now = datetime.now(timezone.utc)
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    if now - modified_at > max_age_delta:
        return False, "file_age"

    try:
        frame = pd.read_csv(path, parse_dates=["Date"])
    except Exception:
        return False, "unreadable"

    if frame.empty:
        return False, "empty"

    last_date = pd.Timestamp(frame["Date"].max())
    if pd.isna(last_date):
        return False, "invalid_dates"

    if last_date.tzinfo is None:
        last_date = last_date.tz_localize(timezone.utc)
    else:
        last_date = last_date.tz_convert(timezone.utc)

    if now - last_date.to_pydatetime() > max_age_delta:
        return False, "data_end_date"

    required_columns = {"Date", "Open", "High", "Low", "Close", "Volume"}
    if not required_columns.issubset(frame.columns):
        return False, "missing_columns"

    return True, "fresh"
