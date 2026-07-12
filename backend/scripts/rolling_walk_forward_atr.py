import sys
from pathlib import Path
from statistics import mean

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backtesting.engine import run_strategy_backtest
from app.market_data.csv_loader import load_candles_from_csv


DATA_FILE = Path("data/oanda_eur_usd_daily.csv")
TRAINING_SIZE = 1500
TEST_SIZE = 500
STEP_SIZE = 500
SPREAD_PIPS = 1.0

PARAMETER_GRID = [
    (0.50, 1.00),
    (0.50, 1.50),
    (0.75, 1.50),
    (1.00, 2.00),
    (1.00, 3.00),
    (1.50, 3.00),
]


def calculate_profit_factor(trades) -> float:
    gross_profit = sum(
        trade.profit_percent
        for trade in trades
        if trade.profit_percent > 0
    )
    gross_loss = abs(
        sum(
            trade.profit_percent
            for trade in trades
            if trade.profit_percent < 0
        )
    )

    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0

    return gross_profit / gross_loss


def select_parameters(training_candles):
    candidates = []

    for stop_loss, take_profit in PARAMETER_GRID:
        result = run_strategy_backtest(
            strategy_name="atr_breakout",
            candles=training_candles,
            stop_loss_percent=stop_loss,
            take_profit_percent=take_profit,
            spread_pips=SPREAD_PIPS,
        )

        candidates.append(
            {
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "result": result,
            }
        )

    eligible = [
        candidate
        for candidate in candidates
        if candidate["result"].total_trades >= 30
    ]

    if not eligible:
        eligible = candidates

    return max(
        eligible,
        key=lambda candidate: (
            candidate["result"].profit_percent,
            -candidate["result"].max_drawdown_percent,
        ),
    )


def main() -> None:
    candles = load_candles_from_csv(DATA_FILE)

    print("ATR BREAKOUT ROLLING WALK-FORWARD VALIDATION")
    print("=" * 84)
    print("Dataset:", DATA_FILE)
    print("Candles:", len(candles))
    print("Training window:", TRAINING_SIZE)
    print("Testing window:", TEST_SIZE)
    print("Step size:", STEP_SIZE)
    print("Spread:", SPREAD_PIPS, "pip")
    print()

    folds = []
    fold_number = 1
    test_start = TRAINING_SIZE

    while test_start + TEST_SIZE <= len(candles):
        training_start = test_start - TRAINING_SIZE
        training_end = test_start
        test_end = test_start + TEST_SIZE

        training_candles = candles[training_start:training_end]
        testing_candles = candles[test_start:test_end]

        selected = select_parameters(training_candles)

        test_result = run_strategy_backtest(
            strategy_name="atr_breakout",
            candles=testing_candles,
            stop_loss_percent=selected["stop_loss"],
            take_profit_percent=selected["take_profit"],
            spread_pips=SPREAD_PIPS,
        )

        returns = [
            trade.profit_percent
            for trade in test_result.trades
        ]
        expectancy = mean(returns) if returns else 0.0
        profit_factor = calculate_profit_factor(test_result.trades)

        passed = (
            test_result.total_trades >= 10
            and test_result.profit_percent > 0
            and expectancy > 0
            and profit_factor > 1.10
        )

        fold = {
            "fold": fold_number,
            "training_start": training_candles[0].timestamp.date(),
            "training_end": training_candles[-1].timestamp.date(),
            "testing_start": testing_candles[0].timestamp.date(),
            "testing_end": testing_candles[-1].timestamp.date(),
            "stop_loss": selected["stop_loss"],
            "take_profit": selected["take_profit"],
            "training_return": selected["result"].profit_percent,
            "test_result": test_result,
            "expectancy": expectancy,
            "profit_factor": profit_factor,
            "passed": passed,
        }
        folds.append(fold)

        print("FOLD", fold_number)
        print("-" * 84)
        print(
            "Training:",
            fold["training_start"],
            "to",
            fold["training_end"],
        )
        print(
            "Testing:",
            fold["testing_start"],
            "to",
            fold["testing_end"],
        )
        print(
            "Selected parameters: SL",
            fold["stop_loss"],
            "% | TP",
            fold["take_profit"],
            "%",
        )
        print("Training return:", fold["training_return"], "%")
        print("Unseen trades:", test_result.total_trades)
        print("Unseen win rate:", test_result.win_rate_percent, "%")
        print("Unseen expectancy:", round(expectancy, 4), "%")
        print("Unseen profit factor:", round(profit_factor, 4))
        print("Unseen return:", test_result.profit_percent, "%")
        print(
            "Unseen maximum drawdown:",
            test_result.max_drawdown_percent,
            "%",
        )
        print("Fold result:", "PASSED" if passed else "FAILED")
        print()

        fold_number += 1
        test_start += STEP_SIZE

    compounded_balance = 10000.0
    total_trades = 0

    for fold in folds:
        compounded_balance *= (
            1 + fold["test_result"].profit_percent / 100
        )
        total_trades += fold["test_result"].total_trades

    compounded_return = (
        compounded_balance / 10000.0 - 1
    ) * 100

    profitable_folds = sum(
        fold["test_result"].profit_percent > 0
        for fold in folds
    )
    passed_folds = sum(fold["passed"] for fold in folds)

    print("=" * 84)
    print("ROLLING WALK-FORWARD SUMMARY")
    print("=" * 84)
    print("Folds tested:", len(folds))
    print("Profitable folds:", profitable_folds)
    print("Folds passing threshold:", passed_folds)
    print("Total unseen trades:", total_trades)
    print(
        "Average unseen return:",
        round(mean(
            fold["test_result"].profit_percent
            for fold in folds
        ), 2),
        "%",
    )
    print(
        "Average unseen expectancy:",
        round(mean(
            fold["expectancy"]
            for fold in folds
        ), 4),
        "%",
    )
    print(
        "Average unseen profit factor:",
        round(mean(
            fold["profit_factor"]
            for fold in folds
        ), 4),
    )
    print(
        "Worst unseen return:",
        min(
            fold["test_result"].profit_percent
            for fold in folds
        ),
        "%",
    )
    print(
        "Worst unseen drawdown:",
        max(
            fold["test_result"].max_drawdown_percent
            for fold in folds
        ),
        "%",
    )
    print(
        "Sequential compounded return:",
        round(compounded_return, 2),
        "%",
    )
    print(
        "Sequential final £10,000 balance:",
        round(compounded_balance, 2),
    )

    promising = (
        len(folds) >= 5
        and profitable_folds >= len(folds) * 0.6
        and passed_folds >= len(folds) * 0.5
        and compounded_return > 0
        and total_trades >= 100
    )

    print()
    print(
        "OVERALL RESULT:",
        "PROMISING" if promising else "NOT ROBUST ENOUGH",
    )


if __name__ == "__main__":
    main()
