from app.market_data.models import Candle
from app.trading.models import SimulatedTrade


def calculate_profit_percent(direction: str, entry_price: float, exit_price: float) -> float:
    if direction == "BUY":
        return ((exit_price - entry_price) / entry_price) * 100

    if direction == "SELL":
        return ((entry_price - exit_price) / entry_price) * 100

    return 0.0


def simulate_multi_candle_trade(
    candles: list[Candle],
    direction: str,
    stop_loss_percent: float = 1.0,
    take_profit_percent: float = 2.0,
) -> SimulatedTrade:
    if len(candles) < 2:
        raise ValueError("At least two candles are required.")

    entry_candle = candles[0]
    entry_price = entry_candle.close

    if direction == "BUY":
        stop_loss = entry_price * (1 - stop_loss_percent / 100)
        take_profit = entry_price * (1 + take_profit_percent / 100)
    elif direction == "SELL":
        stop_loss = entry_price * (1 + stop_loss_percent / 100)
        take_profit = entry_price * (1 - take_profit_percent / 100)
    else:
        return SimulatedTrade(
            symbol=entry_candle.symbol,
            direction=direction,
            entry_price=entry_price,
            exit_price=entry_price,
            profit_percent=0.0,
            exit_reason="No trade.",
            stop_loss=None,
            take_profit=None,
            candles_held=0,
        )

    for index, candle in enumerate(candles[1:], start=1):
        if direction == "BUY":
            if candle.low <= stop_loss:
                exit_price = stop_loss
                exit_reason = "Stop-loss hit."
                candles_held = index
                break

            if candle.high >= take_profit:
                exit_price = take_profit
                exit_reason = "Take-profit hit."
                candles_held = index
                break

        if direction == "SELL":
            if candle.high >= stop_loss:
                exit_price = stop_loss
                exit_reason = "Stop-loss hit."
                candles_held = index
                break

            if candle.low <= take_profit:
                exit_price = take_profit
                exit_reason = "Take-profit hit."
                candles_held = index
                break
    else:
        final_candle = candles[-1]
        exit_price = final_candle.close
        exit_reason = "Closed at final candle."
        candles_held = len(candles) - 1

    profit_percent = calculate_profit_percent(direction, entry_price, exit_price)

    return SimulatedTrade(
        symbol=entry_candle.symbol,
        direction=direction,
        entry_price=round(entry_price, 6),
        exit_price=round(exit_price, 6),
        profit_percent=round(profit_percent, 6),
        exit_reason=exit_reason,
        stop_loss=round(stop_loss, 6),
        take_profit=round(take_profit, 6),
        candles_held=candles_held,
    )


def simulate_one_candle_trade(
    previous_candle: Candle,
    current_candle: Candle,
    direction: str,
) -> SimulatedTrade:
    return simulate_multi_candle_trade(
        candles=[previous_candle, current_candle],
        direction=direction,
        stop_loss_percent=100.0,
        take_profit_percent=100.0,
    )
