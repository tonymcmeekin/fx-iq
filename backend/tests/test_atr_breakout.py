from datetime import UTC, datetime, timedelta

import pytest

from app.indicators.volatility import average_true_range
from app.market_data.models import Candle
from app.strategies.atr_breakout import generate_atr_breakout_signal
from app.strategies.manager import list_available_strategy_names


def make_candles(
    closes: list[float],
    range_size: float = 0.5,
) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)

    return [
        Candle(
            symbol="EUR_USD",
            timeframe="D",
            timestamp=start + timedelta(days=index),
            open=close,
            high=close + range_size,
            low=close - range_size,
            close=close,
            volume=1000,
        )
        for index, close in enumerate(closes)
    ]


def test_average_true_range():
    candles = make_candles(
        [100.0, 101.0, 102.0, 103.0],
        range_size=0.5,
    )

    assert average_true_range(candles, period=3) == 1.5


def test_atr_breakout_generates_buy_signal():
    closes = [100.0] * 20 + [102.0]
    candles = make_candles(closes)

    signal = generate_atr_breakout_signal(
        candles,
        breakout_period=20,
        atr_period=14,
        atr_multiplier=0.25,
    )

    assert signal.direction == "BUY"


def test_atr_breakout_generates_sell_signal():
    closes = [100.0] * 20 + [98.0]
    candles = make_candles(closes)

    signal = generate_atr_breakout_signal(
        candles,
        breakout_period=20,
        atr_period=14,
        atr_multiplier=0.25,
    )

    assert signal.direction == "SELL"


def test_atr_breakout_holds_without_breakout():
    closes = [100.0] * 21
    candles = make_candles(closes)

    signal = generate_atr_breakout_signal(candles)

    assert signal.direction == "HOLD"


def test_atr_breakout_requires_enough_candles():
    with pytest.raises(
        ValueError,
        match="Not enough candles",
    ):
        generate_atr_breakout_signal(
            make_candles([100.0] * 10)
        )


def test_atr_breakout_is_registered():
    assert "atr_breakout" in list_available_strategy_names()
