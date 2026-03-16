"""Cached news context refresh for training and inference."""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.core.config import settings
from backend.prediction_engine.data_pipeline.connector_news import NewsConnector, topic_queries


logger = logging.getLogger(__name__)


@dataclass
class NewsRefreshReport:
    topics: list[str]
    downloaded: list[str]
    refreshed: list[str]
    reused: list[str]
    failed: dict[str, str]
    start_date: str
    end_date: str
    output_dir: str

    def to_dict(self) -> dict:
        return asdict(self)


class NewsContextManager:
    """Ensures recent topic-level news features exist on disk."""

    _instance: "NewsContextManager | None" = None
    _guard = threading.Lock()

    def __new__(cls) -> "NewsContextManager":
        if cls._instance is None:
            with cls._guard:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._lock = threading.Lock()
                    cls._instance._last_report = None
                    cls._instance._last_checked_at = None
        return cls._instance

    def ensure_recent(self, force: bool = False) -> NewsRefreshReport | None:
        if not settings.ENABLE_NEWS_FEATURES:
            return None

        with self._lock:
            now = datetime.now(timezone.utc)
            if (
                not force
                and self._last_checked_at is not None
                and now - self._last_checked_at < timedelta(minutes=15)
                and self._last_report is not None
            ):
                return self._last_report

            report = refresh_news_context(
                output_dir=settings.news_data_path / "topics",
                lookback_days=settings.NEWS_CONTEXT_LOOKBACK_DAYS,
                max_age_hours=settings.NEWS_DATA_MAX_AGE_HOURS,
            )
            self._last_checked_at = now
            self._last_report = report
            return report


def refresh_news_context(
    output_dir: str | Path,
    lookback_days: int,
    max_age_hours: int,
) -> NewsRefreshReport:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    connector = NewsConnector()
    topics = topic_queries()

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=lookback_days)
    report = NewsRefreshReport(
        topics=list(topics.keys()),
        downloaded=[],
        refreshed=[],
        reused=[],
        failed={},
        start_date=start_dt.date().isoformat(),
        end_date=end_dt.date().isoformat(),
        output_dir=str(output_dir),
    )

    for topic, query in topics.items():
        path = output_dir / f"{topic}.csv"
        existed_before = path.exists()
        if path.exists():
            age = end_dt - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if age <= timedelta(hours=max_age_hours):
                report.reused.append(topic)
                continue

        try:
            connector.fetch_to_csv(topic=topic, query=query, start=start_dt, end=end_dt, output_dir=output_dir)
            if existed_before:
                report.refreshed.append(topic)
            else:
                report.downloaded.append(topic)
        except Exception as exc:
            report.failed[topic] = str(exc)
            logger.warning("Failed to refresh news topic %s: %s", topic, exc)

    return report


def get_news_context_manager() -> NewsContextManager:
    return NewsContextManager()
