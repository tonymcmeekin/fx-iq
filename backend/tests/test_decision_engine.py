from datetime import UTC, datetime, timedelta

from app.decision.engine import evaluate_trade_decision
from app.decision.models import DecisionEvaluationRequest
from app.market_data.models import Candle


def trending_breakout_candles() -> list[Candle]:
    candles: list[Candle] = []
    start = datetime(2026, 1, 1, tzinfo=UTC)

    for index in range(50):
        close = 1.1000 + index * 0.0006
        candles.append(
            Candle(
                symbol="EUR_USD",
                timeframe="H1",
                timestamp=start + timedelta(hours=index),
                open=close - 0.0002,
                high=close + 0.0003,
                low=close - 0.0003,
                close=close,
                volume=1000 + index,
            )
        )

    previous_high = max(candle.high for candle in candles[-20:])
    breakout_close = previous_high + 0.0010

    candles.append(
        Candle(
            symbol="EUR_USD",
            timeframe="H1",
            timestamp=start + timedelta(hours=50),
            open=breakout_close - 0.0004,
            high=breakout_close + 0.0003,
            low=breakout_close - 0.0005,
            close=breakout_close,
            volume=1400,
        )
    )

    return candles


def test_decision_engine_allows_strong_paper_setup():
    candles = trending_breakout_candles()
    entry = candles[-1].close

    result = evaluate_trade_decision(
        DecisionEvaluationRequest(
            strategy_name="atr_breakout",
            candles=candles,
            entry_price=entry,
            stop_loss=entry - 0.0020,
            take_profit=entry + 0.0040,
        )
    )

    assert result.direction == "BUY"
    assert result.decision == "ALLOW"
    assert result.approved_for_paper_trade is True
    assert result.confidence_score >= 70
    assert result.blocking_reasons == []
    assert result.live_trading_allowed is False
    assert result.broker_orders_submitted == 0


def test_decision_engine_rejects_invalid_stop_geometry():
    candles = trending_breakout_candles()
    entry = candles[-1].close

    result = evaluate_trade_decision(
        DecisionEvaluationRequest(
            strategy_name="atr_breakout",
            candles=candles,
            entry_price=entry,
            stop_loss=entry + 0.0010,
            take_profit=entry + 0.0040,
        )
    )

    assert result.decision == "REJECT"
    assert result.approved_for_paper_trade is False
    assert any("stop-loss" in reason for reason in result.blocking_reasons)


def test_decision_engine_rejects_inadequate_reward():
    candles = trending_breakout_candles()
    entry = candles[-1].close

    result = evaluate_trade_decision(
        DecisionEvaluationRequest(
            strategy_name="atr_breakout",
            candles=candles,
            entry_price=entry,
            stop_loss=entry - 0.0020,
            take_profit=entry + 0.0010,
        )
    )

    assert result.decision == "REJECT"
    assert any("risk/reward" in reason for reason in result.blocking_reasons)
