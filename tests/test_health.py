def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_ready_checks_database(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ready"}
