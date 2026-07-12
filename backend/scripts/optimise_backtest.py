import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dataclasses import dataclass
from pathlib import Path

from app.backtesting.engine import run_strategy_backtest
from app.market_data.csv_loader import load_candles_from_csv


DATA_FILE = Path("data/eur_usd_daily.csv")
STRATEGIES = ("simple_trend", "ema_crossover")
STOP_LOSSES = (0.5, 0.75, 1.0, 1.5, 2.0)
TAKE_PROFITS = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0)
SPREAD_PIPS = 1.0


@dataclass
class OptimisationResult:
    strategy: str
    stop_loss_percent: float
    take_profit_percent: float
    total_trades: int
    win_rate_percent: float
    return_percent: float
    max_drawdown_percent: float
    final_balance: float


def run_optimisation() -> list[OptimisationResult]:
    candles = load_candles_from_csv(DATA_FILE)
    results: list[OptimisationResult] = []

    for strategy in STRATEGIES:
        for stop_loss in STOP_LOSSES:
            for take_profit in TAKE_PROFITS:
                result = run_strategy_backtest(
                    strategy_name=strategy,
                    candles=candles,
                    stop_loss_percent=stop_loss,
                    take_profit_percent=take_profit,
                    spread_pips=SPREAD_PIPS,
                    commission_percent=0.0,
                )

                final_balance = (
                    result.equity_curve[-1].balance
                    if result.equity_curve
                    else 10000.0
                )

                results.append(
                    OptimisationResult(
                        strategy=strategy,
                        stop_loss_percent=stop_loss,
                        take_profit_percent=take_profit,
                        total_trades=result.total_trades,
                        win_rate_percent=result.win_rate_percent,
                        return_percent=result.profit_percent,
                        max_drawdown_percent=result.max_drawdown_percent,
                        final_balance=final_balance,
                    )
                )

    return results


def print_results(results: list[OptimisationResult]) -> None:
    ranked = sorted(
        results,
        key=lambda item: (
            item.return_percent,
            -item.max_drawdown_percent,
        ),
        reverse=True,
    )

    print()
    print("FX IQ PARAMETER OPTIMISATION")
    print("Dataset:", DATA_FILE)
    print("Spread:", SPREAD_PIPS, "pip")
    print("Combinations tested:", len(results))

    for strategy in STRATEGIES:
        strategy_results = [
            result for result in ranked
            if result.strategy == strategy
        ]

        print()
        print("=" * 72)
        print("Strategy:", strategy)
        print("=" * 72)

        for position, result in enumerate(strategy_results[:10], start=1):
            print(
                f"{position:>2}. "
                f"SL {result.stop_loss_percent:>4.2f}% | "
                f"TP {result.take_profit_percent:>4.2f}% | "
                f"Trades {result.total_trades:>4} | "
                f"Win {result.win_rate_percent:>6.2f}% | "
                f"Return {result.return_percent:>8.2f}% | "
                f"Drawdown {result.max_drawdown_percent:>7.2f}% | "
                f"Balance {result.final_balance:>9.2f}"
            )

    profitable = [
        result for result in ranked
        if result.return_percent > 0
    ]

    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print("Profitable combinations:", len(profitable))

    if profitable:
        best = profitable[0]
        print("Best strategy:", best.strategy)
        print("Best stop loss:", best.stop_loss_percent, "%")
        print("Best take profit:", best.take_profit_percent, "%")
        print("Best return:", best.return_percent, "%")
        print("Best maximum drawdown:", best.max_drawdown_percent, "%")
        print("Best final balance:", best.final_balance)
    else:
        print("No profitable combinations found on this dataset.")


if __name__ == "__main__":
    print_results(run_optimisation())
