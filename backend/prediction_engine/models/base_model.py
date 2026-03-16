"""Abstract base class for all prediction models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class BaseModel(ABC):
    """Interface that every prediction model must implement."""

    @abstractmethod
    def train(self, X: pd.DataFrame, y: pd.Series, **kwargs: Any) -> dict:
        """Train the model.

        Returns a dict of training metrics.
        """

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return predicted class labels (0 = sell, 1 = hold, 2 = buy)."""

    @abstractmethod
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return class probabilities with shape (n_samples, n_classes)."""

    @abstractmethod
    def save(self, path: str | Path) -> Path:
        """Persist model artifact to disk. Returns the saved path."""

    @classmethod
    @abstractmethod
    def load(cls, path: str | Path) -> "BaseModel":
        """Load a previously saved model from disk."""

    @abstractmethod
    def get_version(self) -> str:
        """Return a version identifier for this model instance."""
