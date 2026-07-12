from datetime import UTC, datetime, timedelta

from app.backtesting.engine import run_strategy_backtest
from app.market_data.models import Candle


def make_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2026, 7, 3, 8, tzinfo=UTC)

    return [
        Candle(
            symbol="EUR_USD",
            timeframe="H1",
            timestamp=start + timedelta(hours=index),
            open=close,
            high=close * 1.001,
            low=close * 0.999,
            close=close,
            volume=1000,
        )
        for index, close in enumerate(closes)
    ]


def test_backtest_does_not_create_overlapping_trades():
    candles = make_candles(
        [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    )

    result = run_strategy_backtest(
        strategy_name="simple_trend",
        candles=candles,
        stop_loss_percent=50.0,
        take_profit_percent=50.0,
    )

    assert result.total_trades == 1
    assert result.trades[0].candles_held == 3


def test_backtest_rejects_empty_candle_list():
    try:
        run_strategy_backtest("simple_trend", [])
    except ValueError as error:
        assert str(error) == "At least one candle is required."
    else:
        raise AssertionError("Expected ValueError for empty candle list.")


def test_backtest_enters_after_signal_candle():
    candles = make_candles(
        [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    )

    result = run_strategy_backtest(
        strategy_name="simple_trend",
        candles=candles,
        stop_loss_percent=50.0,
        take_profit_percent=50.0,
    )

    assert result.total_trades == 1

    # The BUY signal is generated after the second candle closes at 101.
    # A realistic backtest must enter on the following candle, not at 101.
    assert result.trades[0].entry_price == 102.0


def test_backtest_enters_at_next_candle_open():
    start = datetime(2026, 7, 3, 8, tzinfo=UTC)

    candles = [
        Candle(
            symbol="EUR_USD",
            timeframe="H1",
            timestamp=start,
            open=100.0,
            high=100.1,
            low=99.9,
            close=100.0,
            volume=1000,
        ),
        Candle(
            symbol="EUR_USD",
            timeframe="H1",
            timestamp=start + timedelta(hours=1),
            open=100.0,
            high=101.1,
            low=99.9,
            close=101.0,
            volume=1000,
        ),
        Candle(
            symbol="EUR_USD",
            timeframe="H1",
            timestamp=start + timedelta(hours=2),
            open=110.0,
            high=110.5,
            low=109.5,
            close=110.0,
            volume=1000,
        ),
        Candle(
            symbol="EUR_USD",
            timeframe="H1",
            timestamp=start + timedelta(hours=3),
            open=110.0,
            high=110.5,
            low=109.5,
            close=110.0,
            volume=1000,
        ),
    ]

    result = run_strategy_backtest(
        strategy_name="simple_trend",
        candles=candles,
        stop_loss_percent=50.0,
        take_profit_percent=50.0,
    )

    assert result.total_trades == 1
    assert result.trades[0].entry_price == 110.0

def test_backtest_can_filter_trade_direction():
    candles = make_candles(
        [100.0, 101.0, 102.0, 101.0, 100.0, 99.0, 98.0]
    )

    buy_only = run_strategy_backtest(
        strategy_name="simple_trend",
        candles=candles,
        stop_loss_percent=50.0,
        take_profit_percent=50.0,
        allowed_directions={"BUY"},
    )

    sell_only = run_strategy_backtest(
        strategy_name="simple_trend",
        candles=candles,
        stop_loss_percent=50.0,
        take_profit_percent=50.0,
        allowed_directions={"SELL"},
    )

    assert all(
        trade.direction == "BUY"
        for trade in buy_only.trades
    )
    assert all(
        trade.direction == "SELL"
        for trade in sell_only.trades
    )


def test_backtest_rejects_invalid_direction_filter():
    candles = make_candles([100.0, 101.0, 102.0])

    try:
        run_strategy_backtest(
            strategy_name="simple_trend",
            candles=candles,
            allowed_directions={"HOLD"},
        )
    except ValueError as error:
        assert str(error) == (
            "Allowed directions must contain only BUY or SELL."
        )
    else:
        raise AssertionError(
            "Expected invalid direction filter to be rejected."
        )

