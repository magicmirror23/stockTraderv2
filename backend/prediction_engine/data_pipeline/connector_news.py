"""News and sentiment data connector backed by a free news feed.

Uses GDELT's public DOC 2.0 article feed to fetch historical headlines,
then scores them with a finance- and macro-aware keyword lexicon.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode
from xml.etree import ElementTree

import pandas as pd
import requests


logger = logging.getLogger(__name__)

_POSITIVE = {
    "surge", "gain", "rally", "profit", "upgrade", "beat", "strong", "bullish",
    "growth", "record", "recovery", "expansion", "investment", "inflow",
    "capex", "stimulus", "easing", "optimism", "order", "contract", "boom",
    "approval", "ceasefire", "rebound", "acquisition", "reform", "subsidy",
    "liquidity", "dovish", "outperform", "partnership", "exports",
}
_NEGATIVE = {
    "drop", "fall", "loss", "crash", "downgrade", "miss", "weak", "bearish",
    "decline", "cut", "war", "conflict", "sanction", "inflation", "slowdown",
    "recession", "outflow", "deficit", "default", "risk", "selloff", "tariff",
    "attack", "missile", "hike", "layoff", "bankruptcy", "probe", "fraud",
    "volatility", "uncertainty", "disruption", "embargo", "debt",
}


@dataclass
class HeadlineRecord:
    timestamp: datetime
    source: str
    headline: str
    topic: str
    sentiment_score: float


class NewsConnector:
    """Fetches and scores historical news headlines for market topics."""

    BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    @staticmethod
    def _keyword_sentiment(text: str) -> float:
        words = re.findall(r"[a-z]+", text.lower())
        if not words:
            return 0.0
        word_set = set(words)
        pos = len(word_set & _POSITIVE)
        neg = len(word_set & _NEGATIVE)
        if pos == 0 and neg == 0:
            return 0.0
        return (pos - neg) / max(pos + neg, 1)

    @staticmethod
    def _format_dt(value: str | datetime | None, default: datetime) -> datetime:
        if value is None:
            return default
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        parsed = pd.Timestamp(value)
        if parsed.tzinfo is None:
            parsed = parsed.tz_localize(timezone.utc)
        else:
            parsed = parsed.tz_convert(timezone.utc)
        return parsed.to_pydatetime()

    @staticmethod
    def _to_gdelt_datetime(value: datetime) -> str:
        return value.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")

    def fetch_headlines(
        self,
        topic: str,
        query: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        max_records: int = 250,
    ) -> list[HeadlineRecord]:
        """Fetch headlines for a logical market topic."""
        end_dt = self._format_dt(end, datetime.now(timezone.utc))
        start_dt = self._format_dt(start, end_dt)
        params = {
            "query": query,
            "mode": "artlist",
            "format": "rssarchive",
            "maxrecords": max_records,
            "sort": "datedesc",
            "startdatetime": self._to_gdelt_datetime(start_dt),
            "enddatetime": self._to_gdelt_datetime(end_dt),
        }
        url = f"{self.BASE_URL}?{urlencode(params)}"
        logger.info("Fetching news topic %s from %s to %s", topic, start_dt, end_dt)
        response = self._session.get(url, timeout=30)
        response.raise_for_status()
        return self._parse_rss(topic, response.text)

    def fetch_to_csv(
        self,
        topic: str,
        query: str,
        start: str | datetime | None,
        end: str | datetime | None,
        output_dir: str | Path,
    ) -> Path:
        end_dt = self._format_dt(end, datetime.now(timezone.utc))
        start_dt = self._format_dt(start, end_dt)
        headlines = self.fetch_headlines(topic=topic, query=query, start=start_dt, end=end_dt)
        series = self.compute_sentiment_series(
            headlines,
            start_date=start_dt.date(),
            end_date=end_dt.date(),
        )
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{topic}.csv"
        series.to_csv(path, index=False)
        logger.info("Saved %d daily news rows -> %s", len(series), path)
        return path

    def compute_sentiment_series(
        self,
        headlines: list[HeadlineRecord],
        start_date: date | None = None,
        end_date: date | None = None,
        long_window: int = 30,
    ) -> pd.DataFrame:
        """Aggregate headline sentiment into daily and rolling features."""
        columns = [
            "date",
            "avg_sentiment",
            "headline_count",
            "sentiment_7d",
            "sentiment_30d",
            "headline_count_7d",
            "headline_count_30d",
        ]
        if not headlines and start_date is None and end_date is None:
            return pd.DataFrame(columns=columns)

        if headlines:
            min_date = min(h.timestamp.date() for h in headlines)
            max_date = max(h.timestamp.date() for h in headlines)
            start_date = start_date or min_date
            end_date = end_date or max_date
        else:
            if start_date is None or end_date is None:
                return pd.DataFrame(columns=columns)

        full_index = pd.date_range(pd.Timestamp(start_date), pd.Timestamp(end_date), freq="D")

        if headlines:
            records = [
                {
                    "date": pd.Timestamp(h.timestamp.date()),
                    "sentiment": h.sentiment_score,
                }
                for h in headlines
            ]
            df = pd.DataFrame(records)
            daily = (
                df.groupby("date")
                .agg(avg_sentiment=("sentiment", "mean"), headline_count=("sentiment", "count"))
                .reset_index()
                .sort_values("date")
            )
            daily = daily.set_index("date").reindex(full_index).rename_axis("date").reset_index()
        else:
            daily = pd.DataFrame({"date": full_index, "avg_sentiment": 0.0, "headline_count": 0})

        daily["avg_sentiment"] = daily["avg_sentiment"].fillna(0.0)
        daily["headline_count"] = daily["headline_count"].fillna(0)
        daily["sentiment_7d"] = daily["avg_sentiment"].rolling(window=7, min_periods=1).mean()
        daily["sentiment_30d"] = daily["avg_sentiment"].rolling(window=long_window, min_periods=1).mean()
        daily["headline_count_7d"] = daily["headline_count"].rolling(window=7, min_periods=1).sum()
        daily["headline_count_30d"] = daily["headline_count"].rolling(window=long_window, min_periods=1).sum()
        return daily

    def score_text(self, text: str) -> float:
        return self._keyword_sentiment(text)

    def _parse_rss(self, topic: str, xml_text: str) -> list[HeadlineRecord]:
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as exc:
            logger.warning("Failed to parse news feed for %s: %s", topic, exc)
            return []

        records: list[HeadlineRecord] = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            if not title:
                continue
            source = (item.findtext("source") or item.findtext("guid") or "gdelt").strip()
            pub_date = item.findtext("pubDate")
            if not pub_date:
                continue
            try:
                timestamp = parsedate_to_datetime(pub_date)
            except Exception:
                continue
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            else:
                timestamp = timestamp.astimezone(timezone.utc)
            records.append(
                HeadlineRecord(
                    timestamp=timestamp,
                    source=source,
                    headline=title,
                    topic=topic,
                    sentiment_score=self._keyword_sentiment(title),
                )
            )
        return records


def topic_queries() -> dict[str, str]:
    """Default market and macro news queries."""
    return {
        "india_market": "\"india stock market\" OR nifty OR sensex OR \"equity market\" OR earnings",
        "india_economy": "\"india economy\" OR inflation OR gdp OR manufacturing OR unemployment OR budget OR exports",
        "central_banks": "RBI OR \"Reserve Bank of India\" OR \"Federal Reserve\" OR \"interest rates\" OR inflation OR liquidity",
        "capital_flows": "\"foreign investment\" OR FII OR DII OR \"capital inflow\" OR \"mutual fund inflow\" OR capex",
        "geopolitics": "war OR conflict OR sanctions OR \"geopolitical tension\" OR ukraine OR russia OR \"middle east\" OR tariff",
    }


def topic_feature_columns() -> list[str]:
    columns: list[str] = []
    for topic in topic_queries():
        columns.extend(
            [
                f"{topic}_sentiment_7d",
                f"{topic}_sentiment_30d",
                f"{topic}_headline_count_7d",
                f"{topic}_headline_count_30d",
            ]
        )
    return columns


def list_topic_files(directory: str | Path) -> Iterable[Path]:
    path = Path(directory)
    if not path.exists():
        return []
    return sorted(path.glob("*.csv"))
