from typing import Literal

from pydantic import BaseModel

from app.market_data.models import Candle

TrendRegime = Literal[
    "TRENDING_UP",
    "TRENDING_DOWN",
    "RANGING",
]

VolatilityRegime = Literal[
    "LOW",
    "NORMAL",
    "HIGH",
]


class MarketRegime(BaseModel):
    trend: TrendRegime
    volatility: VolatilityRegime
    confidence: float
    price_change_percent: float
    volatility_ratio: float
    candles_analysed: int


def _average_range_percent(candles: list[Candle]) -> float:
    range_percentages = [
        (
            (candle.high - candle.low)
            / candle.close
            * 100
        )
        for candle in candles
        if candle.close > 0
    ]

    if not range_percentages:
        return 0.0

    return sum(range_percentages) / len(range_percentages)


def detect_market_regime(
    candles: list[Candle],
    lookback: int = 50,
    recent_volatility_window: int = 10,
    trend_threshold_percent: float = 2.0,
) -> MarketRegime:
    if lookback < 2:
        raise ValueError("Lookback must be at least two candles.")

    if recent_volatility_window < 2:
        raise ValueError(
            "Recent volatility window must be at least two candles."
        )

    if recent_volatility_window > lookback:
        raise ValueError(
            "Recent volatility window cannot exceed lookback."
        )

    if trend_threshold_percent <= 0:
        raise ValueError(
            "Trend threshold percent must be greater than zero."
        )

    if len(candles) < lookback:
        raise ValueError(
            f"At least {lookback} candles are required."
        )

    sample = candles[-lookback:]

    first_close = sample[0].close
    last_close = sample[-1].close

    price_change_percent = (
        (last_close - first_close)
        / first_close
        * 100
    )

    if price_change_percent >= trend_threshold_percent:
        trend: TrendRegime = "TRENDING_UP"
    elif price_change_percent <= -trend_threshold_percent:
        trend = "TRENDING_DOWN"
    else:
        trend = "RANGING"

    baseline_volatility = _average_range_percent(sample)

    recent_candles = sample[-recent_volatility_window:]
    recent_volatility = _average_range_percent(recent_candles)

    volatility_ratio = (
        recent_volatility / baseline_volatility
        if baseline_volatility > 0
        else 1.0
    )

    if volatility_ratio >= 1.25:
        volatility: VolatilityRegime = "HIGH"
    elif volatility_ratio <= 0.75:
        volatility = "LOW"
    else:
        volatility = "NORMAL"

    trend_strength = (
        abs(price_change_percent)
        / trend_threshold_percent
    )

    confidence = min(trend_strength, 1.0)

    if trend == "RANGING":
        confidence = max(
            0.0,
            1.0 - trend_strength,
        )

    return MarketRegime(
        trend=trend,
        volatility=volatility,
        confidence=round(confidence, 4),
        price_change_percent=round(
            price_change_percent,
            4,
        ),
        volatility_ratio=round(
            volatility_ratio,
            4,
        ),
        candles_analysed=lookback,
    )
