from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def candle_payloads() -> list[dict]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = []

    for index in range(50):
        close = 1.1000 + index * 0.0006
        candles.append(
            {
                "symbol": "EUR_USD",
                "timeframe": "H1",
                "timestamp": (start + timedelta(hours=index)).isoformat(),
                "open": close - 0.0002,
                "high": close + 0.0003,
                "low": close - 0.0003,
                "close": close,
                "volume": 1000 + index,
            }
        )

    previous_high = max(candle["high"] for candle in candles[-20:])
    breakout_close = previous_high + 0.0010

    candles.append(
        {
            "symbol": "EUR_USD",
            "timeframe": "H1",
            "timestamp": (start + timedelta(hours=50)).isoformat(),
            "open": breakout_close - 0.0004,
            "high": breakout_close + 0.0003,
            "low": breakout_close - 0.0005,
            "close": breakout_close,
            "volume": 1400,
        }
    )

    return candles


def test_decision_evaluate_api_is_read_only():
    candles = candle_payloads()
    entry = candles[-1]["close"]

    response = client.post(
        "/decision/evaluate",
        json={
            "strategy_name": "atr_breakout",
            "candles": candles,
            "entry_price": entry,
            "stop_loss": entry - 0.0020,
            "take_profit": entry + 0.0040,
            "base_risk_percent": 0.5,
        },
    )

    assert response.status_code == 200

    result = response.json()

    assert result["decision"] == "ALLOW"
    assert result["approved_for_paper_trade"] is True
    assert result["paper_trading_only"] is True
    assert result["live_trading_allowed"] is False
    assert result["broker_orders_submitted"] == 0
    assert result["network_calls_made"] == 0
    assert result["ledger_writes_performed"] == 0


def test_decision_evaluate_rejects_unknown_strategy():
    candles = candle_payloads()
    entry = candles[-1]["close"]

    response = client.post(
        "/decision/evaluate",
        json={
            "strategy_name": "unknown_strategy",
            "candles": candles,
            "entry_price": entry,
            "stop_loss": entry - 0.0020,
            "take_profit": entry + 0.0040,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["status"] == "REJECTED"
    assert response.json()["detail"]["live_trading_allowed"] is False
