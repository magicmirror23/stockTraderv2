"""Paper trading replay engine.

Replays intraday OHLCV bars for a paper account with configurable
speed multiplier and streaming progress.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from backend.paper_trading.paper_account import PaperAccount
from backend.paper_trading.paper_executor import PaperExecutor

logger = logging.getLogger(__name__)


class PaperReplayer:
    """Replays a trading day bar-by-bar on a paper account."""

    def __init__(
        self,
        executor: PaperExecutor | None = None,
        data_dir: str | Path = "storage/raw",
    ) -> None:
        self._executor = executor or PaperExecutor()
        self._data_dir = Path(data_dir)

    def replay_day(
        self,
        account: PaperAccount,
        date: str,
        tickers: list[str] | None = None,
        signal_fn=None,
    ) -> dict:
        """Replay a single trading day.

        Parameters
        ----------
        account : PaperAccount
            The paper account to execute against.
        date : str
            ISO date string (YYYY-MM-DD).
        tickers : list[str], optional
            Tickers to replay. If None, uses all CSVs in data_dir.
        signal_fn : callable, optional
            Function(ticker, row) -> {"side": "buy"|"sell"|None, "quantity": int}
            If None, no trades are generated.

        Returns
        -------
        dict
            Summary: trades executed, equity snapshot, P&L.
        """
        target_date = pd.Timestamp(date)

        if tickers is None:
            csvs = list(self._data_dir.glob("*.csv"))
            tickers = [c.stem for c in csvs]

        trades = []
        for ticker in tickers:
            csv_path = self._data_dir / f"{ticker}.csv"
            if not csv_path.exists():
                continue

            df = pd.read_csv(csv_path, parse_dates=["Date"])
            day_rows = df[df["Date"].dt.date == target_date.date()]

            if day_rows.empty:
                continue

            for _, row in day_rows.iterrows():
                if signal_fn:
                    signal = signal_fn(ticker, row)
                    if signal and signal.get("side"):
                        fill = self._executor.execute_order(
                            account=account,
                            ticker=ticker,
                            side=signal["side"],
                            quantity=signal.get("quantity", 1),
                            market_price=float(row["Close"]),
                        )
                        if fill:
                            trades.append({
                                "ticker": ticker,
                                "side": fill.side,
                                "quantity": fill.quantity,
                                "price": fill.fill_price,
                                "slippage": fill.slippage,
                            })

        # Record equity
        market_prices = {}
        for ticker in tickers:
            csv_path = self._data_dir / f"{ticker}.csv"
            if csv_path.exists():
                df = pd.read_csv(csv_path, parse_dates=["Date"])
                day_rows = df[df["Date"].dt.date == target_date.date()]
                if not day_rows.empty:
                    market_prices[ticker] = float(day_rows.iloc[-1]["Close"])

        account.record_equity(date, market_prices)

        # Handle option expiry
        expired = account.expire_options(date, market_prices)

        return {
            "date": date,
            "trades_executed": len(trades),
            "trades": trades,
            "expired_options": expired,
            "equity": account.equity,
            "cash": account.cash,
            "positions": len(account.positions),
        }

    def replay_range(
        self,
        account: PaperAccount,
        start_date: str,
        end_date: str,
        tickers: list[str] | None = None,
        signal_fn=None,
    ) -> list[dict]:
        """Replay multiple days sequentially."""
        dates = pd.bdate_range(start_date, end_date)
        results = []
        for date in dates:
            result = self.replay_day(
                account, str(date.date()), tickers, signal_fn
            )
            results.append(result)
        return results
