from app.backtesting.models import BacktestResult, MockTrade


def calculate_max_drawdown(trades: list[MockTrade]) -> float:
    equity = 100.0
    peak = equity
    max_drawdown = 0.0

    for trade in trades:
        equity = equity * (1 + trade.profit_percent / 100)
        peak = max(peak, equity)
        drawdown = ((peak - equity) / peak) * 100
        max_drawdown = max(max_drawdown, drawdown)

    return round(max_drawdown, 2)


def calculate_backtest_result(
    strategy_name: str,
    symbol: str,
    trades: list[MockTrade],
) -> BacktestResult:
    total_trades = len(trades)
    winning_trades = len([trade for trade in trades if trade.profit_percent > 0])
    losing_trades = len([trade for trade in trades if trade.profit_percent <= 0])

    total_profit = sum(trade.profit_percent for trade in trades)
    win_rate = (winning_trades / total_trades) * 100 if total_trades else 0
    max_drawdown = calculate_max_drawdown(trades)

    return BacktestResult(
        strategy_name=strategy_name,
        symbol=symbol,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate_percent=round(win_rate, 2),
        profit_percent=round(total_profit, 2),
        max_drawdown_percent=max_drawdown,
    )
