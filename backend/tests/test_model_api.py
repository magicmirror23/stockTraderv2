from __future__ import annotations


def test_model_metadata_endpoint_returns_extended_fields(client, monkeypatch):
    from backend.services.model_manager import ModelManager

    monkeypatch.setattr(
        ModelManager,
        "get_model_metadata",
        lambda self: {
            "model_version": "v-test",
            "status": "loaded",
            "last_trained": "2026-03-19T10:00:00+00:00",
            "accuracy": 0.74,
            "fallback": False,
            "last_error": None,
            "registry_latest": "v-test",
            "trained_model_available": True,
            "artifact_path": "models/artifacts/v-test",
            "feature_set_version": "abc123",
            "feature_count": 42,
            "training_data_snapshot_id": "snap123",
            "calibration_status": "not_reported",
            "calibration_score": None,
            "explainability_mode": "shap_optional",
            "mlflow_enabled": False,
            "shap_enabled": True,
            "signal_policy": {"buy_threshold": 0.54},
            "metrics": {"test_accuracy": 0.74},
        },
    )

    response = client.get("/api/v1/model/metadata")

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_version"] == "v-test"
    assert payload["feature_set_version"] == "abc123"
    assert payload["shap_enabled"] is True
    assert payload["signal_policy"]["buy_threshold"] == 0.54


def test_model_status_endpoint_includes_fallback_state(client, monkeypatch):
    from backend.services.model_manager import ModelManager

    monkeypatch.setattr(
        ModelManager,
        "get_model_info",
        lambda self: {
            "model_version": "demo-fallback",
            "status": "demo_fallback",
            "last_trained": None,
            "accuracy": None,
            "fallback": True,
            "last_error": "artifact_missing",
        },
    )

    response = client.get("/api/v1/model/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["fallback"] is True
    assert payload["last_error"] == "artifact_missing"
