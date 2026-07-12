from app.analytics.equity import build_equity_curve
from app.analytics.models import EquityPoint
from app.backtesting.models import BacktestResult, MockTrade
from app.trading.models import SimulatedTrade


INITIAL_BALANCE = 10000.0


def calculate_max_drawdown_from_equity(
    equity_balances: list[float],
) -> float:
    if not equity_balances:
        return 0.0

    peak = equity_balances[0]
    maximum_drawdown = 0.0

    for balance in equity_balances:
        peak = max(peak, balance)

        if peak > 0:
            drawdown = ((peak - balance) / peak) * 100
            maximum_drawdown = max(maximum_drawdown, drawdown)

    return round(maximum_drawdown, 2)


def build_mock_equity_curve(
    trades: list[MockTrade],
) -> list[EquityPoint]:
    balance = INITIAL_BALANCE

    equity_curve = [
        EquityPoint(
            trade_number=0,
            balance=balance,
            profit_percent=0.0,
        )
    ]

    for index, trade in enumerate(trades, start=1):
        balance *= 1 + trade.profit_percent / 100

        equity_curve.append(
            EquityPoint(
                trade_number=index,
                balance=round(balance, 2),
                profit_percent=trade.profit_percent,
            )
        )

    return equity_curve


def calculate_max_drawdown(trades: list[MockTrade]) -> float:
    equity_curve = build_mock_equity_curve(trades)

    return calculate_max_drawdown_from_equity(
        [point.balance for point in equity_curve]
    )


def calculate_backtest_result(
    strategy_name: str,
    symbol: str,
    trades: list[MockTrade],
    trade_ledger: list[SimulatedTrade] | None = None,
) -> BacktestResult:
    ledger = trade_ledger or []

    total_trades = len(trades)
    winning_trades = sum(
        trade.profit_percent > 0
        for trade in trades
    )
    losing_trades = sum(
        trade.profit_percent < 0
        for trade in trades
    )

    win_rate = (
        winning_trades / total_trades * 100
        if total_trades
        else 0.0
    )

    if ledger:
        equity_curve = build_equity_curve(
            initial_balance=INITIAL_BALANCE,
            trades=ledger,
        )
    else:
        equity_curve = build_mock_equity_curve(trades)

    equity_balances = [
        point.balance
        for point in equity_curve
    ]

    final_balance = equity_balances[-1]

    compounded_return = (
        final_balance / INITIAL_BALANCE - 1
    ) * 100

    maximum_drawdown = calculate_max_drawdown_from_equity(
        equity_balances
    )

    return BacktestResult(
        strategy_name=strategy_name,
        symbol=symbol,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate_percent=round(win_rate, 2),
        profit_percent=round(compounded_return, 2),
        max_drawdown_percent=maximum_drawdown,
        trades=ledger,
        equity_curve=equity_curve,
    )
