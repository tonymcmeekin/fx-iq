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
    assert result.trades[0].candles_held == 4


def test_backtest_rejects_empty_candle_list():
    try:
        run_strategy_backtest("simple_trend", [])
    except ValueError as error:
        assert str(error) == "At least one candle is required."
    else:
        raise AssertionError("Expected ValueError for empty candle list.")
