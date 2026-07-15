from datetime import UTC, datetime, timedelta

import pytest

from app.ai.regime import detect_market_regime
from app.market_data.models import Candle


def make_candles(
    closes: list[float],
    range_percent: float = 1.0,
) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)

    candles = []

    for index, close in enumerate(closes):
        half_range = close * range_percent / 200

        candles.append(
            Candle(
                symbol="EUR_USD",
                timeframe="D",
                timestamp=start + timedelta(days=index),
                open=close,
                high=close + half_range,
                low=close - half_range,
                close=close,
                volume=1000,
            )
        )

    return candles


def test_detects_upward_trend():
    closes = [
        100 + index * 0.2
        for index in range(50)
    ]

    regime = detect_market_regime(
        make_candles(closes),
    )

    assert regime.trend == "TRENDING_UP"
    assert regime.confidence == 1.0
    assert regime.candles_analysed == 50


def test_detects_downward_trend():
    closes = [
        110 - index * 0.2
        for index in range(50)
    ]

    regime = detect_market_regime(
        make_candles(closes),
    )

    assert regime.trend == "TRENDING_DOWN"
    assert regime.confidence == 1.0


def test_detects_ranging_market():
    closes = [
        100.0 if index % 2 == 0 else 100.2
        for index in range(50)
    ]

    regime = detect_market_regime(
        make_candles(closes),
    )

    assert regime.trend == "RANGING"
    assert regime.confidence >= 0.9


def test_detects_high_recent_volatility():
    candles = make_candles(
        [100.0 for _ in range(50)],
        range_percent=1.0,
    )

    for index in range(40, 50):
        close = candles[index].close

        candles[index] = candles[index].model_copy(
            update={
                "high": close * 1.02,
                "low": close * 0.98,
            }
        )

    regime = detect_market_regime(candles)

    assert regime.volatility == "HIGH"
    assert regime.volatility_ratio > 1.25


def test_rejects_insufficient_history():
    with pytest.raises(
        ValueError,
        match="At least 50 candles are required.",
    ):
        detect_market_regime(
            make_candles([100.0] * 49),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "lookback",
            1,
            "Lookback must be at least two candles.",
        ),
        (
            "recent_volatility_window",
            1,
            (
                "Recent volatility window must be "
                "at least two candles."
            ),
        ),
        (
            "trend_threshold_percent",
            0.0,
            (
                "Trend threshold percent must be "
                "greater than zero."
            ),
        ),
    ],
)
def test_rejects_invalid_settings(
    field,
    value,
    message,
):
    arguments = {
        "candles": make_candles([100.0] * 50),
    }
    arguments[field] = value

    with pytest.raises(ValueError, match=message):
        detect_market_regime(**arguments)
