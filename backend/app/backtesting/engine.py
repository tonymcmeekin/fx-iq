from app.backtesting.calculations import calculate_backtest_result
from app.backtesting.models import BacktestResult, MockTrade
from app.market_data.models import Candle
from app.strategies.manager import run_strategy
from app.trading.models import SimulatedTrade
from app.trading.simulator import simulate_multi_candle_trade


def run_strategy_backtest(
    strategy_name: str,
    candles: list[Candle],
    stop_loss_percent: float = 1.0,
    take_profit_percent: float = 2.0,
    spread_pips: float = 0.0,
    commission_percent: float = 0.0,
) -> BacktestResult:
    if not candles:
        raise ValueError("At least one candle is required.")

    if spread_pips < 0:
        raise ValueError("Spread pips cannot be negative.")

    if commission_percent < 0:
        raise ValueError("Commission percent cannot be negative.")

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

        trade_candles = candles[index:]

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

        index += max(simulated_trade.candles_held, 1) + 1

    return calculate_backtest_result(
        strategy_name=strategy_name,
        symbol=candles[-1].symbol,
        trades=trades,
        trade_ledger=trade_ledger,
    )
