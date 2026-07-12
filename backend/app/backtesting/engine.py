from app.backtesting.calculations import calculate_backtest_result
from app.backtesting.models import BacktestResult, MockTrade
from app.market_data.models import Candle
from app.strategies.manager import (
    list_available_strategy_names,
    run_strategy,
)
from app.trading.models import SimulatedTrade
from app.trading.simulator import simulate_multi_candle_trade


def run_strategy_backtest(
    strategy_name: str,
    candles: list[Candle],
    stop_loss_percent: float = 1.0,
    take_profit_percent: float = 2.0,
    spread_pips: float = 0.0,
    commission_percent: float = 0.0,
    allowed_directions: set[str] | None = None,
    initial_balance: float = 10000.0,
    risk_per_trade_percent: float = 0.5,
    max_leverage: float = 20.0,
    slippage_pips: float = 0.0,
) -> BacktestResult:
    if not candles:
        raise ValueError("At least one candle is required.")

    if strategy_name not in list_available_strategy_names():
        raise ValueError(f"Unknown strategy: {strategy_name}")

    if spread_pips < 0:
        raise ValueError("Spread pips cannot be negative.")

    if commission_percent < 0:
        raise ValueError("Commission percent cannot be negative.")

    if slippage_pips < 0:
        raise ValueError("Slippage pips cannot be negative.")

    if initial_balance <= 0:
        raise ValueError("Initial balance must be greater than zero.")

    if risk_per_trade_percent <= 0:
        raise ValueError(
            "Risk per trade percent must be greater than zero."
        )

    if risk_per_trade_percent > 100:
        raise ValueError(
            "Risk per trade percent cannot exceed 100."
        )

    if max_leverage <= 0:
        raise ValueError("Maximum leverage must be greater than zero.")

    if allowed_directions is not None:
        invalid_directions = allowed_directions - {"BUY", "SELL"}

        if invalid_directions:
            raise ValueError(
                "Allowed directions must contain only BUY or SELL."
            )

    trades: list[MockTrade] = []
    trade_ledger: list[SimulatedTrade] = []

    current_balance = initial_balance
    index = 0

    while index < len(candles) - 1:
        try:
            signal = run_strategy(strategy_name, candles[: index + 1])
        except ValueError:
            index += 1
            continue

        if signal.direction == "HOLD":
            index += 1
            continue

        if (
            allowed_directions is not None
            and signal.direction not in allowed_directions
        ):
            index += 1
            continue

        # The signal is only known after candles[index] has closed.
        # Enter no earlier than the next candle to avoid look-ahead bias.
        entry_index = index + 1
        trade_candles = candles[entry_index:]

        if len(trade_candles) < 2:
            break

        simulated_trade = simulate_multi_candle_trade(
            candles=trade_candles,
            direction=signal.direction,
            stop_loss_percent=stop_loss_percent,
            take_profit_percent=take_profit_percent,
            spread_pips=spread_pips,
            commission_percent=commission_percent,
            slippage_pips=slippage_pips,
        )

        stop_loss = simulated_trade.stop_loss

        if stop_loss is None:
            raise ValueError(
                "A stop-loss is required for risk-based position sizing."
            )

        stop_distance = abs(
            simulated_trade.entry_price - stop_loss
        )

        if stop_distance <= 0:
            raise ValueError(
                "Stop-loss distance must be greater than zero."
            )

        risk_amount = (
            current_balance
            * risk_per_trade_percent
            / 100
        )

        risk_based_units = risk_amount / stop_distance

        maximum_notional = current_balance * max_leverage
        leverage_limited_units = (
            maximum_notional / simulated_trade.entry_price
        )

        position_size_units = min(
            risk_based_units,
            leverage_limited_units,
        )

        notional_value = (
            position_size_units
            * simulated_trade.entry_price
        )

        leverage_used = notional_value / current_balance

        account_profit_percent = (
            simulated_trade.profit_percent
            * notional_value
            / current_balance
        )

        simulated_trade = simulated_trade.model_copy(
            update={
                "profit_percent": round(
                    account_profit_percent,
                    6,
                ),
                "account_balance_before": round(
                    current_balance,
                    2,
                ),
                "risk_amount": round(risk_amount, 2),
                "position_size_units": round(
                    position_size_units,
                    2,
                ),
                "notional_value": round(
                    notional_value,
                    2,
                ),
                "leverage_used": round(
                    leverage_used,
                    4,
                ),
                "position_limited_by_leverage": (
                    leverage_limited_units
                    < risk_based_units
                ),
            }
        )

        current_balance *= (
            1 + simulated_trade.profit_percent / 100
        )

        trade_ledger.append(simulated_trade)
        trades.append(
            MockTrade(
                symbol=simulated_trade.symbol,
                profit_percent=simulated_trade.profit_percent,
            )
        )

        # Move to the candle after the trade exit.
        # One candle is also consumed between signal and entry.
        index = entry_index + max(simulated_trade.candles_held, 1)

    return calculate_backtest_result(
        strategy_name=strategy_name,
        symbol=candles[-1].symbol,
        trades=trades,
        trade_ledger=trade_ledger,
    )
