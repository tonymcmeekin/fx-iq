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


def test_backtesting_api_accepts_trading_parameters():
    response = client.get(
        "/backtesting/run/ema_crossover",
        params={
            "stop_loss_percent": 2.0,
            "take_profit_percent": 0.5,
            "spread_pips": 1.0,
            "commission_percent": 0.01,
        },
    )

    assert response.status_code == 200

    result = response.json()

    assert result["strategy_name"] == "ema_crossover"
    assert result["total_trades"] > 0
    assert result["trades"]

    first_trade = result["trades"][0]

    assert first_trade["spread_pips"] == 1.0
    assert first_trade["commission_percent"] == 0.01
    assert first_trade["trading_cost_percent"] > 0


def test_backtesting_api_rejects_negative_spread():
    response = client.get(
        "/backtesting/run/simple_trend",
        params={"spread_pips": -1.0},
    )

    assert response.status_code == 422


def test_backtesting_api_rejects_zero_stop_loss():
    response = client.get(
        "/backtesting/run/simple_trend",
        params={"stop_loss_percent": 0.0},
    )

    assert response.status_code == 422


def test_backtesting_api_returns_400_for_unknown_strategy():
    response = client.get(
        "/backtesting/run/not_a_strategy",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown strategy: not_a_strategy"
