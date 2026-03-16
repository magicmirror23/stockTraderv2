"""Walk-forward backtester with configurable execution model.

Simulates trading based on model predictions and computes portfolio
performance metrics.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

STORAGE_DIR = Path(__file__).resolve().parents[3] / "storage" / "backtests"


@dataclass
class ExecutionConfig:
    """Configurable execution model for the backtester."""

    slippage_pct: float = 0.001        # 0.1 % slippage
    fill_probability: float = 0.98     # 98 % fill rate
    use_angel_charges: bool = True     # Use real Angel One brokerage charges
    trade_type: str = "intraday"       # "intraday" or "delivery"
    # Legacy flat commission (used only when use_angel_charges=False)
    commission_per_trade: float = 20.0


@dataclass
class Trade:
    date: str
    ticker: str
    side: str  # "buy" | "sell"
    quantity: int
    price: float
    pnl: float = 0.0


@dataclass
class BacktestResult:
    job_id: str
    status: str
    tickers: list[str]
    start_date: str
    end_date: str
    initial_capital: float
    final_value: float
    total_return_pct: float
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown_pct: float | None = None
    cagr_pct: float | None = None
    total_charges: float = 0.0
    trades: list[Trade] = field(default_factory=list)
    completed_at: str | None = None


class Backtester:
    """Walk-forward backtesting engine with Angel One charges support."""

    def __init__(self, config: ExecutionConfig | None = None) -> None:
        self.config = config or ExecutionConfig()
        self._charge_calc = None

    def _get_charges(self, buy_price: float, sell_price: float, qty: int) -> float:
        """Calculate total charges for a round-trip trade."""
        if self.config.use_angel_charges:
            from backend.services.brokerage_calculator import (
                calculate_charges, TradeType,
            )
            trade_type = (
                TradeType.DELIVERY if self.config.trade_type == "delivery"
                else TradeType.INTRADAY
            )
            breakdown = calculate_charges(buy_price, sell_price, qty, trade_type)
            return breakdown.total_charges
        # Legacy flat commission
        return self.config.commission_per_trade * 2  # buy + sell

    def run(
        self,
        predictions_df: pd.DataFrame,
        price_df: pd.DataFrame,
        initial_capital: float = 100_000.0,
        job_id: str | None = None,
    ) -> BacktestResult:
        """Run a backtest.

        Parameters
        ----------
        predictions_df : pd.DataFrame
            Must have columns: date, ticker, action, confidence.
        price_df : pd.DataFrame
            Must have columns: Date, ticker, Close.
        initial_capital : float
            Starting cash.
        job_id : str, optional
            Unique job identifier; auto-generated if not provided.
        """
        job_id = job_id or str(uuid.uuid4())
        cash = initial_capital
        positions: dict[str, int] = {}  # ticker -> qty
        entry_prices: dict[str, float] = {}  # ticker -> avg buy price
        trades: list[Trade] = []
        portfolio_values: list[float] = []
        total_charges_paid: float = 0.0

        dates = sorted(predictions_df["date"].unique())

        for date in dates:
            day_preds = predictions_df[predictions_df["date"] == date]
            day_prices = price_df[price_df["Date"] == date]

            for _, pred in day_preds.iterrows():
                ticker = pred["ticker"]
                action = pred["action"]

                price_row = day_prices[day_prices["ticker"] == ticker]
                if price_row.empty:
                    continue
                price = float(price_row["Close"].iloc[0])

                # Apply fill probability
                if np.random.random() > self.config.fill_probability:
                    continue

                if action == "buy" and cash > price:
                    # Buy with slippage
                    exec_price = price * (1 + self.config.slippage_pct)
                    qty = max(1, int(cash * 0.1 / exec_price))  # 10% of cash per trade
                    cost = qty * exec_price + self.config.commission_per_trade
                    if cost <= cash:
                        cash -= cost
                        positions[ticker] = positions.get(ticker, 0) + qty
                        entry_prices[ticker] = exec_price
                        trades.append(Trade(
                            date=str(date), ticker=ticker, side="buy",
                            quantity=qty, price=exec_price,
                        ))

                elif action == "sell" and positions.get(ticker, 0) > 0:
                    exec_price = price * (1 - self.config.slippage_pct)
                    qty = positions[ticker]
                    avg_buy = entry_prices.get(ticker, price)
                    total_charges = self._get_charges(avg_buy, exec_price, qty)
                    proceeds = qty * exec_price - total_charges
                    pnl = (exec_price - avg_buy) * qty - total_charges
                    cash += proceeds
                    positions[ticker] = 0
                    total_charges_paid += total_charges
                    trades.append(Trade(
                        date=str(date), ticker=ticker, side="sell",
                        quantity=qty, price=exec_price, pnl=round(pnl, 2),
                    ))

            # Mark-to-market portfolio
            pos_value = 0.0
            for tkr, qty in positions.items():
                p = day_prices[day_prices["ticker"] == tkr]
                if not p.empty and qty > 0:
                    pos_value += qty * float(p["Close"].iloc[0])
            portfolio_values.append(cash + pos_value)

        final_value = portfolio_values[-1] if portfolio_values else initial_capital
        total_return = (final_value / initial_capital - 1) * 100

        # Metrics
        sharpe = self._sharpe(portfolio_values)
        sortino = self._sortino(portfolio_values)
        max_dd = self._max_drawdown(portfolio_values)
        cagr = self._cagr(initial_capital, final_value, len(dates))

        result = BacktestResult(
            job_id=job_id,
            status="completed",
            tickers=sorted(set(predictions_df["ticker"])),
            start_date=str(dates[0]) if dates else "",
            end_date=str(dates[-1]) if dates else "",
            initial_capital=initial_capital,
            final_value=round(final_value, 2),
            total_return_pct=round(total_return, 2),
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown_pct=max_dd,
            cagr_pct=cagr,
            total_charges=round(total_charges_paid, 2),
            trades=trades,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

        # Persist
        self._save_result(result)
        return result

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @staticmethod
    def _sharpe(values: list[float], risk_free: float = 0.0) -> float | None:
        if len(values) < 2:
            return None
        rets = pd.Series(values).pct_change().dropna()
        if rets.std() == 0:
            return None
        return round(float((rets.mean() - risk_free) / rets.std() * math.sqrt(252)), 4)

    @staticmethod
    def _sortino(values: list[float], risk_free: float = 0.0) -> float | None:
        if len(values) < 2:
            return None
        rets = pd.Series(values).pct_change().dropna()
        down = rets[rets < 0]
        if down.empty or down.std() == 0:
            return None
        return round(float((rets.mean() - risk_free) / down.std() * math.sqrt(252)), 4)

    @staticmethod
    def _max_drawdown(values: list[float]) -> float | None:
        if len(values) < 2:
            return None
        peak = values[0]
        max_dd = 0.0
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
        return round(max_dd * 100, 2)

    @staticmethod
    def _cagr(initial: float, final: float, days: int) -> float | None:
        if days <= 0 or initial <= 0:
            return None
        years = days / 252  # trading days
        if years <= 0:
            return None
        return round(((final / initial) ** (1 / years) - 1) * 100, 2)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _save_result(result: BacktestResult) -> Path:
        job_dir = STORAGE_DIR / result.job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / "results.json"
        path.write_text(json.dumps(asdict(result), indent=2, default=str))
        logger.info("Backtest results saved → %s", path)
        return path

    @staticmethod
    def load_result(job_id: str) -> dict | None:
        path = STORAGE_DIR / job_id / "results.json"
        if path.exists():
            return json.loads(path.read_text())
        return None
