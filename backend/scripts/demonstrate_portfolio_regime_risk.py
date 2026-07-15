from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.ai.regime_risk import regime_risk_adjuster
from app.market_data.csv_loader import load_candles_from_csv
from app.portfolio.engine import run_portfolio_backtest
from app.portfolio.models import PortfolioStrategyConfig


DATA_FILE = Path(
    "data/oanda_eur_usd_daily.csv"
)


def config() -> PortfolioStrategyConfig:
    return PortfolioStrategyConfig(
        strategy_name="atr_breakout",
        symbol="EUR_USD",
        stop_loss_percent=1.5,
        take_profit_percent=3.0,
        risk_per_trade_percent=0.5,
        spread_pips=1.0,
        slippage_pips=0.5,
    )


def main() -> None:
    candles = load_candles_from_csv(DATA_FILE)

    baseline = run_portfolio_backtest(
        candles_by_symbol={
            "EUR_USD": candles,
        },
        strategy_configs=[
            config(),
        ],
        initial_balance=10000.0,
        max_portfolio_leverage=30.0,
        max_total_risk_percent=0.5,
    )

    regime_risk = run_portfolio_backtest(
        candles_by_symbol={
            "EUR_USD": candles,
        },
        strategy_configs=[
            config(),
        ],
        initial_balance=10000.0,
        max_portfolio_leverage=30.0,
        max_total_risk_percent=0.5,
        risk_percent_adjuster=regime_risk_adjuster,
    )

    reduced_risk_trades = sum(
        trade.risk_amount
        < (
            trade.account_return_percent * 0
            + 50.0
        )
        for trade in regime_risk.trades
    )

    print(
        "TRADE IQ PORTFOLIO REGIME-RISK "
        "INTEGRATION DEMONSTRATION"
    )
    print("=" * 80)
    print("Market: EUR_USD")
    print("Strategy: atr_breakout")
    print("Configured risk: 0.5% per trade")
    print()
    print(
        "Baseline | "
        f"Trades {baseline.total_trades:3d} | "
        f"Return {baseline.return_percent:7.2f}% | "
        f"DD {baseline.max_drawdown_percent:5.2f}%"
    )
    print(
        "Regime   | "
        f"Trades {regime_risk.total_trades:3d} | "
        f"Return {regime_risk.return_percent:7.2f}% | "
        f"DD {regime_risk.max_drawdown_percent:5.2f}%"
    )
    print()
    print(
        "Trades using less than the initial £50 risk:",
        reduced_risk_trades,
    )
    print(
        "Trade signals and trade count should remain "
        "unchanged."
    )


if __name__ == "__main__":
    main()
