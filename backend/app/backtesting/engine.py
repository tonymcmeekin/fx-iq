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
) -> BacktestResult:
    if not candles:
        raise ValueError("At least one candle is required.")

    if strategy_name not in list_available_strategy_names():
        raise ValueError(f"Unknown strategy: {strategy_name}")

    if spread_pips < 0:
        raise ValueError("Spread pips cannot be negative.")

    if commission_percent < 0:
        raise ValueError("Commission percent cannot be negative.")

    if allowed_directions is not None:
        invalid_directions = allowed_directions - {"BUY", "SELL"}

        if invalid_directions:
            raise ValueError(
                "Allowed directions must contain only BUY or SELL."
            )

    trades: list[MockTrade] = []
    trade_ledger: list[SimulatedTrade] = []

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
