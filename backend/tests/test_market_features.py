from __future__ import annotations

import pytest

from app.features import (
    FeatureCandle,
    TrendState,
    VolatilityState,
    build_market_features,
)


def make_trending_candles(
    count: int = 80,
) -> list[FeatureCandle]:
    candles: list[FeatureCandle] = []

    for index in range(count):
        close = 1.1000 + (index * 0.0005)

        candles.append(
            FeatureCandle(
                high=close + 0.0003,
                low=close - 0.0003,
                close=close,
            )
        )

    return candles


def make_falling_candles(
    count: int = 80,
) -> list[FeatureCandle]:
    candles: list[FeatureCandle] = []

    for index in range(count):
        close = 1.2000 - (index * 0.0005)

        candles.append(
            FeatureCandle(
                high=close + 0.0003,
                low=close - 0.0003,
                close=close,
            )
        )

    return candles


def test_empty_candles_return_insufficient_data() -> None:
    features = build_market_features([])

    assert features.candle_count == 0
    assert features.latest_close is None
    assert features.trend_state is TrendState.INSUFFICIENT_DATA
    assert (
        features.volatility_state
        is VolatilityState.INSUFFICIENT_DATA
    )


def test_feature_engine_detects_uptrend() -> None:
    features = build_market_features(
        make_trending_candles()
    )

    assert features.candle_count == 80
    assert features.ema_20 is not None
    assert features.ema_50 is not None
    assert features.ema_20 > features.ema_50
    assert features.ema_alignment == "BULLISH"
    assert features.trend_state is TrendState.TRENDING_UP
    assert features.rsi_14 == pytest.approx(100.0)
    assert features.atr_14 is not None
    assert features.atr_percent is not None


def test_feature_engine_detects_downtrend() -> None:
    features = build_market_features(
        make_falling_candles()
    )

    assert features.ema_20 is not None
    assert features.ema_50 is not None
    assert features.ema_20 < features.ema_50
    assert features.ema_alignment == "BEARISH"
    assert features.trend_state is TrendState.TRENDING_DOWN
    assert features.rsi_14 == pytest.approx(0.0)


def test_feature_engine_range_position_is_bounded() -> None:
    features = build_market_features(
        make_trending_candles()
    )

    assert features.range_position is not None
    assert 0.0 <= features.range_position <= 1.0


def test_feature_engine_is_deterministic() -> None:
    candles = make_trending_candles()

    first = build_market_features(candles)
    second = build_market_features(candles)

    assert first == second
