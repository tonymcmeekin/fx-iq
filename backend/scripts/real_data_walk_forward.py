import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backtesting.engine import run_strategy_backtest
from app.market_data.csv_loader import load_candles_from_csv


DATA_FILE = Path("data/oanda_eur_usd_daily.csv")
STRATEGIES = ("simple_trend", "ema_crossover")
STOP_LOSSES = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0)
TAKE_PROFITS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
SPREAD_PIPS = 1.0
TRAINING_FRACTION = 0.70


@dataclass
class Candidate:
    strategy: str
    stop_loss_percent: float
    take_profit_percent: float
    return_percent: float
    max_drawdown_percent: float
    win_rate_percent: float
    total_trades: int


def select_best_candidate(strategy: str, candles) -> Candidate:
    candidates: list[Candidate] = []

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

            candidates.append(
                Candidate(
                    strategy=strategy,
                    stop_loss_percent=stop_loss,
                    take_profit_percent=take_profit,
                    return_percent=result.profit_percent,
                    max_drawdown_percent=result.max_drawdown_percent,
                    win_rate_percent=result.win_rate_percent,
                    total_trades=result.total_trades,
                )
            )

    return max(
        candidates,
        key=lambda candidate: (
            candidate.return_percent,
            -candidate.max_drawdown_percent,
            candidate.total_trades,
        ),
    )


def main() -> None:
    candles = load_candles_from_csv(DATA_FILE)

    split_index = int(len(candles) * TRAINING_FRACTION)
    training_candles = candles[:split_index]
    testing_candles = candles[split_index:]

    print("FX IQ GENUINE OANDA WALK-FORWARD VALIDATION")
    print("=" * 76)
    print("Dataset:", DATA_FILE)
    print("Total candles:", len(candles))
    print("Training candles:", len(training_candles))
    print("Testing candles:", len(testing_candles))
    print("Spread:", SPREAD_PIPS, "pip")
    print()
    print(
        "Training period:",
        training_candles[0].timestamp.date(),
        "to",
        training_candles[-1].timestamp.date(),
    )
    print(
        "Unseen testing period:",
        testing_candles[0].timestamp.date(),
        "to",
        testing_candles[-1].timestamp.date(),
    )

    final_results = []

    for strategy in STRATEGIES:
        selected = select_best_candidate(strategy, training_candles)

        training_result = run_strategy_backtest(
            strategy_name=strategy,
            candles=training_candles,
            stop_loss_percent=selected.stop_loss_percent,
            take_profit_percent=selected.take_profit_percent,
            spread_pips=SPREAD_PIPS,
            commission_percent=0.0,
        )

        testing_result = run_strategy_backtest(
            strategy_name=strategy,
            candles=testing_candles,
            stop_loss_percent=selected.stop_loss_percent,
            take_profit_percent=selected.take_profit_percent,
            spread_pips=SPREAD_PIPS,
            commission_percent=0.0,
        )

        final_results.append((selected, testing_result))

        print()
        print("=" * 76)
        print("Strategy:", strategy)
        print("Selected stop loss:", selected.stop_loss_percent, "%")
        print("Selected take profit:", selected.take_profit_percent, "%")
        print()
        print("TRAINING PERFORMANCE")
        print("Trades:", training_result.total_trades)
        print("Win rate:", training_result.win_rate_percent, "%")
        print("Return:", training_result.profit_percent, "%")
        print("Maximum drawdown:", training_result.max_drawdown_percent, "%")
        print()
        print("UNSEEN TEST PERFORMANCE")
        print("Trades:", testing_result.total_trades)
        print("Wins:", testing_result.winning_trades)
        print("Losses:", testing_result.losing_trades)
        print("Win rate:", testing_result.win_rate_percent, "%")
        print("Return:", testing_result.profit_percent, "%")
        print("Maximum drawdown:", testing_result.max_drawdown_percent, "%")
        print("Final £10,000 balance:", testing_result.equity_curve[-1].balance)
        print(
            "Result:",
            "PROFITABLE"
            if testing_result.profit_percent > 0
            else "NOT PROFITABLE",
        )

    best_selected, best_test = max(
        final_results,
        key=lambda item: item[1].profit_percent,
    )

    print()
    print("=" * 76)
    print("FINAL GENUINE-DATA SUMMARY")
    print("=" * 76)
    print("Best unseen-data strategy:", best_selected.strategy)
    print("Stop loss:", best_selected.stop_loss_percent, "%")
    print("Take profit:", best_selected.take_profit_percent, "%")
    print("Unseen return:", best_test.profit_percent, "%")
    print("Unseen maximum drawdown:", best_test.max_drawdown_percent, "%")
    print("Final £10,000 balance:", best_test.equity_curve[-1].balance)

    if best_test.profit_percent <= 0:
        print()
        print(
            "Conclusion: neither current strategy has demonstrated a "
            "profitable edge on unseen genuine OANDA data."
        )


if __name__ == "__main__":
    main()
