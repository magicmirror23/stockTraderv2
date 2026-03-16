"""Yahoo Finance data connector using yfinance.

Provides OHLCV data for NSE tickers by appending the `.NS` suffix
expected by Yahoo Finance.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
except ImportError:
    yf = None
    logger.warning("yfinance not installed – YahooConnector will not work")


class YahooConnector:
    """Fetches OHLCV data from Yahoo Finance."""

    REQUIRED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

    def __init__(self, nse_suffix: str = ".NS") -> None:
        self._suffix = nse_suffix

    def _yahoo_ticker(self, ticker: str) -> str:
        """Append exchange suffix if not already present."""
        if not ticker.endswith(self._suffix):
            return f"{ticker}{self._suffix}"
        return ticker

    def fetch(
        self,
        ticker: str,
        start: str | datetime,
        end: str | datetime,
    ) -> pd.DataFrame:
        """Download OHLCV data for a single ticker.

        Parameters
        ----------
        ticker : str
            NSE ticker symbol (e.g. ``RELIANCE``).
        start, end : str or datetime
            Date range (inclusive).

        Returns
        -------
        pd.DataFrame
            DataFrame with columns Date, Open, High, Low, Close, Volume.
        """
        if yf is None:
            raise RuntimeError("yfinance is not installed")

        yahoo_sym = self._yahoo_ticker(ticker)
        logger.info("Fetching %s (%s) from %s to %s", ticker, yahoo_sym, start, end)

        # Convert to date-only strings to avoid yfinance datetime parsing errors
        start_str = start.strftime("%Y-%m-%d") if isinstance(start, datetime) else str(start).split(" ")[0]
        end_str = end.strftime("%Y-%m-%d") if isinstance(end, datetime) else str(end).split(" ")[0]

        df = yf.download(yahoo_sym, start=start_str, end=end_str, progress=False, auto_adjust=True)

        if df.empty:
            logger.warning("No data returned for %s", ticker)
            return pd.DataFrame(columns=["Date"] + self.REQUIRED_COLUMNS)

        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.reset_index()
        df = df.rename(columns={"index": "Date"} if "Date" not in df.columns else {})
        return df[["Date"] + self.REQUIRED_COLUMNS]

    def fetch_to_csv(
        self,
        ticker: str,
        start: str | datetime,
        end: str | datetime,
        output_dir: str | Path,
    ) -> Path:
        """Fetch data and persist as CSV.

        Returns the path of the written file.
        """
        df = self.fetch(ticker, start, end)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{ticker}.csv"
        df.to_csv(path, index=False)
        logger.info("Saved %d rows → %s", len(df), path)
        return path
