def test_predict_endpoint_returns_explanation_payload(client):
    response = client.post("/api/v1/predict", json={"ticker": "RELIANCE", "horizon_days": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["prediction"]["model_version"]
    assert body["prediction"]["action"] in {"buy", "sell", "hold"}
    assert body["prediction"]["explanation"]["summary"]
    assert body["prediction"]["explanation"]["drivers"]


def test_batch_predict_works_in_demo_mode(client):
    response = client.post("/api/v1/batch_predict", json={"tickers": ["RELIANCE", "TCS"], "horizon_days": 1})
    assert response.status_code == 200
    body = response.json()
    assert len(body["predictions"]) == 2
    assert all("explanation" in prediction for prediction in body["predictions"])
