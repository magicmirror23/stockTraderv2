"""Implied Volatility and option chain data connector.

Fetches option chains, IV surfaces, and historical option prices
using yfinance as the data backend.
"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
except ImportError:
    yf = None


class IVConnector:
    """Fetches option chains and implied volatility data."""

    def __init__(self, nse_suffix: str = ".NS") -> None:
        self._suffix = nse_suffix

    def _yahoo_ticker(self, ticker: str) -> str:
        if not ticker.endswith(self._suffix):
            return f"{ticker}{self._suffix}"
        return ticker

    def fetch_option_chain(self, ticker: str, expiry: str | None = None) -> dict[str, pd.DataFrame]:
        """Fetch current option chain for a ticker.

        Returns dict with keys 'calls' and 'puts', each a DataFrame.
        """
        if yf is None:
            raise RuntimeError("yfinance is not installed")

        sym = yf.Ticker(self._yahoo_ticker(ticker))
        try:
            if expiry:
                chain = sym.option_chain(expiry)
            else:
                chain = sym.option_chain()
        except Exception as exc:
            logger.warning("Failed to fetch option chain for %s: %s", ticker, exc)
            return {"calls": pd.DataFrame(), "puts": pd.DataFrame()}

        return {"calls": chain.calls, "puts": chain.puts}

    def fetch_expiry_dates(self, ticker: str) -> list[str]:
        """Return available option expiry dates for a ticker."""
        if yf is None:
            raise RuntimeError("yfinance is not installed")

        sym = yf.Ticker(self._yahoo_ticker(ticker))
        try:
            return list(sym.options)
        except Exception:
            return []

    def fetch_iv_surface(self, ticker: str) -> pd.DataFrame:
        """Build an IV surface across all available expiries and strikes.

        Returns DataFrame with columns: expiry, strike, option_type, iv, last_price, volume, open_interest.
        """
        expiries = self.fetch_expiry_dates(ticker)
        rows = []
        for exp in expiries:
            chain = self.fetch_option_chain(ticker, exp)
            for opt_type, df in [("CE", chain["calls"]), ("PE", chain["puts"])]:
                if df.empty:
                    continue
                for _, row in df.iterrows():
                    rows.append({
                        "expiry": exp,
                        "strike": row.get("strike", 0),
                        "option_type": opt_type,
                        "iv": row.get("impliedVolatility", None),
                        "last_price": row.get("lastPrice", None),
                        "volume": row.get("volume", 0),
                        "open_interest": row.get("openInterest", 0),
                    })
        return pd.DataFrame(rows)

    def fetch_historical_option_prices(
        self,
        ticker: str,
        strike: float,
        expiry: str,
        option_type: str = "CE",
        start: str | datetime | None = None,
        end: str | datetime | None = None,
    ) -> pd.DataFrame:
        """Fetch historical prices for a specific option contract.

        Note: yfinance has limited support for historical option data.
        This returns current chain data as a snapshot.
        """
        chain = self.fetch_option_chain(ticker, expiry)
        key = "calls" if option_type == "CE" else "puts"
        df = chain[key]
        if df.empty:
            return df
        return df[df["strike"] == strike].copy()
