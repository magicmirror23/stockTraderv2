"""Tests for model predict output shape and probability mapping."""

import numpy as np
import pandas as pd
import pytest

from backend.prediction_engine.models.lightgbm_model import LightGBMModel

# Skip all tests if lightgbm is not installed
lgb = pytest.importorskip("lightgbm")


@pytest.fixture()
def trained_model(tmp_path):
    """Train a tiny model on synthetic data."""
    np.random.seed(42)
    n = 200
    X = pd.DataFrame({
        "f1": np.random.randn(n),
        "f2": np.random.randn(n),
        "f3": np.random.randn(n),
    })
    y = pd.Series(np.random.choice([0, 1, 2], size=n))

    model = LightGBMModel(seed=42)
    model.train(X, y, num_boost_round=10)
    return model, X


def test_predict_shape(trained_model):
    model, X = trained_model
    preds = model.predict(X)
    assert preds.shape == (len(X),)
    assert set(np.unique(preds)).issubset({0, 1, 2})


def test_predict_proba_shape(trained_model):
    model, X = trained_model
    proba = model.predict_proba(X)
    assert proba.shape == (len(X), 3)
    np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-6)


def test_predict_with_expected_return(trained_model):
    model, X = trained_model
    results = model.predict_with_expected_return(X)
    assert len(results) == len(X)
    for r in results:
        assert r["action"] in ("buy", "sell", "hold")
        assert 0.0 <= r["confidence"] <= 1.0


def test_save_load_roundtrip(trained_model, tmp_path):
    model, X = trained_model
    original_preds = model.predict(X)

    model.save(tmp_path / "test_model")
    loaded = LightGBMModel.load(tmp_path / "test_model")

    np.testing.assert_array_equal(loaded.predict(X), original_preds)
    assert loaded.get_version() == model.get_version()
