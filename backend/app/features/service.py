from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.features.calculations import (
    average_true_range,
    exponential_moving_average,
    percentage_change,
    range_position,
    relative_strength_index,
)
from app.features.models import (
    MarketFeatureVector,
    TrendState,
    VolatilityState,
)


@dataclass(frozen=True)
class FeatureCandle:
    high: float
    low: float
    close: float


def build_market_features(
    candles: Sequence[FeatureCandle],
) -> MarketFeatureVector:
    candle_count = len(candles)

    if candle_count == 0:
        return MarketFeatureVector(
            candle_count=0,
            latest_close=None,
            price_change_percent=None,
            ema_20=None,
            ema_50=None,
            ema_alignment="INSUFFICIENT_DATA",
            ema_20_slope_percent=None,
            atr_14=None,
            atr_percent=None,
            rsi_14=None,
            recent_high=None,
            recent_low=None,
            range_position=None,
            trend_state=TrendState.INSUFFICIENT_DATA,
            volatility_state=VolatilityState.INSUFFICIENT_DATA,
        )

    highs = [candle.high for candle in candles]
    lows = [candle.low for candle in candles]
    closes = [candle.close for candle in candles]

    latest_close = closes[-1]
    ema_20 = exponential_moving_average(closes, 20)
    ema_50 = exponential_moving_average(closes, 50)
    atr_14 = average_true_range(
        highs,
        lows,
        closes,
        14,
    )
    rsi_14 = relative_strength_index(closes, 14)

    previous_ema_20 = (
        exponential_moving_average(closes[:-5], 20)
        if len(closes) >= 25
        else None
    )

    ema_20_slope_percent = (
        percentage_change(previous_ema_20, ema_20)
        if previous_ema_20 is not None
        and ema_20 is not None
        else None
    )

    atr_percent = (
        (atr_14 / latest_close) * 100.0
        if atr_14 is not None
        and latest_close != 0
        else None
    )

    lookback = min(20, candle_count)
    recent_high = max(highs[-lookback:])
    recent_low = min(lows[-lookback:])

    current_range_position = range_position(
        latest_close,
        recent_low,
        recent_high,
    )

    if ema_20 is None or ema_50 is None:
        ema_alignment = "INSUFFICIENT_DATA"
        trend_state = TrendState.INSUFFICIENT_DATA
    elif ema_20 > ema_50 and latest_close > ema_20:
        ema_alignment = "BULLISH"
        trend_state = TrendState.TRENDING_UP
    elif ema_20 < ema_50 and latest_close < ema_20:
        ema_alignment = "BEARISH"
        trend_state = TrendState.TRENDING_DOWN
    else:
        ema_alignment = "MIXED"
        trend_state = TrendState.RANGING

    if atr_percent is None:
        volatility_state = (
            VolatilityState.INSUFFICIENT_DATA
        )
    elif atr_percent < 0.08:
        volatility_state = VolatilityState.LOW
    elif atr_percent > 0.30:
        volatility_state = VolatilityState.HIGH
    else:
        volatility_state = VolatilityState.NORMAL

    return MarketFeatureVector(
        candle_count=candle_count,
        latest_close=latest_close,
        price_change_percent=percentage_change(
            closes[0],
            latest_close,
        ),
        ema_20=ema_20,
        ema_50=ema_50,
        ema_alignment=ema_alignment,
        ema_20_slope_percent=ema_20_slope_percent,
        atr_14=atr_14,
        atr_percent=atr_percent,
        rsi_14=rsi_14,
        recent_high=recent_high,
        recent_low=recent_low,
        range_position=current_range_position,
        trend_state=trend_state,
        volatility_state=volatility_state,
    )
