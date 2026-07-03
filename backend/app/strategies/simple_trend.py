from app.market_data.models import Candle
from app.signals.models import TradeSignal


def generate_simple_trend_signal(candles: list[Candle]) -> TradeSignal:
    first_close = candles[0].close
    last_close = candles[-1].close

    if last_close > first_close:
        direction = "BUY"
        reason = "Price closed higher than it started."
    elif last_close < first_close:
        direction = "SELL"
        reason = "Price closed lower than it started."
    else:
        direction = "HOLD"
        reason = "Price is unchanged."

    return TradeSignal(
        symbol=candles[-1].symbol,
        direction=direction,
        confidence=0.6,
        strategy_name="Simple Trend",
        reason=reason,
    )
