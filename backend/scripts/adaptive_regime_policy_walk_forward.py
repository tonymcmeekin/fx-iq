from datetime import UTC, datetime, time
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.market_data.csv_loader import load_candles_from_csv
from app.portfolio.engine import run_portfolio_backtest
from app.portfolio.models import PortfolioStrategyConfig


INITIAL_BALANCE = 10_000.0
MINIMUM_TRAINING_TRADES = 20

MARKETS = {
    "EUR_USD": Path("data/oanda_eur_usd_daily.csv"),
    "GBP_USD": Path("data/oanda_gbp_usd_daily.csv"),
    "AUD_USD": Path("data/oanda_aud_usd_daily.csv"),
}

CANDIDATE_POLICIES = [
    "atr_breakout",
    "atr_regime_filtered",
    "atr_regime_allow_ranges",
    "atr_regime_contrarian",
    "atr_regime_sell_bias",
]

FOLDS = [
    ("2013-01-28", "2014-12-16"),
    ("2014-12-17", "2016-11-20"),
    ("2016-11-21", "2018-10-23"),
    ("2018-10-24", "2020-09-27"),
    ("2020-09-28", "2022-08-30"),
    ("2022-08-31", "2024-08-04"),
    ("2024-08-05", "2026-07-09"),
]


def start_timestamp(date_text: str) -> datetime:
    return datetime.combine(
        datetime.fromisoformat(date_text).date(),
        time.min,
        tzinfo=UTC,
    )


def end_timestamp(date_text: str) -> datetime:
    return datetime.combine(
        datetime.fromisoformat(date_text).date(),
        time.max,
        tzinfo=UTC,
    )


def strategy_config(
    strategy_name: str,
    symbol: str,
) -> PortfolioStrategyConfig:
    return PortfolioStrategyConfig(
        strategy_name=strategy_name,
        symbol=symbol,
        stop_loss_percent=1.5,
        take_profit_percent=3.0,
        risk_per_trade_percent=0.5,
        spread_pips=1.0,
        slippage_pips=0.5,
    )


def profit_factor(trades) -> float:
    gross_profit = sum(
        trade.net_pnl
        for trade in trades
        if trade.net_pnl > 0
    )

    gross_loss = abs(
        sum(
            trade.net_pnl
            for trade in trades
            if trade.net_pnl < 0
        )
    )

    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0

    return gross_profit / gross_loss


def policy_score(result) -> float:
    if result.total_trades < MINIMUM_TRAINING_TRADES:
        return -1_000_000.0

    pf = profit_factor(result.trades)

    capped_pf = min(pf, 3.0)

    return (
        result.return_percent
        + (capped_pf - 1.0) * 3.0
        - result.max_drawdown_percent * 0.75
    )


def choose_policy(
    symbol: str,
    training_candles,
) -> tuple[str, list[dict]]:
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

        pf = profit_factor(result.trades)
        score = policy_score(result)

        candidates.append(
            {
                "strategy": strategy_name,
                "trades": result.total_trades,
                "return": result.return_percent,
                "drawdown": result.max_drawdown_percent,
                "profit_factor": pf,
                "score": score,
            }
        )

    candidates.sort(
        key=lambda candidate: (
            candidate["score"],
            candidate["return"],
            -candidate["drawdown"],
        ),
        reverse=True,
    )

    return candidates[0]["strategy"], candidates


def run_test_fold(
    symbol: str,
    candles,
    strategy_name: str,
    fold_start: datetime,
    fold_end: datetime,
    starting_balance: float,
):
    available_candles = [
        candle
        for candle in candles
        if candle.timestamp <= fold_end
    ]

    return run_portfolio_backtest(
        candles_by_symbol={
            symbol: available_candles,
        },
        strategy_configs=[
            strategy_config(
                strategy_name,
                symbol,
            )
        ],
        initial_balance=starting_balance,
        max_portfolio_leverage=30.0,
        max_total_risk_percent=0.5,
        trading_start_timestamp=fold_start,
    )


def run_market(symbol: str, candles) -> dict:
    adaptive_balance = INITIAL_BALANCE
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

        selected_policy, candidates = choose_policy(
            symbol=symbol,
            training_candles=training_candles,
        )

        adaptive_result = run_test_fold(
            symbol=symbol,
            candles=candles,
            strategy_name=selected_policy,
            fold_start=fold_start,
            fold_end=fold_end,
            starting_balance=adaptive_balance,
        )

        baseline_result = run_test_fold(
            symbol=symbol,
            candles=candles,
            strategy_name="atr_breakout",
            fold_start=fold_start,
            fold_end=fold_end,
            starting_balance=baseline_balance,
        )

        adaptive_return = (
            adaptive_result.final_balance
            / adaptive_balance
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
                "training_candidates": candidates,
                "adaptive_trades": adaptive_result.total_trades,
                "adaptive_return": adaptive_return,
                "adaptive_drawdown": (
                    adaptive_result.max_drawdown_percent
                ),
                "adaptive_pf": profit_factor(
                    adaptive_result.trades
                ),
                "baseline_trades": baseline_result.total_trades,
                "baseline_return": baseline_return,
                "baseline_drawdown": (
                    baseline_result.max_drawdown_percent
                ),
                "baseline_pf": profit_factor(
                    baseline_result.trades
                ),
            }
        )

        adaptive_balance = adaptive_result.final_balance
        baseline_balance = baseline_result.final_balance

    return {
        "symbol": symbol,
        "folds": fold_results,
        "adaptive_balance": adaptive_balance,
        "baseline_balance": baseline_balance,
        "adaptive_return": (
            adaptive_balance / INITIAL_BALANCE - 1
        ) * 100,
        "baseline_return": (
            baseline_balance / INITIAL_BALANCE - 1
        ) * 100,
        "adaptive_winning_folds": sum(
            fold["adaptive_return"] > 0
            for fold in fold_results
        ),
        "baseline_winning_folds": sum(
            fold["baseline_return"] > 0
            for fold in fold_results
        ),
        "adaptive_worst_drawdown": max(
            fold["adaptive_drawdown"]
            for fold in fold_results
        ),
        "baseline_worst_drawdown": max(
            fold["baseline_drawdown"]
            for fold in fold_results
        ),
        "adaptive_trades": sum(
            fold["adaptive_trades"]
            for fold in fold_results
        ),
        "baseline_trades": sum(
            fold["baseline_trades"]
            for fold in fold_results
        ),
    }


def print_market_result(result: dict) -> None:
    print()
    print("=" * 118)
    print(result["symbol"])
    print("=" * 118)

    for fold in result["folds"]:
        top_candidates = fold["training_candidates"][:3]

        candidate_text = ", ".join(
            (
                f"{item['strategy']}="
                f"{item['score']:.2f}"
            )
            for item in top_candidates
        )

        print(
            f"Fold {fold['fold']}: "
            f"{fold['start']} to {fold['end']}"
        )
        print(
            "  Historical selection:",
            fold["selected_policy"],
        )
        print(
            "  Top training scores:",
            candidate_text,
        )
        print(
            "  Adaptive | "
            f"Trades {fold['adaptive_trades']:3d} | "
            f"Return {fold['adaptive_return']:7.2f}% | "
            f"PF {fold['adaptive_pf']:6.3f} | "
            f"DD {fold['adaptive_drawdown']:5.2f}%"
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
                fold["adaptive_return"]
                - fold["baseline_return"],
                2,
            ),
            "percentage points",
        )
        print("-" * 118)

    print("MARKET SUMMARY")
    print(
        "Adaptive profitable folds:",
        f"{result['adaptive_winning_folds']}/7",
    )
    print(
        "Baseline profitable folds:",
        f"{result['baseline_winning_folds']}/7",
    )
    print(
        "Adaptive sequential return:",
        round(result["adaptive_return"], 2),
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
            result["adaptive_return"]
            - result["baseline_return"],
            2,
        ),
        "percentage points",
    )
    print(
        "Adaptive worst drawdown:",
        round(result["adaptive_worst_drawdown"], 2),
        "%",
    )
    print(
        "Baseline worst drawdown:",
        round(result["baseline_worst_drawdown"], 2),
        "%",
    )
    print(
        "Adaptive trades:",
        result["adaptive_trades"],
    )


def main() -> None:
    print("ADAPTIVE REGIME POLICY WALK-FORWARD")
    print("=" * 118)
    print(
        "Policy choice for each fold uses only candles dated "
        "before that fold begins."
    )
    print(
        "Training score = return + profit-factor reward "
        "- drawdown penalty."
    )
    print(
        "The selected policy is frozen throughout the next "
        "unseen fold."
    )

    results = []

    for symbol, path in MARKETS.items():
        candles = load_candles_from_csv(path)

        result = run_market(
            symbol=symbol,
            candles=candles,
        )

        results.append(result)
        print_market_result(result)

    print()
    print("=" * 118)
    print("THREE-MARKET ADAPTIVE SUMMARY")
    print("=" * 118)

    for result in results:
        print(
            f"{result['symbol']:7s} | "
            f"Adaptive {result['adaptive_return']:7.2f}% | "
            f"Baseline {result['baseline_return']:7.2f}% | "
            f"Difference "
            f"{result['adaptive_return'] - result['baseline_return']:7.2f}pp | "
            f"Adaptive DD {result['adaptive_worst_drawdown']:5.2f}% | "
            f"Baseline DD {result['baseline_worst_drawdown']:5.2f}%"
        )

    improved_return_markets = sum(
        result["adaptive_return"]
        > result["baseline_return"]
        for result in results
    )

    profitable_adaptive_markets = sum(
        result["adaptive_return"] > 0
        for result in results
    )

    reduced_drawdown_markets = sum(
        result["adaptive_worst_drawdown"]
        < result["baseline_worst_drawdown"]
        for result in results
    )

    total_adaptive_trades = sum(
        result["adaptive_trades"]
        for result in results
    )

    total_adaptive_return = sum(
        result["adaptive_return"]
        for result in results
    )

    total_baseline_return = sum(
        result["baseline_return"]
        for result in results
    )

    promising = (
        improved_return_markets >= 2
        and profitable_adaptive_markets >= 2
        and reduced_drawdown_markets >= 2
        and total_adaptive_trades >= 200
        and total_adaptive_return > total_baseline_return
    )

    print()
    print(
        "Markets with improved return:",
        improved_return_markets,
        "/ 3",
    )
    print(
        "Profitable adaptive markets:",
        profitable_adaptive_markets,
        "/ 3",
    )
    print(
        "Markets with reduced drawdown:",
        reduced_drawdown_markets,
        "/ 3",
    )
    print(
        "Total adaptive trades:",
        total_adaptive_trades,
    )
    print(
        "Sum of adaptive market returns:",
        round(total_adaptive_return, 2),
        "%",
    )
    print(
        "Sum of baseline market returns:",
        round(total_baseline_return, 2),
        "%",
    )

    print()
    print(
        "OVERALL RESULT:",
        (
            "ADAPTIVE POLICY SELECTION SHOWS PROMISE"
            if promising
            else
            "ADAPTIVE POLICY SELECTION NOT YET ROBUST"
        ),
    )


if __name__ == "__main__":
    main()
