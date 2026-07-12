import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.backtesting.engine import run_strategy_backtest
from app.market_data.csv_loader import load_candles_from_csv
from app.market_data.models import Candle


DATA_FILE = BACKEND_DIR / "data" / "eur_usd_daily.csv"
TRAINING_PERCENT = 0.70
SPREAD_PIPS = 1.0
COMMISSION_PERCENT = 0.0

STRATEGIES = (
    "simple_trend",
    "ema_crossover",
)

STOP_LOSSES = (
    0.5,
    1.0,
    1.5,
    2.0,
)

TAKE_PROFITS = (
    0.5,
    1.0,
    1.5,
    2.0,
    3.0,
    4.0,
)


@dataclass
class ValidationResult:
    strategy: str
    stop_loss_percent: float
    take_profit_percent: float
    training_return_percent: float
    training_drawdown_percent: float
    training_trades: int
    testing_return_percent: float
    testing_drawdown_percent: float
    testing_trades: int
    testing_win_rate_percent: float
    testing_final_balance: float


def split_candles(
    candles: list[Candle],
) -> tuple[list[Candle], list[Candle]]:
    split_index = int(len(candles) * TRAINING_PERCENT)

    training = candles[:split_index]
    testing = candles[split_index:]

    if len(training) < 2 or len(testing) < 2:
        raise ValueError("Dataset is too small for walk-forward validation.")

    return training, testing


def find_best_training_parameters(
    strategy: str,
    training_candles: list[Candle],
) -> tuple[float, float, float, float, int]:
    best_result = None
    best_stop_loss = None
    best_take_profit = None

    for stop_loss in STOP_LOSSES:
        for take_profit in TAKE_PROFITS:
            result = run_strategy_backtest(
                strategy_name=strategy,
                candles=training_candles,
                stop_loss_percent=stop_loss,
                take_profit_percent=take_profit,
                spread_pips=SPREAD_PIPS,
                commission_percent=COMMISSION_PERCENT,
            )

            if (
                best_result is None
                or result.profit_percent > best_result.profit_percent
            ):
                best_result = result
                best_stop_loss = stop_loss
                best_take_profit = take_profit

    if (
        best_result is None
        or best_stop_loss is None
        or best_take_profit is None
    ):
        raise RuntimeError(f"No optimisation result for {strategy}.")

    return (
        best_stop_loss,
        best_take_profit,
        best_result.profit_percent,
        best_result.max_drawdown_percent,
        best_result.total_trades,
    )


def validate_strategy(
    strategy: str,
    training_candles: list[Candle],
    testing_candles: list[Candle],
) -> ValidationResult:
    (
        stop_loss,
        take_profit,
        training_return,
        training_drawdown,
        training_trades,
    ) = find_best_training_parameters(
        strategy,
        training_candles,
    )

    testing_result = run_strategy_backtest(
        strategy_name=strategy,
        candles=testing_candles,
        stop_loss_percent=stop_loss,
        take_profit_percent=take_profit,
        spread_pips=SPREAD_PIPS,
        commission_percent=COMMISSION_PERCENT,
    )

    return ValidationResult(
        strategy=strategy,
        stop_loss_percent=stop_loss,
        take_profit_percent=take_profit,
        training_return_percent=training_return,
        training_drawdown_percent=training_drawdown,
        training_trades=training_trades,
        testing_return_percent=testing_result.profit_percent,
        testing_drawdown_percent=testing_result.max_drawdown_percent,
        testing_trades=testing_result.total_trades,
        testing_win_rate_percent=testing_result.win_rate_percent,
        testing_final_balance=testing_result.equity_curve[-1].balance,
    )


def main() -> None:
    candles = load_candles_from_csv(DATA_FILE)
    training_candles, testing_candles = split_candles(candles)

    print("FX IQ WALK-FORWARD VALIDATION")
    print("=" * 76)
    print(f"Dataset candles: {len(candles)}")
    print(f"Training candles: {len(training_candles)}")
    print(f"Testing candles: {len(testing_candles)}")
    print(f"Spread: {SPREAD_PIPS} pip")
    print()
    print(
        "Training period:",
        training_candles[0].timestamp.date(),
        "to",
        training_candles[-1].timestamp.date(),
    )
    print(
        "Testing period:",
        testing_candles[0].timestamp.date(),
        "to",
        testing_candles[-1].timestamp.date(),
    )

    results = [
        validate_strategy(
            strategy,
            training_candles,
            testing_candles,
        )
        for strategy in STRATEGIES
    ]

    for result in results:
        print()
        print("=" * 76)
        print("Strategy:", result.strategy)
        print("=" * 76)
        print("Selected stop loss:", result.stop_loss_percent, "%")
        print("Selected take profit:", result.take_profit_percent, "%")
        print()
        print("TRAINING PERFORMANCE")
        print("Trades:", result.training_trades)
        print("Return:", result.training_return_percent, "%")
        print("Maximum drawdown:", result.training_drawdown_percent, "%")
        print()
        print("UNSEEN TEST PERFORMANCE")
        print("Trades:", result.testing_trades)
        print("Win rate:", result.testing_win_rate_percent, "%")
        print("Return:", result.testing_return_percent, "%")
        print("Maximum drawdown:", result.testing_drawdown_percent, "%")
        print("Final balance:", result.testing_final_balance)

        if result.testing_return_percent > 0:
            print("Validation result: PROFITABLE ON UNSEEN DATA")
        else:
            print("Validation result: FAILED ON UNSEEN DATA")

    best_test = max(
        results,
        key=lambda item: item.testing_return_percent,
    )

    print()
    print("=" * 76)
    print("FINAL VALIDATION SUMMARY")
    print("=" * 76)
    print("Best unseen-data strategy:", best_test.strategy)
    print("Stop loss:", best_test.stop_loss_percent, "%")
    print("Take profit:", best_test.take_profit_percent, "%")
    print("Unseen-data return:", best_test.testing_return_percent, "%")
    print(
        "Unseen-data maximum drawdown:",
        best_test.testing_drawdown_percent,
        "%",
    )

    print()
    print(
        "Important: the dataset is synthetic, so these figures validate "
        "the software process only—not real trading profitability."
    )


if __name__ == "__main__":
    main()
