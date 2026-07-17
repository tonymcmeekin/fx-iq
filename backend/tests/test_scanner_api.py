from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_scanner_opportunities_returns_ranked_markets():
    response = client.get("/scanner/opportunities")

    assert response.status_code == 200

    result = response.json()

    assert result["scanner_version"] == "1.0"
    assert result["evaluated_markets"] == 8
    assert len(result["opportunities"]) == 8

    assert [
        opportunity["rank"]
        for opportunity in result["opportunities"]
    ] == list(range(1, 9))


def test_scanner_opportunities_contains_allow_result():
    response = client.get("/scanner/opportunities")

    result = response.json()

    assert result["allow_count"] >= 1
    assert any(
        opportunity["decision"] == "ALLOW"
        for opportunity in result["opportunities"]
    )


def test_scanner_opportunities_is_read_only():
    response = client.get("/scanner/opportunities")

    assert response.status_code == 200

    result = response.json()

    assert result["paper_trading_only"] is True
    assert result["live_trading_allowed"] is False
    assert result["broker_orders_submitted"] == 0
    assert result["network_calls_made"] == 0
    assert result["ledger_writes_performed"] == 0

    for opportunity in result["opportunities"]:
        assert opportunity["paper_trading_only"] is True
        assert opportunity["live_trading_allowed"] is False
        assert opportunity["broker_orders_submitted"] == 0
        assert opportunity["network_calls_made"] == 0
        assert opportunity["ledger_writes_performed"] == 0


def test_scanner_opportunities_are_decision_ranked():
    response = client.get("/scanner/opportunities")

    result = response.json()

    priorities = {
        "ALLOW": 0,
        "WATCH": 1,
        "REJECT": 2,
    }

    actual_priorities = [
        priorities[opportunity["decision"]]
        for opportunity in result["opportunities"]
    ]

    assert actual_priorities == sorted(actual_priorities)
