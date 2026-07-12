from app.analytics.models import EquityPoint
from app.trading.models import SimulatedTrade


def build_equity_curve(
    initial_balance: float,
    trades: list[SimulatedTrade],
) -> list[EquityPoint]:
    balance = initial_balance
    equity_curve: list[EquityPoint] = [
        EquityPoint(
            trade_number=0,
            balance=round(balance, 2),
            profit_percent=0.0,
        )
    ]

    for index, trade in enumerate(trades, start=1):
        balance = balance * (1 + trade.profit_percent / 100)

        equity_curve.append(
            EquityPoint(
                trade_number=index,
                balance=round(balance, 2),
                profit_percent=trade.profit_percent,
            )
        )

    return equity_curve
