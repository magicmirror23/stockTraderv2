"""Health and deployment-status tests."""


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "StockTrader API"


def test_health_returns_200(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_info_exposes_modes(client):
    response = client.get("/api/v1/health/info")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "feed_mode" in body
    assert "model_status" in body
