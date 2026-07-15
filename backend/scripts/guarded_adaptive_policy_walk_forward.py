from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.market_data.csv_loader import load_candles_from_csv
from scripts.adaptive_regime_policy_walk_forward import (
    CANDIDATE_POLICIES,
    FOLDS,
    INITIAL_BALANCE,
    MARKETS,
    MINIMUM_TRAINING_TRADES,
    end_timestamp,
    policy_score,
    profit_factor,
    run_test_fold,
    start_timestamp,
    strategy_config,
)
from app.portfolio.engine import run_portfolio_backtest


BASELINE_STRATEGY = "atr_breakout"

MINIMUM_CHALLENGER_RETURN = 0.0
MINIMUM_CHALLENGER_PROFIT_FACTOR = 1.05
MAXIMUM_CHALLENGER_DRAWDOWN = 10.0
MINIMUM_SCORE_ADVANTAGE = 1.5


def evaluate_training_candidates(
    symbol: str,
    training_candles,
) -> list[dict]:
    candidates = []

    for strategy_name in CANDIDATE_POLICIES:
        result = run_portfolio_backtest(
            candles_by_symbol={
                symbol: training_candles,
            },
            strategy_configs=[
                strategy_config(
                    strategy_name,
                    symbol,
                )
            ],
            initial_balance=INITIAL_BALANCE,
            max_portfolio_leverage=30.0,
            max_total_risk_percent=0.5,
        )

        candidates.append(
            {
                "strategy": strategy_name,
                "trades": result.total_trades,
                "return": result.return_percent,
                "drawdown": result.max_drawdown_percent,
                "profit_factor": profit_factor(
                    result.trades
                ),
                "score": policy_score(result),
            }
        )

    candidates.sort(
        key=lambda item: (
            item["score"],
            item["return"],
            -item["drawdown"],
        ),
        reverse=True,
    )

    return candidates


def choose_guarded_policy(
    candidates: list[dict],
) -> tuple[str, str]:
    baseline = next(
        item
        for item in candidates
        if item["strategy"] == BASELINE_STRATEGY
    )

    challengers = [
        item
        for item in candidates
        if item["strategy"] != BASELINE_STRATEGY
    ]

    if not challengers:
        return (
            BASELINE_STRATEGY,
            "No alternative policy was available.",
        )

    challenger = max(
        challengers,
        key=lambda item: (
            item["score"],
            item["return"],
            -item["drawdown"],
        ),
    )

    score_advantage = (
        challenger["score"] - baseline["score"]
    )

    eligible = (
        challenger["trades"]
        >= MINIMUM_TRAINING_TRADES
        and challenger["return"]
        > MINIMUM_CHALLENGER_RETURN
        and challenger["profit_factor"]
        >= MINIMUM_CHALLENGER_PROFIT_FACTOR
        and challenger["drawdown"]
        <= MAXIMUM_CHALLENGER_DRAWDOWN
        and score_advantage
        >= MINIMUM_SCORE_ADVANTAGE
    )

    if eligible:
        return (
            challenger["strategy"],
            (
                "Challenger promoted: "
                f"score advantage={score_advantage:.2f}, "
                f"return={challenger['return']:.2f}%, "
                f"PF={challenger['profit_factor']:.3f}, "
                f"DD={challenger['drawdown']:.2f}%."
            ),
        )

    return (
        BASELINE_STRATEGY,
        (
            "Baseline retained: challenger failed one or more "
            "promotion requirements. "
            f"Score advantage={score_advantage:.2f}, "
            f"return={challenger['return']:.2f}%, "
            f"PF={challenger['profit_factor']:.3f}, "
            f"DD={challenger['drawdown']:.2f}%."
        ),
    )


def run_market(symbol: str, candles) -> dict:
    guarded_balance = INITIAL_BALANCE
    baseline_balance = INITIAL_BALANCE
    fold_results = []

    for fold_number, (start_text, end_text) in enumerate(
        FOLDS,
        start=1,
    ):
        fold_start = start_timestamp(start_text)
        fold_end = end_timestamp(end_text)

        training_candles = [
            candle
            for candle in candles
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
            candles=candles,
            strategy_name=selected_policy,
            fold_start=fold_start,
            fold_end=fold_end,
            starting_balance=guarded_balance,
        )

        baseline_result = run_test_fold(
            symbol=symbol,
            candles=candles,
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

        fold_results.append(
            {
                "fold": fold_number,
                "start": start_text,
                "end": end_text,
                "selected_policy": selected_policy,
                "reason": reason,
                "candidates": candidates,
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
        "folds": fold_results,
        "guarded_return": (
            guarded_balance / INITIAL_BALANCE - 1
        ) * 100,
        "baseline_return": (
            baseline_balance / INITIAL_BALANCE - 1
        ) * 100,
        "guarded_profitable_folds": sum(
            fold["guarded_return"] > 0
            for fold in fold_results
        ),
        "baseline_profitable_folds": sum(
            fold["baseline_return"] > 0
            for fold in fold_results
        ),
        "guarded_worst_drawdown": max(
            fold["guarded_drawdown"]
            for fold in fold_results
        ),
        "baseline_worst_drawdown": max(
            fold["baseline_drawdown"]
            for fold in fold_results
        ),
        "guarded_trades": sum(
            fold["guarded_trades"]
            for fold in fold_results
        ),
        "promotions": sum(
            fold["selected_policy"]
            != BASELINE_STRATEGY
            for fold in fold_results
        ),
    }


def print_market(result: dict) -> None:
    print()
    print("=" * 118)
    print(result["symbol"])
    print("=" * 118)

    for fold in result["folds"]:
        top_scores = ", ".join(
            (
                f"{item['strategy']}="
                f"{item['score']:.2f}"
            )
            for item in fold["candidates"][:3]
        )

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
            "  Top historical scores:",
            top_scores,
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
            "  Return difference:",
            round(
                fold["guarded_return"]
                - fold["baseline_return"],
                2,
            ),
            "percentage points",
        )
        print("-" * 118)

    print("MARKET SUMMARY")
    print(
        "Policy promotions:",
        f"{result['promotions']}/7",
    )
    print(
        "Guarded profitable folds:",
        f"{result['guarded_profitable_folds']}/7",
    )
    print(
        "Baseline profitable folds:",
        f"{result['baseline_profitable_folds']}/7",
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


def main() -> None:
    print("GUARDED ADAPTIVE REGIME POLICY WALK-FORWARD")
    print("=" * 118)
    print(
        "ATR breakout remains the champion unless a challenger "
        "passes all historical promotion rules."
    )
    print(
        "Each decision uses only candles preceding the unseen "
        "test fold."
    )

    results = []

    for symbol, path in MARKETS.items():
        candles = load_candles_from_csv(path)
        result = run_market(symbol, candles)
        results.append(result)
        print_market(result)

    print()
    print("=" * 118)
    print("THREE-MARKET GUARDED SUMMARY")
    print("=" * 118)

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
            f"{result['baseline_worst_drawdown']:5.2f}% | "
            f"Promotions {result['promotions']}/7"
        )

    improved_return_markets = sum(
        result["guarded_return"]
        > result["baseline_return"]
        for result in results
    )

    profitable_guarded_markets = sum(
        result["guarded_return"] > 0
        for result in results
    )

    reduced_drawdown_markets = sum(
        result["guarded_worst_drawdown"]
        < result["baseline_worst_drawdown"]
        for result in results
    )

    total_guarded_trades = sum(
        result["guarded_trades"]
        for result in results
    )

    total_promotions = sum(
        result["promotions"]
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

    promising = (
        improved_return_markets >= 2
        and profitable_guarded_markets >= 2
        and reduced_drawdown_markets >= 2
        and total_guarded_trades >= 250
        and guarded_return_sum > baseline_return_sum
    )

    print()
    print(
        "Markets with improved return:",
        improved_return_markets,
        "/ 3",
    )
    print(
        "Profitable guarded markets:",
        profitable_guarded_markets,
        "/ 3",
    )
    print(
        "Markets with reduced drawdown:",
        reduced_drawdown_markets,
        "/ 3",
    )
    print(
        "Total policy promotions:",
        total_promotions,
        "/ 21",
    )
    print(
        "Total guarded trades:",
        total_guarded_trades,
    )
    print(
        "Sum of guarded market returns:",
        round(guarded_return_sum, 2),
        "%",
    )
    print(
        "Sum of baseline market returns:",
        round(baseline_return_sum, 2),
        "%",
    )

    print()
    print(
        "OVERALL RESULT:",
        (
            "GUARDED ADAPTIVE SELECTION SHOWS PROMISE"
            if promising
            else
            "GUARDED ADAPTIVE SELECTION NOT YET ROBUST"
        ),
    )


if __name__ == "__main__":
    main()
