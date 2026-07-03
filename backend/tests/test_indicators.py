from datetime import UTC, datetime

import pytest

from app.indicators.moving_averages import simple_moving_average
from app.market_data.models import Candle


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


def test_simple_moving_average():
    candles = [
        make_candle(1.0),
        make_candle(2.0),
        make_candle(3.0),
        make_candle(4.0),
        make_candle(5.0),
    ]

    result = simple_moving_average(candles, period=3)

    assert result == 4.0


def test_simple_moving_average_requires_positive_period():
    candles = [make_candle(1.0)]

    with pytest.raises(ValueError):
        simple_moving_average(candles, period=0)


def test_simple_moving_average_requires_enough_candles():
    candles = [make_candle(1.0)]

    with pytest.raises(ValueError):
        simple_moving_average(candles, period=3)
