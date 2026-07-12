from app.market_data.models import Candle
from app.trading.models import SimulatedTrade


def calculate_profit_percent(
    direction: str,
    entry_price: float,
    exit_price: float,
) -> float:
    if direction == "BUY":
        return ((exit_price - entry_price) / entry_price) * 100

    if direction == "SELL":
        return ((entry_price - exit_price) / entry_price) * 100

    return 0.0


def calculate_trading_cost_percent(
    entry_price: float,
    spread_pips: float = 0.0,
    commission_percent: float = 0.0,
    slippage_pips: float = 0.0,
    pip_size: float = 0.0001,
) -> float:
    if entry_price <= 0:
        raise ValueError("Entry price must be greater than zero.")

    if spread_pips < 0:
        raise ValueError("Spread pips cannot be negative.")

    if commission_percent < 0:
        raise ValueError("Commission percent cannot be negative.")

    if pip_size <= 0:
        raise ValueError("Pip size must be greater than zero.")

    spread_price = spread_pips * pip_size
    spread_cost_percent = (spread_price / entry_price) * 100

    return spread_cost_percent + commission_percent


def simulate_multi_candle_trade(
    candles: list[Candle],
    direction: str,
    stop_loss_percent: float = 1.0,
    take_profit_percent: float = 2.0,
    spread_pips: float = 0.0,
    commission_percent: float = 0.0,
    slippage_pips: float = 0.0,
    pip_size: float = 0.0001,
) -> SimulatedTrade:
    if len(candles) < 2:
        raise ValueError("At least two candles are required.")

    if stop_loss_percent <= 0:
        raise ValueError("Stop-loss percent must be greater than zero.")

    if take_profit_percent <= 0:
        raise ValueError("Take-profit percent must be greater than zero.")

    entry_candle = candles[0]

    # A signal is generated after the previous candle closes.
    # The earliest realistic entry is the next candle's opening price.
    entry_price = entry_candle.open

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
            entry_price=round(entry_price, 6),
            exit_price=round(entry_price, 6),
            profit_percent=0.0,
            gross_profit_percent=0.0,
            trading_cost_percent=0.0,
            spread_pips=spread_pips,
            commission_percent=commission_percent,
            slippage_pips=slippage_pips,
            exit_reason="No trade.",
            stop_loss=None,
            take_profit=None,
            candles_held=0,
        )

    exit_price = candles[-1].close
    exit_reason = "Closed at final candle."
    candles_held = len(candles) - 1

    # Include the entry candle because the position exists from its open.
    for index, candle in enumerate(candles):
        if direction == "BUY":
            stop_hit = candle.low <= stop_loss
            target_hit = candle.high >= take_profit

            # OHLC data does not reveal which level was reached first.
            # Use the stop-loss when both are touched to avoid optimistic bias.
            if stop_hit:
                exit_price = stop_loss
                exit_reason = (
                    "Stop-loss used: both stop-loss and take-profit "
                    "were touched in the same candle."
                    if target_hit
                    else "Stop-loss hit."
                )
                candles_held = index
                break

            if target_hit:
                exit_price = take_profit
                exit_reason = "Take-profit hit."
                candles_held = index
                break

        elif direction == "SELL":
            stop_hit = candle.high >= stop_loss
            target_hit = candle.low <= take_profit

            if stop_hit:
                exit_price = stop_loss
                exit_reason = (
                    "Stop-loss used: both stop-loss and take-profit "
                    "were touched in the same candle."
                    if target_hit
                    else "Stop-loss hit."
                )
                candles_held = index
                break

            if target_hit:
                exit_price = take_profit
                exit_reason = "Take-profit hit."
                candles_held = index
                break

    gross_profit_percent = calculate_profit_percent(
        direction=direction,
        entry_price=entry_price,
        exit_price=exit_price,
    )

    trading_cost_percent = calculate_trading_cost_percent(
        entry_price=entry_price,
        spread_pips=spread_pips,
        commission_percent=commission_percent,
        slippage_pips=slippage_pips,
        pip_size=pip_size,
    )

    net_profit_percent = gross_profit_percent - trading_cost_percent

    return SimulatedTrade(
        symbol=entry_candle.symbol,
        direction=direction,
        entry_price=round(entry_price, 6),
        exit_price=round(exit_price, 6),
        profit_percent=round(net_profit_percent, 6),
        gross_profit_percent=round(gross_profit_percent, 6),
        trading_cost_percent=round(trading_cost_percent, 6),
        spread_pips=spread_pips,
        commission_percent=commission_percent,
        slippage_pips=slippage_pips,
        exit_reason=exit_reason,
        stop_loss=round(stop_loss, 6),
        take_profit=round(take_profit, 6),
        candles_held=candles_held,
    )


def simulate_one_candle_trade(
    previous_candle: Candle,
    current_candle: Candle,
    direction: str,
    spread_pips: float = 0.0,
    commission_percent: float = 0.0,
    slippage_pips: float = 0.0,
) -> SimulatedTrade:
    return simulate_multi_candle_trade(
        candles=[previous_candle, current_candle],
        direction=direction,
        stop_loss_percent=100.0,
        take_profit_percent=100.0,
        spread_pips=spread_pips,
        commission_percent=commission_percent,
        slippage_pips=slippage_pips,
    )
