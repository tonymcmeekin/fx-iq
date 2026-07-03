from datetime import UTC, datetime

from app.market_data.models import Candle
from app.trading.simulator import simulate_one_candle_trade


def make_candle(close: float) -> Candle:
    return Candle(
        symbol="EUR_USD",
        timeframe="H1",
        timestamp=datetime(2026, 7, 3, tzinfo=UTC),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
    )


def test_buy_trade_profit():
    trade = simulate_one_candle_trade(
        previous_candle=make_candle(100.0),
        current_candle=make_candle(110.0),
        direction="BUY",
    )

    assert trade.direction == "BUY"
    assert trade.entry_price == 100.0
    assert trade.exit_price == 110.0
    assert trade.profit_percent == 10.0


def test_sell_trade_profit():
    trade = simulate_one_candle_trade(
        previous_candle=make_candle(100.0),
        current_candle=make_candle(90.0),
        direction="SELL",
    )

    assert trade.direction == "SELL"
    assert trade.profit_percent == 10.0


def test_hold_trade_has_zero_profit():
    trade = simulate_one_candle_trade(
        previous_candle=make_candle(100.0),
        current_candle=make_candle(110.0),
        direction="HOLD",
    )

    assert trade.direction == "HOLD"
    assert trade.profit_percent == 0.0
