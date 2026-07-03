from app.market_data.models import Candle
from app.trading.models import SimulatedTrade


def simulate_one_candle_trade(
    previous_candle: Candle,
    current_candle: Candle,
    direction: str,
) -> SimulatedTrade:
    if direction == "BUY":
        profit_percent = (
            (current_candle.close - previous_candle.close) / previous_candle.close
        ) * 100
    elif direction == "SELL":
        profit_percent = (
            (previous_candle.close - current_candle.close) / previous_candle.close
        ) * 100
    else:
        profit_percent = 0.0

    return SimulatedTrade(
        symbol=current_candle.symbol,
        direction=direction,
        entry_price=previous_candle.close,
        exit_price=current_candle.close,
        profit_percent=round(profit_percent, 6),
        exit_reason="One-candle simulation exit.",
    )
