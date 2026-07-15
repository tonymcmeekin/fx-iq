from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.ai.external_validation import (
    EXTERNAL_MARKETS,
    HOLDOUT_START,
)
from app.market_data.csv_loader import load_candles_from_csv
from scripts.adaptive_regime_policy_walk_forward import (
    FOLDS,
    INITIAL_BALANCE,
    profit_factor,
    run_test_fold,
    start_timestamp,
    end_timestamp,
)
from scripts.guarded_adaptive_policy_walk_forward import (
    BASELINE_STRATEGY,
    choose_guarded_policy,
    evaluate_training_candidates,
)


DEVELOPMENT_FOLDS = [
    fold
    for fold in FOLDS
    if end_timestamp(fold[1]) < HOLDOUT_START
]


def run_market(symbol: str, candles) -> dict:
    guarded_balance = INITIAL_BALANCE
    baseline_balance = INITIAL_BALANCE
    results = []

    development_candles = [
        candle
        for candle in candles
        if candle.timestamp < HOLDOUT_START
    ]

    for fold_number, (start_text, end_text) in enumerate(
        DEVELOPMENT_FOLDS,
        start=1,
    ):
        fold_start = start_timestamp(start_text)
        fold_end = end_timestamp(end_text)

        training_candles = [
            candle
            for candle in development_candles
            if candle.timestamp < fold_start
        ]

        candidates = evaluate_training_candidates(
            symbol=symbol,
            training_candles=training_candles,
        )

        selected_policy, reason = choose_guarded_policy(
            candidates
        )

        guarded_result = run_test_fold(
            symbol=symbol,
            candles=development_candles,
            strategy_name=selected_policy,
            fold_start=fold_start,
            fold_end=fold_end,
            starting_balance=guarded_balance,
        )

        baseline_result = run_test_fold(
            symbol=symbol,
            candles=development_candles,
            strategy_name=BASELINE_STRATEGY,
            fold_start=fold_start,
            fold_end=fold_end,
            starting_balance=baseline_balance,
        )

        guarded_return = (
            guarded_result.final_balance
            / guarded_balance
            - 1
        ) * 100

        baseline_return = (
            baseline_result.final_balance
            / baseline_balance
            - 1
        ) * 100

        results.append(
            {
                "fold": fold_number,
                "start": start_text,
                "end": end_text,
                "selected_policy": selected_policy,
                "reason": reason,
                "guarded_trades": guarded_result.total_trades,
                "guarded_return": guarded_return,
                "guarded_pf": profit_factor(
                    guarded_result.trades
                ),
                "guarded_drawdown": (
                    guarded_result.max_drawdown_percent
                ),
                "baseline_trades": baseline_result.total_trades,
                "baseline_return": baseline_return,
                "baseline_pf": profit_factor(
                    baseline_result.trades
                ),
                "baseline_drawdown": (
                    baseline_result.max_drawdown_percent
                ),
            }
        )

        guarded_balance = guarded_result.final_balance
        baseline_balance = baseline_result.final_balance

    return {
        "symbol": symbol,
        "folds": results,
        "guarded_return": (
            guarded_balance / INITIAL_BALANCE - 1
        ) * 100,
        "baseline_return": (
            baseline_balance / INITIAL_BALANCE - 1
        ) * 100,
        "guarded_profitable_folds": sum(
            item["guarded_return"] > 0
            for item in results
        ),
        "baseline_profitable_folds": sum(
            item["baseline_return"] > 0
            for item in results
        ),
        "guarded_worst_drawdown": max(
            item["guarded_drawdown"]
            for item in results
        ),
        "baseline_worst_drawdown": max(
            item["baseline_drawdown"]
            for item in results
        ),
        "guarded_trades": sum(
            item["guarded_trades"]
            for item in results
        ),
        "baseline_trades": sum(
            item["baseline_trades"]
            for item in results
        ),
        "promotions": sum(
            item["selected_policy"]
            != BASELINE_STRATEGY
            for item in results
        ),
    }


def print_market(result: dict) -> None:
    print()
    print("=" * 116)
    print(result["symbol"])
    print("=" * 116)

    for fold in result["folds"]:
        print(
            f"Fold {fold['fold']}: "
            f"{fold['start']} to {fold['end']}"
        )
        print(
            "  Selected:",
            fold["selected_policy"],
        )
        print(
            "  Decision:",
            fold["reason"],
        )
        print(
            "  Guarded  | "
            f"Trades {fold['guarded_trades']:3d} | "
            f"Return {fold['guarded_return']:7.2f}% | "
            f"PF {fold['guarded_pf']:6.3f} | "
            f"DD {fold['guarded_drawdown']:5.2f}%"
        )
        print(
            "  Baseline | "
            f"Trades {fold['baseline_trades']:3d} | "
            f"Return {fold['baseline_return']:7.2f}% | "
            f"PF {fold['baseline_pf']:6.3f} | "
            f"DD {fold['baseline_drawdown']:5.2f}%"
        )
        print(
            "  Difference:",
            round(
                fold["guarded_return"]
                - fold["baseline_return"],
                2,
            ),
            "percentage points",
        )
        print("-" * 116)

    print("MARKET SUMMARY")
    print(
        "Promotions:",
        f"{result['promotions']}/"
        f"{len(DEVELOPMENT_FOLDS)}",
    )
    print(
        "Guarded profitable folds:",
        f"{result['guarded_profitable_folds']}/"
        f"{len(DEVELOPMENT_FOLDS)}",
    )
    print(
        "Baseline profitable folds:",
        f"{result['baseline_profitable_folds']}/"
        f"{len(DEVELOPMENT_FOLDS)}",
    )
    print(
        "Guarded sequential return:",
        round(result["guarded_return"], 2),
        "%",
    )
    print(
        "Baseline sequential return:",
        round(result["baseline_return"], 2),
        "%",
    )
    print(
        "Return improvement:",
        round(
            result["guarded_return"]
            - result["baseline_return"],
            2,
        ),
        "percentage points",
    )
    print(
        "Guarded worst drawdown:",
        round(result["guarded_worst_drawdown"], 2),
        "%",
    )
    print(
        "Baseline worst drawdown:",
        round(result["baseline_worst_drawdown"], 2),
        "%",
    )
    print(
        "Guarded trades:",
        result["guarded_trades"],
    )


def main() -> None:
    print("EXTERNAL-MARKET DEVELOPMENT VALIDATION")
    print("=" * 116)
    print(
        "Frozen guarded selector tested on three markets that "
        "did not influence its design."
    )
    print(
        "Only folds ending before "
        f"{HOLDOUT_START.isoformat()} are included."
    )
    print(
        "The final holdout remains unopened."
    )

    results = []

    for symbol, path in EXTERNAL_MARKETS.items():
        candles = load_candles_from_csv(path)

        holdout_count = sum(
            candle.timestamp >= HOLDOUT_START
            for candle in candles
        )

        print()
        print(
            f"{symbol}: reserving {holdout_count} "
            "holdout candles."
        )

        result = run_market(
            symbol=symbol,
            candles=candles,
        )

        results.append(result)
        print_market(result)

    print()
    print("=" * 116)
    print("EXTERNAL DEVELOPMENT SUMMARY")
    print("=" * 116)

    for result in results:
        difference = (
            result["guarded_return"]
            - result["baseline_return"]
        )

        print(
            f"{result['symbol']:7s} | "
            f"Guarded {result['guarded_return']:7.2f}% | "
            f"Baseline {result['baseline_return']:7.2f}% | "
            f"Difference {difference:7.2f}pp | "
            f"Guarded DD "
            f"{result['guarded_worst_drawdown']:5.2f}% | "
            f"Baseline DD "
            f"{result['baseline_worst_drawdown']:5.2f}%"
        )

    profitable_markets = sum(
        result["guarded_return"] > 0
        for result in results
    )

    improved_markets = sum(
        result["guarded_return"]
        > result["baseline_return"]
        for result in results
    )

    reduced_drawdown_markets = sum(
        result["guarded_worst_drawdown"]
        < result["baseline_worst_drawdown"]
        for result in results
    )

    total_trades = sum(
        result["guarded_trades"]
        for result in results
    )

    guarded_return_sum = sum(
        result["guarded_return"]
        for result in results
    )

    baseline_return_sum = sum(
        result["baseline_return"]
        for result in results
    )

    print()
    print(
        "Profitable external markets:",
        profitable_markets,
        "/ 3",
    )
    print(
        "External markets beating baseline:",
        improved_markets,
        "/ 3",
    )
    print(
        "External markets reducing drawdown:",
        reduced_drawdown_markets,
        "/ 3",
    )
    print(
        "Total external development trades:",
        total_trades,
    )
    print(
        "Sum of guarded returns:",
        round(guarded_return_sum, 2),
        "%",
    )
    print(
        "Sum of baseline returns:",
        round(baseline_return_sum, 2),
        "%",
    )

    external_pass = (
        profitable_markets >= 2
        and improved_markets >= 2
        and total_trades >= 200
        and guarded_return_sum > 0
    )

    print()
    print(
        "EXTERNAL DEVELOPMENT RESULT:",
        (
            "PASSED"
            if external_pass
            else "FAILED"
        ),
    )
    print(
        "FINAL HOLDOUT STATUS: UNOPENED"
    )


if __name__ == "__main__":
    main()
