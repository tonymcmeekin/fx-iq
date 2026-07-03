from app.market_data.models import Candle


def simple_moving_average(candles: list[Candle], period: int) -> float:
    if period <= 0:
        raise ValueError("Period must be greater than zero.")

    if len(candles) < period:
        raise ValueError("Not enough candles to calculate simple moving average.")

    selected_candles = candles[-period:]
    total_close = sum(candle.close for candle in selected_candles)

    return round(total_close / period, 6)


def exponential_moving_average(candles: list[Candle], period: int) -> float:
    if period <= 0:
        raise ValueError("Period must be greater than zero.")

    if len(candles) < period:
        raise ValueError("Not enough candles to calculate exponential moving average.")

    multiplier = 2 / (period + 1)
    ema = simple_moving_average(candles[:period], period)

    for candle in candles[period:]:
        ema = (candle.close - ema) * multiplier + ema

    return round(ema, 6)
