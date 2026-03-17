"""Integration tests for the feature store."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.prediction_engine.feature_store.feature_store import (
    build_features,
    get_features_for_inference,
    FEATURE_COLUMNS,
)
from backend.prediction_engine.feature_store.normalization import normalize_features_per_ticker
from backend.prediction_engine.model_features import MODEL_INPUT_COLUMNS
from backend.services import news_context as news_context_module
from backend.services import training_data as training_data_module

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _write_synthetic_ohlcv(output_dir: Path, ticker: str, periods: int = 260) -> Path:
    dates = pd.date_range("2024-01-01", periods=periods, freq="D")
    base = np.arange(periods, dtype=float)
    trend = 0.18 * base
    seasonal = 4.5 * np.sin(base / 8.0)
    close = 100.0 + trend + seasonal
    open_price = close + 0.6 * np.cos(base / 5.0)
    high = np.maximum(open_price, close) + 1.2 + np.abs(np.sin(base / 6.0))
    low = np.minimum(open_price, close) - 1.2 - np.abs(np.cos(base / 6.0))
    volume = 1_000_000 + (base * 900) + (40_000 * np.sin(base / 11.0))
    frame = pd.DataFrame(
        {
            "Date": dates,
            "Open": open_price,
            "High": high,
            "Low": low,
            "Close": close,
            "Adj Close": close,
            "Volume": volume,
        }
    )
    path = output_dir / f"{ticker}.csv"
    frame.to_csv(path, index=False)
    return path


@pytest.fixture()
def _setup_fixture_as_raw(tmp_path):
    """Create a synthetic OHLCV CSV in a temp raw dir."""
    dest = _write_synthetic_ohlcv(tmp_path, "TESTICKER")
    return tmp_path


def test_build_features_columns(_setup_fixture_as_raw):
    df = build_features(["TESTICKER"], data_dir=_setup_fixture_as_raw)
    assert not df.empty
    assert list(df.columns) == FEATURE_COLUMNS


def test_build_features_returns_dataframe(tmp_path):
    """Build features from a synthetic fixture."""
    _write_synthetic_ohlcv(tmp_path, "SAMPLE")

    df = build_features(["SAMPLE"], data_dir=tmp_path)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == FEATURE_COLUMNS
    assert len(df) > 0


def test_build_features_deterministic(tmp_path):
    _write_synthetic_ohlcv(tmp_path, "SAMPLE")

    df1 = build_features(["SAMPLE"], data_dir=tmp_path)
    df2 = build_features(["SAMPLE"], data_dir=tmp_path)

    pd.testing.assert_frame_equal(df1, df2)


def test_get_features_for_inference(tmp_path):
    _write_synthetic_ohlcv(tmp_path, "SAMPLE")

    class _DummyNewsManager:
        def ensure_recent(self, force: bool = False):
            return None

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(news_context_module, "get_news_context_manager", lambda: _DummyNewsManager())
    monkeypatch.setattr(training_data_module, "load_training_tickers", lambda: ["SAMPLE"])

    result = get_features_for_inference("SAMPLE", data_dir=tmp_path)
    assert isinstance(result, dict)
    for col in FEATURE_COLUMNS:
        assert col in result
    monkeypatch.undo()


def test_news_features_are_lagged_for_training_but_recent_for_inference(tmp_path, monkeypatch):
    dates = pd.date_range("2024-01-01", periods=260, freq="D")
    _write_synthetic_ohlcv(tmp_path, "SAMPLE", periods=len(dates))

    news_dir = tmp_path / "news"
    news_dir.mkdir()
    news = pd.DataFrame(
        {
            "date": dates,
            "avg_sentiment": np.linspace(-0.2, 0.8, len(dates)),
            "headline_count": np.arange(len(dates)) + 1,
            "sentiment_7d": np.arange(len(dates), dtype=float) * 10.0,
            "sentiment_30d": np.arange(len(dates), dtype=float),
            "headline_count_7d": np.arange(len(dates), dtype=float) * 3.0,
            "headline_count_30d": np.arange(len(dates), dtype=float) * 5.0,
        }
    )
    news.to_csv(news_dir / "india_market.csv", index=False)

    training_df = build_features(["SAMPLE"], data_dir=tmp_path, news_dir=news_dir, news_mode="training")
    inference_df = build_features(["SAMPLE"], data_dir=tmp_path, news_dir=news_dir, news_mode="inference")

    training_last = training_df.iloc[-1]
    inference_last = inference_df.iloc[-1]
    last_date = pd.Timestamp(inference_last["date"])
    prior_date = last_date - pd.Timedelta(days=1)

    expected_same_day = float(news.loc[news["date"] == last_date, "sentiment_30d"].iloc[0])
    expected_prior_day = float(news.loc[news["date"] == prior_date, "sentiment_30d"].iloc[0])

    assert inference_last["india_market_sentiment_30d"] == expected_same_day
    assert training_last["india_market_sentiment_30d"] == expected_prior_day

    class _DummyNewsManager:
        def ensure_recent(self, force: bool = False):
            return None

    monkeypatch.setattr(news_context_module, "get_news_context_manager", lambda: _DummyNewsManager())
    monkeypatch.setattr(training_data_module, "load_training_tickers", lambda: ["SAMPLE"])

    inference_row = get_features_for_inference("SAMPLE", data_dir=tmp_path, news_dir=news_dir)
    assert inference_row["india_market_sentiment_30d"] == expected_same_day


def test_company_news_features_are_lagged_for_training_but_recent_for_inference(tmp_path, monkeypatch):
    dates = pd.date_range("2024-01-01", periods=260, freq="D")
    _write_synthetic_ohlcv(tmp_path, "SAMPLE", periods=len(dates))

    company_news_dir = tmp_path / "company_news"
    company_news_dir.mkdir()
    company_news = pd.DataFrame(
        {
            "date": dates,
            "avg_sentiment": np.linspace(-0.1, 0.6, len(dates)),
            "headline_count": np.arange(len(dates)) + 5,
            "avg_event_score": np.linspace(-0.3, 0.3, len(dates)),
            "sentiment_7d": np.arange(len(dates), dtype=float) * 2.0,
            "sentiment_30d": np.arange(len(dates), dtype=float) * 1.0,
            "headline_count_7d": np.arange(len(dates), dtype=float) * 4.0,
            "headline_count_30d": np.arange(len(dates), dtype=float) * 6.0,
            "event_score_7d": np.linspace(-0.2, 0.8, len(dates)),
            "event_score_30d": np.linspace(-0.5, 0.5, len(dates)),
        }
    )
    company_news.to_csv(company_news_dir / "SAMPLE.csv", index=False)

    class _DummyNewsManager:
        def ensure_recent(self, force: bool = False):
            return None

    monkeypatch.setattr(news_context_module, "get_news_context_manager", lambda: _DummyNewsManager())
    monkeypatch.setattr(training_data_module, "load_training_tickers", lambda: ["SAMPLE"])

    training_df = build_features(
        ["SAMPLE"],
        data_dir=tmp_path,
        company_news_dir=company_news_dir,
        news_mode="training",
    )
    inference_df = build_features(
        ["SAMPLE"],
        data_dir=tmp_path,
        company_news_dir=company_news_dir,
        news_mode="inference",
    )
    training_last = training_df.iloc[-1]
    inference_last = inference_df.iloc[-1]
    last_date = pd.Timestamp(inference_last["date"])
    prior_date = last_date - pd.Timedelta(days=1)

    expected_same_day = float(company_news.loc[company_news["date"] == last_date, "sentiment_30d"].iloc[0])
    expected_prior_day = float(company_news.loc[company_news["date"] == prior_date, "sentiment_30d"].iloc[0])

    assert inference_last["company_sentiment_30d"] == expected_same_day
    assert training_last["company_sentiment_30d"] == expected_prior_day

    inference_row = get_features_for_inference(
        "SAMPLE",
        data_dir=tmp_path,
        company_news_dir=company_news_dir,
    )
    assert inference_row["company_sentiment_30d"] == expected_same_day


def test_inference_uses_training_normalization_contract(tmp_path, monkeypatch):
    _write_synthetic_ohlcv(tmp_path, "SAMPLE", periods=260)

    class _DummyNewsManager:
        def ensure_recent(self, force: bool = False):
            return None

    monkeypatch.setattr(news_context_module, "get_news_context_manager", lambda: _DummyNewsManager())
    monkeypatch.setattr(training_data_module, "load_training_tickers", lambda: ["SAMPLE"])

    raw = build_features(["SAMPLE"], data_dir=tmp_path, news_mode="inference")
    normalized = normalize_features_per_ticker(raw.copy(), MODEL_INPUT_COLUMNS)
    normalized = normalized.dropna(subset=MODEL_INPUT_COLUMNS).reset_index(drop=True)

    inference_row = get_features_for_inference("SAMPLE", data_dir=tmp_path)

    assert inference_row["close"] == pytest.approx(float(normalized.iloc[-1]["close"]))
    assert inference_row["macd"] == pytest.approx(float(normalized.iloc[-1]["macd"]))
    assert inference_row["market_return_1d"] == pytest.approx(float(normalized.iloc[-1]["market_return_1d"]))
