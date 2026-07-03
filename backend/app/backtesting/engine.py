from app.backtesting.calculations import calculate_backtest_result
from app.backtesting.models import BacktestResult, MockTrade
from app.market_data.models import Candle
from app.strategies.manager import run_strategy
from app.trading.simulator import simulate_multi_candle_trade


def run_strategy_backtest(strategy_name: str, candles: list[Candle]) -> BacktestResult:
    trades: list[MockTrade] = []

    for index in range(0, len(candles) - 1):
        try:
            signal = run_strategy(strategy_name, candles[: index + 1])
        except ValueError:
            continue

        if signal.direction == "HOLD":
            continue

        trade_candles = candles[index : index + 4]

        if len(trade_candles) < 2:
            continue

        simulated_trade = simulate_multi_candle_trade(
            candles=trade_candles,
            direction=signal.direction,
            stop_loss_percent=1.0,
            take_profit_percent=2.0,
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
