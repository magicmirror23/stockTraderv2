"""News / sentiment data connector.

Fetches headlines and computes basic sentiment scores.
Uses a simple keyword-based approach as a baseline;
can be extended with a proper NLP model.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

# Simple keyword sentiment lexicon (extendable)
_POSITIVE = {"surge", "gain", "rally", "profit", "upgrade", "beat", "strong", "bullish", "growth", "record"}
_NEGATIVE = {"drop", "fall", "loss", "crash", "downgrade", "miss", "weak", "bearish", "decline", "cut"}


@dataclass
class HeadlineRecord:
    timestamp: datetime
    source: str
    headline: str
    ticker: str
    sentiment_score: float  # -1 to 1


class NewsConnector:
    """Fetches and scores news headlines for given tickers.

    Currently uses a keyword-based scorer. Set NEWS_API_KEY to enable
    external API integration (stub).
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("NEWS_API_KEY")

    @staticmethod
    def _keyword_sentiment(text: str) -> float:
        """Simple keyword-based sentiment scoring (-1 to 1)."""
        words = set(re.findall(r"[a-z]+", text.lower()))
        pos = len(words & _POSITIVE)
        neg = len(words & _NEGATIVE)
        total = pos + neg
        if total == 0:
            return 0.0
        return (pos - neg) / total

    def fetch_headlines(
        self,
        ticker: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
    ) -> list[HeadlineRecord]:
        """Fetch news headlines for a ticker.

        TODO: Integrate with a real news API (e.g., NewsAPI, Google News RSS).
        Currently returns an empty list as a stub.
        """
        logger.info("Fetching headlines for %s (stub — no real API configured)", ticker)
        # Placeholder: in production, call an external news API here
        return []

    def compute_sentiment_series(
        self,
        headlines: list[HeadlineRecord],
    ) -> pd.DataFrame:
        """Aggregate headline sentiment into a daily time series.

        Returns DataFrame with columns: date, avg_sentiment, headline_count.
        """
        if not headlines:
            return pd.DataFrame(columns=["date", "avg_sentiment", "headline_count"])

        records = [
            {"date": h.timestamp.date(), "sentiment": h.sentiment_score}
            for h in headlines
        ]
        df = pd.DataFrame(records)
        daily = df.groupby("date").agg(
            avg_sentiment=("sentiment", "mean"),
            headline_count=("sentiment", "count"),
        ).reset_index()
        return daily

    def score_text(self, text: str) -> float:
        """Score arbitrary text for sentiment."""
        return self._keyword_sentiment(text)
