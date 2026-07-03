from datetime import UTC, datetime

from app.market_data.models import Candle
from app.trading.simulator import simulate_multi_candle_trade


def make_candle(
    close: float,
    high: float | None = None,
    low: float | None = None,
) -> Candle:
    return Candle(
        symbol="EUR_USD",
        timeframe="H1",
        timestamp=datetime(2026, 7, 3, tzinfo=UTC),
        open=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
        volume=1000,
    )


def test_buy_take_profit_hit():
    trade = simulate_multi_candle_trade(
        candles=[
            make_candle(100.0),
            make_candle(101.0, high=102.5, low=100.5),
        ],
        direction="BUY",
        stop_loss_percent=1.0,
        take_profit_percent=2.0,
    )

    assert trade.exit_reason == "Take-profit hit."
    assert trade.exit_price == 102.0
    assert trade.profit_percent == 2.0


def test_buy_stop_loss_hit():
    trade = simulate_multi_candle_trade(
        candles=[
            make_candle(100.0),
            make_candle(99.0, high=100.5, low=98.5),
        ],
        direction="BUY",
        stop_loss_percent=1.0,
        take_profit_percent=2.0,
    )

    assert trade.exit_reason == "Stop-loss hit."
    assert trade.exit_price == 99.0
    assert trade.profit_percent == -1.0


def test_sell_take_profit_hit():
    trade = simulate_multi_candle_trade(
        candles=[
            make_candle(100.0),
            make_candle(98.0, high=99.5, low=97.5),
        ],
        direction="SELL",
        stop_loss_percent=1.0,
        take_profit_percent=2.0,
    )

    assert trade.exit_reason == "Take-profit hit."
    assert trade.exit_price == 98.0
    assert trade.profit_percent == 2.0


def test_sell_stop_loss_hit():
    trade = simulate_multi_candle_trade(
        candles=[
            make_candle(100.0),
            make_candle(101.0, high=101.5, low=99.5),
        ],
        direction="SELL",
        stop_loss_percent=1.0,
        take_profit_percent=2.0,
    )

    assert trade.exit_reason == "Stop-loss hit."
    assert trade.exit_price == 101.0
    assert trade.profit_percent == -1.0


def test_trade_closes_at_final_candle():
    trade = simulate_multi_candle_trade(
        candles=[
            make_candle(100.0),
            make_candle(100.5, high=100.8, low=99.8),
        ],
        direction="BUY",
        stop_loss_percent=1.0,
        take_profit_percent=2.0,
    )

    assert trade.exit_reason == "Closed at final candle."
    assert trade.exit_price == 100.5
    assert trade.profit_percent == 0.5
