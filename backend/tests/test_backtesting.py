from app.backtesting.calculations import calculate_backtest_result, calculate_max_drawdown
from app.backtesting.models import MockTrade


def test_calculate_backtest_result():
    trades = [
        MockTrade(symbol="EUR_USD", profit_percent=1.2),
        MockTrade(symbol="EUR_USD", profit_percent=-0.5),
        MockTrade(symbol="EUR_USD", profit_percent=0.8),
        MockTrade(symbol="EUR_USD", profit_percent=2.1),
        MockTrade(symbol="EUR_USD", profit_percent=-1.0),
    ]

    result = calculate_backtest_result(
        strategy_name="Trend Following",
        symbol="EUR_USD",
        trades=trades,
    )

    assert result.total_trades == 5
    assert result.winning_trades == 3
    assert result.losing_trades == 2
    assert result.win_rate_percent == 60.0
    assert result.profit_percent == 2.59
    assert result.max_drawdown_percent == 1.0


def test_calculate_max_drawdown_with_no_trades():
    assert calculate_max_drawdown([]) == 0.0
