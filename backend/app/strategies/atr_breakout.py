from app.indicators.volatility import average_true_range
from app.market_data.models import Candle
from app.signals.models import TradeSignal


def generate_atr_breakout_signal(
    candles: list[Candle],
    breakout_period: int = 20,
    atr_period: int = 14,
    atr_multiplier: float = 0.25,
) -> TradeSignal:
    if breakout_period <= 0:
        raise ValueError("Breakout period must be greater than zero.")

    if atr_period <= 0:
        raise ValueError("ATR period must be greater than zero.")

    if atr_multiplier < 0:
        raise ValueError("ATR multiplier cannot be negative.")

    minimum_candles = max(
        breakout_period + 1,
        atr_period + 1,
    )

    if len(candles) < minimum_candles:
        raise ValueError(
            "Not enough candles to calculate ATR breakout signal."
        )

    current_candle = candles[-1]
    previous_channel = candles[-(breakout_period + 1):-1]

    previous_high = max(
        candle.high
        for candle in previous_channel
    )
    previous_low = min(
        candle.low
        for candle in previous_channel
    )

    atr = average_true_range(
        candles=candles,
        period=atr_period,
    )

    upper_breakout = previous_high + (atr * atr_multiplier)
    lower_breakout = previous_low - (atr * atr_multiplier)

    if current_candle.close > upper_breakout:
        direction = "BUY"
        reason = (
            "Close broke above the previous price channel "
            "with ATR confirmation."
        )
    elif current_candle.close < lower_breakout:
        direction = "SELL"
        reason = (
            "Close broke below the previous price channel "
            "with ATR confirmation."
        )
    else:
        direction = "HOLD"
        reason = "No ATR-confirmed channel breakout."

    return TradeSignal(
        symbol=current_candle.symbol,
        direction=direction,
        confidence=0.7 if direction != "HOLD" else 0.5,
        strategy_name="ATR Breakout",
        reason=reason,
    )
