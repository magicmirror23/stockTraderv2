def test_feed_status_endpoint(client):
    response = client.get("/api/v1/stream/feed-status")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] in {"live", "replay", "unavailable", "waking"}


def test_watchlist_endpoint(client):
    response = client.get("/api/v1/stream/watchlist")
    assert response.status_code == 200
    assert "data" in response.json()
