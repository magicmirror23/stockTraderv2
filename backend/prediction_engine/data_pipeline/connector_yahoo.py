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
    SYMBOL_ALIASES = {
        "BAJAJ_AUTO": ["BAJAJ-AUTO.NS"],
        "M_M": ["M&M.NS"],
        "TATAMOTORS": ["TATAMOTORS.NS", "500570.BO"],
        "VARUNBEV": ["VBL.NS", "VARUNBEV.NS"],
        "NIFTY50": ["^NSEI"],
        "BANKNIFTY": ["^NSEBANK"],
        "INDIAVIX": ["^INDIAVIX"],
        "USDINR": ["INR=X"],
        "BRENT": ["BZ=F"],
        "GOLD": ["GC=F"],
        "SP500": ["^GSPC"],
        "US10Y": ["^TNX"],
    }

    def __init__(self, nse_suffix: str = ".NS") -> None:
        self._suffix = nse_suffix

    def _yahoo_tickers(self, ticker: str) -> list[str]:
        """Return candidate Yahoo symbols for a logical ticker."""
        normalized = ticker.strip().upper()
        if normalized in self.SYMBOL_ALIASES:
            return self.SYMBOL_ALIASES[normalized]
        if normalized.startswith("^") or "=" in normalized or normalized.endswith(self._suffix):
            return [normalized]
        return [f"{normalized}{self._suffix}"]

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

        # Convert to date-only strings to avoid yfinance datetime parsing errors
        start_str = start.strftime("%Y-%m-%d") if isinstance(start, datetime) else str(start).split(" ")[0]
        end_str = end.strftime("%Y-%m-%d") if isinstance(end, datetime) else str(end).split(" ")[0]
        last_error: Exception | None = None

        for yahoo_sym in self._yahoo_tickers(ticker):
            logger.info("Fetching %s (%s) from %s to %s", ticker, yahoo_sym, start, end)
            try:
                df = yf.download(
                    yahoo_sym,
                    start=start_str,
                    end=end_str,
                    progress=False,
                    auto_adjust=True,
                    threads=False,
                )
            except Exception as exc:
                last_error = exc
                logger.warning("Yahoo download failed for %s via %s: %s", ticker, yahoo_sym, exc)
                continue

            if df.empty:
                logger.warning("No data returned for %s via %s", ticker, yahoo_sym)
                continue

            # Flatten MultiIndex columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = df.reset_index()
            df = df.rename(columns={"index": "Date"} if "Date" not in df.columns else {})
            missing = [column for column in self.REQUIRED_COLUMNS if column not in df.columns]
            if missing:
                logger.warning("Yahoo response missing columns for %s via %s: %s", ticker, yahoo_sym, missing)
                continue
            return df[["Date"] + self.REQUIRED_COLUMNS]

        if last_error is not None:
            logger.warning("All Yahoo symbol candidates failed for %s: %s", ticker, last_error)
        else:
            logger.warning("No data returned for %s", ticker)
        return pd.DataFrame(columns=["Date"] + self.REQUIRED_COLUMNS)

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
