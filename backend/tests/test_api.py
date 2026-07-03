from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_sample_signal():
    response = client.get("/signals/sample")
    assert response.status_code == 200
    assert response.json()["symbol"] == "EUR_USD"


def test_sample_risk_check():
    response = client.get("/risk/sample-check")
    assert response.status_code == 200
    assert response.json()["approved"] is True
