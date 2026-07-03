from app.backtesting.calculations import calculate_backtest_result
from app.backtesting.models import BacktestResult, MockTrade
from app.market_data.models import Candle
from app.strategies.manager import run_strategy
from app.trading.simulator import simulate_one_candle_trade


def run_strategy_backtest(strategy_name: str, candles: list[Candle]) -> BacktestResult:
    trades: list[MockTrade] = []

    for index in range(1, len(candles)):
        previous_candle = candles[index - 1]
        current_candle = candles[index]

        signal = run_strategy(strategy_name, [previous_candle, current_candle])
        simulated_trade = simulate_one_candle_trade(
            previous_candle=previous_candle,
            current_candle=current_candle,
            direction=signal.direction,
        )

        trades.append(
            MockTrade(
                symbol=simulated_trade.symbol,
                profit_percent=simulated_trade.profit_percent,
            )
        )

    return calculate_backtest_result(
        strategy_name=strategy_name,
        symbol=candles[-1].symbol,
        trades=trades,
    )
