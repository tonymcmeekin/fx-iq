from collections import defaultdict
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.ai.regime import detect_market_regime
from app.market_data.csv_loader import load_candles_from_csv
from app.portfolio.engine import run_portfolio_backtest
from scripts.adaptive_regime_policy_walk_forward import (
    FOLDS,
    INITIAL_BALANCE,
    end_timestamp,
    profit_factor,
    start_timestamp,
    strategy_config,
)


MARKETS = {
    "EUR_USD": Path("data/oanda_eur_usd_daily.csv"),
    "GBP_USD": Path("data/oanda_gbp_usd_daily.csv"),
    "AUD_USD": Path("data/oanda_aud_usd_daily.csv"),
    "USD_JPY": Path("data/oanda_usd_jpy_daily.csv"),
    "USD_CAD": Path("data/oanda_usd_cad_daily.csv"),
    "NZD_USD": Path("data/oanda_nzd_usd_daily.csv"),
}

DEVELOPMENT_FOLDS = FOLDS[:6]

STRATEGY_NAME = "atr_breakout"
BASE_RISK_PERCENT = 0.5
REDUCED_RISK_MULTIPLIER = 0.5
REGIME_LOOKBACK = 50

MINIMUM_TOTAL_TRADES = 40
MINIMUM_MARKETS = 4


def fold_return(
    result,
    starting_balance: float,
) -> float:
    return (
        result.final_balance
        / starting_balance
        - 1
    ) * 100


def classify_trade(
    candles,
    trade,
):
    historical = [
        candle
        for candle in candles
        if candle.timestamp <= trade.signal_timestamp
    ]

    if len(historical) < REGIME_LOOKBACK:
        return None

    regime = detect_market_regime(
        historical,
        lookback=REGIME_LOOKBACK,
    )

    return {
        "trend": regime.trend,
        "volatility": regime.volatility,
        "direction": trade.direction,
    }


def collect_fixed_records(
    candles_by_market,
) -> list[dict]:
    records = []

    for symbol, candles in candles_by_market.items():
        for fold_number, (
            start_text,
            end_text,
        ) in enumerate(
            DEVELOPMENT_FOLDS,
            start=1,
        ):
            fold_start = start_timestamp(start_text)
            fold_end = end_timestamp(end_text)

            available = [
                candle
                for candle in candles
                if candle.timestamp <= fold_end
            ]

            result = run_portfolio_backtest(
                candles_by_symbol={
                    symbol: available,
                },
                strategy_configs=[
                    strategy_config(
                        STRATEGY_NAME,
                        symbol,
                    )
                ],
                initial_balance=INITIAL_BALANCE,
                max_portfolio_leverage=30.0,
                max_total_risk_percent=BASE_RISK_PERCENT,
                trading_start_timestamp=fold_start,
            )

            for trade in result.trades:
                classification = classify_trade(
                    candles=available,
                    trade=trade,
                )

                if classification is None:
                    continue

                records.append(
                    {
                        "market": symbol,
                        "fold": fold_number,
                        "trend": classification["trend"],
                        "volatility": (
                            classification["volatility"]
                        ),
                        "direction": (
                            classification["direction"]
                        ),
                        "return": (
                            trade.account_return_percent
                        ),
                    }
                )

    return records


def average_return(
    records: list[dict],
) -> float:
    if not records:
        return 0.0

    return sum(
        record["return"]
        for record in records
    ) / len(records)


def discover_robust_negative_groups(
    training_records: list[dict],
) -> dict[tuple[str, str, str], dict]:
    grouped = defaultdict(list)

    for record in training_records:
        key = (
            record["trend"],
            record["volatility"],
            record["direction"],
        )

        grouped[key].append(record)

    selected = {}

    for key, records in grouped.items():
        represented_markets = {
            record["market"]
            for record in records
        }

        if len(records) < MINIMUM_TOTAL_TRADES:
            continue

        if len(represented_markets) < MINIMUM_MARKETS:
            continue

        overall_average = average_return(records)

        if overall_average >= 0:
            continue

        exclusion_averages = {}

        for excluded_market in MARKETS:
            retained = [
                record
                for record in records
                if record["market"] != excluded_market
            ]

            exclusion_averages[
                excluded_market
            ] = average_return(retained)

        if not all(
            value < 0
            for value in exclusion_averages.values()
        ):
            continue

        selected[key] = {
            "trades": len(records),
            "markets": len(represented_markets),
            "average_return": overall_average,
            "exclusion_averages": exclusion_averages,
        }

    return selected


def create_frozen_adjuster(
    reduced_groups: set[tuple[str, str, str]],
):
    def adjuster(
        config,
        historical_candles,
        direction,
    ) -> float:
        if len(historical_candles) < REGIME_LOOKBACK:
            return config.risk_per_trade_percent

        try:
            regime = detect_market_regime(
                historical_candles,
                lookback=REGIME_LOOKBACK,
            )
        except ValueError:
            return config.risk_per_trade_percent

        key = (
            regime.trend,
            regime.volatility,
            direction,
        )

        if key not in reduced_groups:
            return config.risk_per_trade_percent

        return (
            config.risk_per_trade_percent
            * REDUCED_RISK_MULTIPLIER
        )

    return adjuster


def run_fold(
    symbol: str,
    candles,
    fold_start,
    fold_end,
    starting_balance: float,
    risk_adjuster=None,
):
    available = [
        candle
        for candle in candles
        if candle.timestamp <= fold_end
    ]

    arguments = {
        "candles_by_symbol": {
            symbol: available,
        },
        "strategy_configs": [
            strategy_config(
                STRATEGY_NAME,
                symbol,
            )
        ],
        "initial_balance": starting_balance,
        "max_portfolio_leverage": 30.0,
        "max_total_risk_percent": BASE_RISK_PERCENT,
        "trading_start_timestamp": fold_start,
    }

    if risk_adjuster is not None:
        arguments[
            "risk_percent_adjuster"
        ] = risk_adjuster

    return run_portfolio_backtest(**arguments)


def estimated_risk_percentages(
    result,
    starting_balance: float,
) -> list[float]:
    balance = starting_balance
    percentages = []

    for trade in result.trades:
        if balance > 0:
            percentages.append(
                trade.risk_amount
                / balance
                * 100
            )

        balance += trade.net_pnl

    return percentages


def print_rule_snapshot(
    fold_number: int,
    training_records: list[dict],
    selected_groups: dict,
) -> None:
    print()
    print("=" * 122)
    print(
        f"POLICY SNAPSHOT BEFORE FOLD {fold_number}"
    )
    print("=" * 122)
    print(
        "Training records available:",
        len(training_records),
    )
    print(
        "Training folds:",
        (
            f"1 to {fold_number - 1}"
            if fold_number > 1
            else "None"
        ),
    )

    if not selected_groups:
        print(
            "Frozen reduced-risk groups: None"
        )
        return

    print("Frozen reduced-risk groups:")

    for key, details in sorted(
        selected_groups.items()
    ):
        print(
            " -",
            " | ".join(key),
            "| Trades:",
            details["trades"],
            "| Markets:",
            details["markets"],
            "| Average:",
            round(
                details["average_return"],
                4,
            ),
            "%",
        )


def main() -> None:
    print(
        "TRADE IQ NESTED SELECTIVE REGIME-RISK "
        "WALK-FORWARD"
    )
    print("=" * 122)
    print(
        "Before each fold, risk rules are learned only from "
        "earlier completed folds."
    )
    print(
        "The rules are then frozen and tested on the next "
        "chronological fold."
    )
    print(
        "No external holdout data is accessed or reused."
    )

    candles_by_market = {
        symbol: load_candles_from_csv(path)
        for symbol, path in MARKETS.items()
    }

    print()
    print("Collecting fixed-risk development records...")

    fixed_records = collect_fixed_records(
        candles_by_market
    )

    print(
        "Classified fixed-risk records:",
        len(fixed_records),
    )

    fixed_balances = {
        symbol: INITIAL_BALANCE
        for symbol in MARKETS
    }

    nested_balances = {
        symbol: INITIAL_BALANCE
        for symbol in MARKETS
    }

    market_results = {
        symbol: {
            "fixed_folds": [],
            "nested_folds": [],
            "fixed_worst_drawdown": 0.0,
            "nested_worst_drawdown": 0.0,
            "reduced_trades": 0,
            "trades": 0,
        }
        for symbol in MARKETS
    }

    fold_summaries = []

    for fold_number, (
        start_text,
        end_text,
    ) in enumerate(
        DEVELOPMENT_FOLDS,
        start=1,
    ):
        training_records = [
            record
            for record in fixed_records
            if record["fold"] < fold_number
        ]

        selected_groups = (
            discover_robust_negative_groups(
                training_records
            )
        )

        reduced_group_keys = set(
            selected_groups
        )

        frozen_adjuster = create_frozen_adjuster(
            reduced_group_keys
        )

        print_rule_snapshot(
            fold_number=fold_number,
            training_records=training_records,
            selected_groups=selected_groups,
        )

        fold_start = start_timestamp(start_text)
        fold_end = end_timestamp(end_text)

        fixed_fold_return_sum = 0.0
        nested_fold_return_sum = 0.0
        fold_trade_count = 0
        fold_reduced_trades = 0
        fold_lower_drawdown_markets = 0

        print()
        print(
            f"FOLD {fold_number}: "
            f"{start_text} to {end_text}"
        )
        print("-" * 122)

        for symbol, candles in candles_by_market.items():
            fixed_starting_balance = (
                fixed_balances[symbol]
            )
            nested_starting_balance = (
                nested_balances[symbol]
            )

            fixed_result = run_fold(
                symbol=symbol,
                candles=candles,
                fold_start=fold_start,
                fold_end=fold_end,
                starting_balance=(
                    fixed_starting_balance
                ),
            )

            nested_result = run_fold(
                symbol=symbol,
                candles=candles,
                fold_start=fold_start,
                fold_end=fold_end,
                starting_balance=(
                    nested_starting_balance
                ),
                risk_adjuster=frozen_adjuster,
            )

            if (
                fixed_result.total_trades
                != nested_result.total_trades
            ):
                raise RuntimeError(
                    f"{symbol} fold {fold_number}: "
                    "risk policy changed trade count."
                )

            fixed_return = fold_return(
                fixed_result,
                fixed_starting_balance,
            )

            nested_return = fold_return(
                nested_result,
                nested_starting_balance,
            )

            nested_risk_percentages = (
                estimated_risk_percentages(
                    nested_result,
                    nested_starting_balance,
                )
            )

            reduced_trades = sum(
                risk_percent
                < BASE_RISK_PERCENT - 0.01
                for risk_percent
                in nested_risk_percentages
            )

            fixed_balances[
                symbol
            ] = fixed_result.final_balance

            nested_balances[
                symbol
            ] = nested_result.final_balance

            details = market_results[symbol]

            details["fixed_folds"].append(
                fixed_return
            )
            details["nested_folds"].append(
                nested_return
            )
            details[
                "fixed_worst_drawdown"
            ] = max(
                details["fixed_worst_drawdown"],
                fixed_result.max_drawdown_percent,
            )
            details[
                "nested_worst_drawdown"
            ] = max(
                details["nested_worst_drawdown"],
                nested_result.max_drawdown_percent,
            )
            details[
                "reduced_trades"
            ] += reduced_trades
            details[
                "trades"
            ] += fixed_result.total_trades

            fixed_fold_return_sum += fixed_return
            nested_fold_return_sum += nested_return
            fold_trade_count += (
                fixed_result.total_trades
            )
            fold_reduced_trades += reduced_trades

            if (
                nested_result.max_drawdown_percent
                < fixed_result.max_drawdown_percent
            ):
                fold_lower_drawdown_markets += 1

            print(
                f"{symbol:7s} | "
                f"Fixed {fixed_return:7.2f}% | "
                f"Nested {nested_return:7.2f}% | "
                f"Difference "
                f"{nested_return - fixed_return:7.2f}pp | "
                f"Trades {fixed_result.total_trades:3d} | "
                f"Reduced {reduced_trades:3d} | "
                f"Fixed DD "
                f"{fixed_result.max_drawdown_percent:5.2f}% | "
                f"Nested DD "
                f"{nested_result.max_drawdown_percent:5.2f}% | "
                f"PF "
                f"{profit_factor(nested_result.trades):6.3f}"
            )

        fold_summaries.append(
            {
                "fold": fold_number,
                "fixed_return_sum": (
                    fixed_fold_return_sum
                ),
                "nested_return_sum": (
                    nested_fold_return_sum
                ),
                "trades": fold_trade_count,
                "reduced_trades": (
                    fold_reduced_trades
                ),
                "rules": len(
                    reduced_group_keys
                ),
                "lower_drawdown_markets": (
                    fold_lower_drawdown_markets
                ),
            }
        )

        print("-" * 122)
        print(
            "Fold fixed return sum:",
            round(
                fixed_fold_return_sum,
                2,
            ),
            "%",
        )
        print(
            "Fold nested return sum:",
            round(
                nested_fold_return_sum,
                2,
            ),
            "%",
        )
        print(
            "Fold difference:",
            round(
                nested_fold_return_sum
                - fixed_fold_return_sum,
                2,
            ),
            "percentage points",
        )
        print(
            "Reduced-risk trades:",
            fold_reduced_trades,
            "/",
            fold_trade_count,
        )
        print(
            "Markets with lower fold drawdown:",
            fold_lower_drawdown_markets,
            "/",
            len(MARKETS),
        )

    print()
    print("=" * 122)
    print("MARKET SUMMARY")
    print("=" * 122)

    markets_beating_fixed = 0
    markets_lower_drawdown = 0

    fixed_return_sum = 0.0
    nested_return_sum = 0.0
    total_trades = 0
    total_reduced_trades = 0

    for symbol, details in market_results.items():
        fixed_return = (
            fixed_balances[symbol]
            / INITIAL_BALANCE
            - 1
        ) * 100

        nested_return = (
            nested_balances[symbol]
            / INITIAL_BALANCE
            - 1
        ) * 100

        if nested_return > fixed_return:
            markets_beating_fixed += 1

        if (
            details["nested_worst_drawdown"]
            < details["fixed_worst_drawdown"]
        ):
            markets_lower_drawdown += 1

        fixed_return_sum += fixed_return
        nested_return_sum += nested_return
        total_trades += details["trades"]
        total_reduced_trades += (
            details["reduced_trades"]
        )

        print(
            f"{symbol:7s} | "
            f"Fixed {fixed_return:7.2f}% | "
            f"Nested {nested_return:7.2f}% | "
            f"Difference "
            f"{nested_return - fixed_return:7.2f}pp | "
            f"Fixed DD "
            f"{details['fixed_worst_drawdown']:5.2f}% | "
            f"Nested DD "
            f"{details['nested_worst_drawdown']:5.2f}% | "
            f"Reduced "
            f"{details['reduced_trades']:3d}/"
            f"{details['trades']:3d}"
        )

    print()
    print("=" * 122)
    print("NESTED DEVELOPMENT SUMMARY")
    print("=" * 122)
    print(
        "Markets where nested policy beats fixed:",
        markets_beating_fixed,
        "/",
        len(MARKETS),
    )
    print(
        "Markets where nested policy lowers drawdown:",
        markets_lower_drawdown,
        "/",
        len(MARKETS),
    )
    print(
        "Sum of fixed sequential returns:",
        round(
            fixed_return_sum,
            2,
        ),
        "%",
    )
    print(
        "Sum of nested sequential returns:",
        round(
            nested_return_sum,
            2,
        ),
        "%",
    )
    print(
        "Nested versus fixed:",
        round(
            nested_return_sum
            - fixed_return_sum,
            2,
        ),
        "percentage points",
    )
    print(
        "Total trades:",
        total_trades,
    )
    print(
        "Trades receiving reduced risk:",
        total_reduced_trades,
    )

    profitable_nested_markets = sum(
        balance > INITIAL_BALANCE
        for balance in nested_balances.values()
    )

    passed = (
        markets_beating_fixed >= 4
        and markets_lower_drawdown >= 4
        and nested_return_sum > fixed_return_sum
        and nested_return_sum > 0
        and profitable_nested_markets >= 4
    )

    print(
        "Profitable nested markets:",
        profitable_nested_markets,
        "/",
        len(MARKETS),
    )

    print()
    print(
        "DEVELOPMENT RESULT:",
        "PASSED"
        if passed
        else "FAILED",
    )
    print(
        "RESEARCH STATUS: "
        "NESTED_DEVELOPMENT_ONLY"
    )
    print(
        "The external holdout was not accessed or reused."
    )


if __name__ == "__main__":
    main()
