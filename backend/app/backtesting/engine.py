from app.backtesting.calculations import calculate_backtest_result
from app.backtesting.models import BacktestResult, MockTrade
from app.market_data.models import Candle
from app.strategies.simple_trend import generate_simple_trend_signal


def run_simple_trend_backtest(candles: list[Candle]) -> BacktestResult:
    trades: list[MockTrade] = []

    for index in range(1, len(candles)):
        previous_candle = candles[index - 1]
        current_candle = candles[index]

        signal = generate_simple_trend_signal([previous_candle, current_candle])

        if signal.direction == "BUY":
            profit_percent = (
                (current_candle.close - previous_candle.close) / previous_candle.close
            ) * 100
        elif signal.direction == "SELL":
            profit_percent = (
                (previous_candle.close - current_candle.close) / previous_candle.close
            ) * 100
        else:
            profit_percent = 0.0

        trades.append(MockTrade(symbol=current_candle.symbol, profit_percent=profit_percent))

    return calculate_backtest_result(
        strategy_name="Simple Trend",
        symbol=candles[-1].symbol,
        trades=trades,
    )
