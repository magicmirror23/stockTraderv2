"""Helpers for loading strategy inputs from local/replay/live-compatible sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from backend.core.config import settings
from backend.trading_engine.strategies.base import StrategyMarketData


class StrategyMarketDataLoader:
    """Build normalized strategy inputs from the current project data sources."""

    def __init__(self, raw_data_path: str | Path | None = None, history_lookback: int = 80) -> None:
        self._raw_data_path = Path(raw_data_path or settings.raw_data_path)
        self._history_lookback = history_lookback

    def load(self, ticker: str, adapter: Any | None = None, prediction: dict[str, Any] | None = None) -> StrategyMarketData:
        history = self._load_history(ticker)
        spot_price = self._resolve_spot_price(ticker, adapter, history, prediction)
        return StrategyMarketData(
            ticker=str(ticker).upper(),
            spot_price=spot_price,
            history=history,
            prediction=prediction,
        )

    def _load_history(self, ticker: str) -> pd.DataFrame | None:
        path = self._raw_data_path / f"{str(ticker).upper()}.csv"
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path)
        except Exception:
            return None
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df = df.dropna(subset=["Date"]).sort_values("Date")
        if len(df) > self._history_lookback:
            df = df.tail(self._history_lookback).reset_index(drop=True)
        return df

    @staticmethod
    def _resolve_spot_price(
        ticker: str,
        adapter: Any | None,
        history: pd.DataFrame | None,
        prediction: dict[str, Any] | None,
    ) -> float:
        if prediction:
            value = prediction.get("close") or prediction.get("predicted_price")
            if value not in (None, "", 0, 0.0):
                return float(value)
        if adapter is not None:
            try:
                ltp = adapter.get_ltp(ticker)
                value = ltp.get("ltp") if isinstance(ltp, dict) else None
                if value not in (None, "", 0, 0.0):
                    return float(value)
            except Exception:
                pass
        if history is not None and not history.empty and "Close" in history.columns:
            close = pd.to_numeric(history["Close"], errors="coerce").dropna()
            if not close.empty:
                return float(close.iloc[-1])
        return 0.0
