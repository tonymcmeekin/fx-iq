from app.indicators.moving_averages import exponential_moving_average
from app.market_data.models import Candle
from app.signals.models import TradeSignal


def generate_ema_crossover_signal(
    candles: list[Candle],
    fast_period: int = 3,
    slow_period: int = 5,
) -> TradeSignal:
    if fast_period >= slow_period:
        raise ValueError("Fast period must be less than slow period.")

    fast_ema = exponential_moving_average(candles, fast_period)
    slow_ema = exponential_moving_average(candles, slow_period)

    if fast_ema > slow_ema:
        direction = "BUY"
        reason = "Fast EMA is above slow EMA."
    elif fast_ema < slow_ema:
        direction = "SELL"
        reason = "Fast EMA is below slow EMA."
    else:
        direction = "HOLD"
        reason = "Fast EMA equals slow EMA."

    return TradeSignal(
        symbol=candles[-1].symbol,
        direction=direction,
        confidence=0.65,
        strategy_name="EMA Crossover",
        reason=reason,
    )
