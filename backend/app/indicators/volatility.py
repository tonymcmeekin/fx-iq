from app.market_data.models import Candle


def true_range(
    current_candle: Candle,
    previous_close: float,
) -> float:
    return max(
        current_candle.high - current_candle.low,
        abs(current_candle.high - previous_close),
        abs(current_candle.low - previous_close),
    )


def average_true_range(
    candles: list[Candle],
    period: int = 14,
) -> float:
    if period <= 0:
        raise ValueError("ATR period must be greater than zero.")

    if len(candles) < period + 1:
        raise ValueError("Not enough candles to calculate ATR.")

    selected = candles[-(period + 1):]
    ranges = [
        true_range(
            current_candle=selected[index],
            previous_close=selected[index - 1].close,
        )
        for index in range(1, len(selected))
    ]

    return round(sum(ranges) / period, 6)
