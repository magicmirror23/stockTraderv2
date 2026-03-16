"""Sequence model prototypes (LSTM / Transformer).

Provides BaseModel-compatible wrappers for PyTorch-based
sequence models. Falls back gracefully if torch is not installed.
"""

from __future__ import annotations

import json
import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from backend.prediction_engine.models.base_model import BaseModel

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("torch not installed — sequence models unavailable")


class _LSTMNet(nn.Module if TORCH_AVAILABLE else object):
    """LSTM classifier with dropout regularization."""

    def __init__(self, input_dim: int, hidden_dim: int = 128, num_classes: int = 3):
        if not TORCH_AVAILABLE:
            return
        super().__init__()
        self.lstm = nn.LSTM(input_dim, hidden_dim, batch_first=True, num_layers=2, dropout=0.3)
        self.dropout = nn.Dropout(0.3)
        self.fc1 = nn.Linear(hidden_dim, hidden_dim // 2)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(hidden_dim // 2, num_classes)

    def forward(self, x):
        _, (h_n, _) = self.lstm(x)
        out = self.dropout(h_n[-1])
        out = self.relu(self.fc1(out))
        return self.fc2(out)


class _GRUFeatureNet(nn.Module if TORCH_AVAILABLE else object):
    """GRU binary classifier with extractable feature layer (demo.py strategy).

    Architecture: GRU(48) → Dropout → GRU(24) → Dropout → Dense(12, relu) → Dense(1, sigmoid)
    The Dense(12) layer is the feature extraction point for the XGBoost meta-learner.
    """

    def __init__(self, input_dim: int, hidden1: int = 48, hidden2: int = 24, feature_dim: int = 12):
        if not TORCH_AVAILABLE:
            return
        super().__init__()
        self.gru1 = nn.GRU(input_dim, hidden1, batch_first=True)
        self.drop1 = nn.Dropout(0.2)
        self.gru2 = nn.GRU(hidden1, hidden2, batch_first=True)
        self.drop2 = nn.Dropout(0.2)
        self.feature_layer = nn.Linear(hidden2, feature_dim)
        self.relu = nn.ReLU()
        self.output = nn.Linear(feature_dim, 1)

    def forward(self, x):
        x, _ = self.gru1(x)
        x = self.drop1(x)
        x, _ = self.gru2(x)
        x = self.drop2(x[:, -1, :])  # last timestep
        features = self.relu(self.feature_layer(x))
        out = torch.sigmoid(self.output(features))
        return out

    def extract_features(self, x):
        """Return the intermediate feature vector (for XGBoost meta-learner)."""
        x, _ = self.gru1(x)
        x = self.drop1(x)
        x, _ = self.gru2(x)
        x = self.drop2(x[:, -1, :])
        return self.relu(self.feature_layer(x))


class SequenceModel(BaseModel):
    """LSTM-based sequence model following BaseModel interface.

    Input X is expected as (n_samples, seq_len, n_features).
    For 2D input, it is reshaped to (n_samples, 1, n_features).
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self._params = params or {
            "hidden_dim": 128,
            "num_classes": 3,
            "epochs": 40,
            "lr": 0.0005,
            "batch_size": 64,
            "seq_len": 10,
        }
        self._model: Any = None
        self._version: str = ""
        self._trained_at: datetime | None = None

    def train(self, X: np.ndarray, y: np.ndarray, params: dict | None = None) -> None:
        if not TORCH_AVAILABLE:
            raise RuntimeError("torch is not installed")

        p = {**self._params, **(params or {})}
        torch.manual_seed(42)

        # Reshape if 2D
        if X.ndim == 2:
            X = X.reshape(X.shape[0], 1, X.shape[1])

        input_dim = X.shape[2]
        self._model = _LSTMNet(input_dim, p["hidden_dim"], p["num_classes"])
        optimizer = torch.optim.Adam(self._model.parameters(), lr=p["lr"])
        criterion = nn.CrossEntropyLoss()

        X_t = torch.FloatTensor(X)
        y_t = torch.LongTensor(y)

        dataset = torch.utils.data.TensorDataset(X_t, y_t)
        loader = torch.utils.data.DataLoader(dataset, batch_size=p["batch_size"], shuffle=False)

        self._model.train()
        for epoch in range(p["epochs"]):
            total_loss = 0
            for xb, yb in loader:
                optimizer.zero_grad()
                out = self._model(xb)
                loss = criterion(out, yb)
                loss.backward()
                optimizer.step()
                total_loss += loss.item()
            if (epoch + 1) % 5 == 0:
                logger.info("Epoch %d/%d loss=%.4f", epoch + 1, p["epochs"], total_loss / len(loader))

        self._trained_at = datetime.now(timezone.utc)
        self._version = f"lstm_{self._trained_at.strftime('%Y%m%d_%H%M%S')}"

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Model not trained or loaded")
        if X.ndim == 2:
            X = X.reshape(X.shape[0], 1, X.shape[1])
        self._model.eval()
        with torch.no_grad():
            out = self._model(torch.FloatTensor(X))
            return out.argmax(dim=1).numpy()

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Model not trained or loaded")
        if X.ndim == 2:
            X = X.reshape(X.shape[0], 1, X.shape[1])
        self._model.eval()
        with torch.no_grad():
            out = self._model(torch.FloatTensor(X))
            return torch.softmax(out, dim=1).numpy()

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        torch.save(self._model.state_dict(), path / "model.pt")
        meta = {
            "type": "lstm",
            "version": self._version,
            "trained_at": self._trained_at.isoformat() if self._trained_at else None,
            "params": self._params,
        }
        (path / "meta.json").write_text(json.dumps(meta, indent=2))

    def load(self, path: str | Path) -> None:
        if not TORCH_AVAILABLE:
            raise RuntimeError("torch is not installed")
        path = Path(path)
        meta = json.loads((path / "meta.json").read_text())
        p = meta.get("params", self._params)
        # Need input_dim from saved state
        state = torch.load(path / "model.pt", map_location="cpu", weights_only=True)
        input_dim = state["lstm.weight_ih_l0"].shape[1]
        self._model = _LSTMNet(input_dim, p.get("hidden_dim", 64), p.get("num_classes", 3))
        self._model.load_state_dict(state)
        self._version = meta.get("version", "")

    def get_version(self) -> str:
        return self._version


class GRUFeatureExtractor:
    """GRU binary model with extractable hidden features (demo.py strategy).

    Used in the hybrid pipeline: GRU trains on sequences, then its hidden features
    are combined with raw features and fed to XGBoost as a meta-learner.

    Parameters
    ----------
    seq_len : int
        Number of timesteps in each sequence (default: 30, matching demo.py).
    feature_dim : int
        Size of the extracted feature vector (default: 12).
    epochs : int
        Training epochs (default: 80).
    """

    def __init__(
        self,
        seq_len: int = 30,
        feature_dim: int = 12,
        epochs: int = 80,
        batch_size: int = 32,
        lr: float = 0.001,
    ) -> None:
        self.seq_len = seq_len
        self.feature_dim = feature_dim
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self._model: Any = None

    @staticmethod
    def create_sequences(data: np.ndarray, target: np.ndarray, seq_len: int = 30):
        """Create overlapping sequences from flat feature matrix."""
        X_seq, y_seq = [], []
        for i in range(seq_len, len(data)):
            X_seq.append(data[i - seq_len:i])
            y_seq.append(target[i])
        return np.array(X_seq), np.array(y_seq)

    def train(
        self,
        X_seq: np.ndarray,
        y_seq: np.ndarray,
        X_val_seq: np.ndarray | None = None,
        y_val_seq: np.ndarray | None = None,
    ) -> dict:
        """Train the GRU on sequence data with class weights and LR scheduling."""
        if not TORCH_AVAILABLE:
            raise RuntimeError("torch is not installed")

        torch.manual_seed(42)
        input_dim = X_seq.shape[2]
        self._model = _GRUFeatureNet(input_dim, feature_dim=self.feature_dim)

        optimizer = torch.optim.Adam(self._model.parameters(), lr=self.lr)
        criterion = nn.BCELoss()

        # Class weights
        num_pos = int(np.sum(y_seq == 1))
        num_neg = int(np.sum(y_seq == 0))
        pos_weight = num_neg / max(num_pos, 1)
        criterion = nn.BCEWithLogitsLoss(
            pos_weight=torch.tensor([pos_weight])
        )

        # Use raw logit output for BCEWithLogitsLoss — bypass sigmoid
        # So we need a slight change: use output before sigmoid
        # Actually, let's keep BCELoss with manual class weighting instead
        criterion = nn.BCELoss()
        sample_weights = np.where(y_seq == 1, len(y_seq) / (2 * num_pos), len(y_seq) / (2 * num_neg))

        X_t = torch.FloatTensor(X_seq)
        y_t = torch.FloatTensor(y_seq).unsqueeze(1)
        w_t = torch.FloatTensor(sample_weights)

        dataset = torch.utils.data.TensorDataset(X_t, y_t, w_t)
        loader = torch.utils.data.DataLoader(dataset, batch_size=self.batch_size, shuffle=False)

        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", factor=0.5, patience=5, min_lr=1e-6
        )

        best_val_acc = 0.0
        best_state = None
        patience_counter = 0

        self._model.train()
        for epoch in range(self.epochs):
            total_loss = 0
            for xb, yb, wb in loader:
                optimizer.zero_grad()
                out = self._model(xb)
                loss = (criterion(out, yb) * wb.unsqueeze(1)).mean()
                loss.backward()
                optimizer.step()
                total_loss += loss.item()

            avg_loss = total_loss / len(loader)
            scheduler.step(avg_loss)

            # Early stopping on validation
            if X_val_seq is not None and y_val_seq is not None:
                self._model.eval()
                with torch.no_grad():
                    val_out = self._model(torch.FloatTensor(X_val_seq))
                    val_preds = (val_out.squeeze().numpy() > 0.5).astype(int)
                    val_acc = float((val_preds == y_val_seq).mean())
                self._model.train()

                if val_acc > best_val_acc:
                    best_val_acc = val_acc
                    best_state = {k: v.clone() for k, v in self._model.state_dict().items()}
                    patience_counter = 0
                else:
                    patience_counter += 1
                    if patience_counter >= 15:
                        logger.info("GRU early stopping at epoch %d (best val_acc=%.4f)", epoch + 1, best_val_acc)
                        break

            if (epoch + 1) % 10 == 0:
                logger.info("GRU epoch %d/%d loss=%.4f", epoch + 1, self.epochs, avg_loss)

        if best_state is not None:
            self._model.load_state_dict(best_state)

        return {"best_val_acc": best_val_acc}

    def predict(self, X_seq: np.ndarray) -> np.ndarray:
        """Return binary predictions."""
        self._model.eval()
        with torch.no_grad():
            out = self._model(torch.FloatTensor(X_seq))
            return out.squeeze().numpy()

    def extract_features(self, X_seq: np.ndarray) -> np.ndarray:
        """Extract hidden features from the intermediate layer."""
        self._model.eval()
        with torch.no_grad():
            return self._model.extract_features(torch.FloatTensor(X_seq)).numpy()

    def save(self, path: str | Path) -> None:
        if not TORCH_AVAILABLE:
            return
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        torch.save(self._model.state_dict(), path / "gru_model.pt")
        meta = {"seq_len": self.seq_len, "feature_dim": self.feature_dim}
        (path / "gru_meta.json").write_text(json.dumps(meta, indent=2))

    def load(self, path: str | Path, input_dim: int) -> None:
        if not TORCH_AVAILABLE:
            raise RuntimeError("torch is not installed")
        path = Path(path)
        meta = json.loads((path / "gru_meta.json").read_text())
        self.seq_len = meta["seq_len"]
        self.feature_dim = meta["feature_dim"]
        self._model = _GRUFeatureNet(input_dim, feature_dim=self.feature_dim)
        state = torch.load(path / "gru_model.pt", map_location="cpu", weights_only=True)
        self._model.load_state_dict(state)
        self._model.eval()
