from collections import defaultdict
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.indicators.volatility import average_true_range
from app.market_data.csv_loader import load_candles_from_csv
from app.portfolio.engine import run_portfolio_backtest
from app.portfolio.models import PortfolioStrategyConfig
from app.signals.models import TradeSignal
from app.strategies.atr_breakout import (
    generate_atr_breakout_signal,
)
from app.strategies.manager import STRATEGIES
from scripts.adaptive_regime_policy_walk_forward import (
    FOLDS,
    INITIAL_BALANCE,
    end_timestamp,
    profit_factor,
    start_timestamp,
)
from scripts.analyse_atr_breakout_quality import (
    collect_market_records,
    percentile,
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

BASE_RISK_PERCENT = 0.5
BREAKOUT_PERIOD = 20
ATR_PERIOD = 14
ATR_MULTIPLIER = 0.25

MINIMUM_TRAINING_FOLDS = 2
MINIMUM_TRAINING_RECORDS = 150

POLICIES = [
    "close_location",
    "channel_width",
    "momentum_20",
    "combined",
]


def strategy_config(
    symbol: str,
    strategy_name: str,
) -> PortfolioStrategyConfig:
    return PortfolioStrategyConfig(
        strategy_name=strategy_name,
        symbol=symbol,
        stop_loss_percent=1.5,
        take_profit_percent=3.0,
        risk_per_trade_percent=BASE_RISK_PERCENT,
        spread_pips=1.0,
        slippage_pips=0.5,
    )


def signal_features(candles, direction):
    minimum_required = max(
        BREAKOUT_PERIOD + 1,
        ATR_PERIOD + 1,
        21,
    )

    if len(candles) < minimum_required:
        return None

    current = candles[-1]
    previous_channel = candles[
        -(BREAKOUT_PERIOD + 1):-1
    ]

    previous_high = max(
        candle.high
        for candle in previous_channel
    )

    previous_low = min(
        candle.low
        for candle in previous_channel
    )

    atr = average_true_range(
        candles,
        period=ATR_PERIOD,
    )

    if atr <= 0:
        return None

    candle_range = (
        current.high - current.low
    )

    if direction == "BUY":
        directional_close_location = (
            (current.close - current.low)
            / candle_range
            if candle_range > 0
            else 0.5
        )

        momentum_20_atr = (
            current.close
            - candles[-21].close
        ) / atr

    elif direction == "SELL":
        directional_close_location = (
            (current.high - current.close)
            / candle_range
            if candle_range > 0
            else 0.5
        )

        momentum_20_atr = (
            candles[-21].close
            - current.close
        ) / atr

    else:
        return None

    channel_width_atr = (
        previous_high - previous_low
    ) / atr

    return {
        "directional_close_location": (
            directional_close_location
        ),
        "channel_width_atr": (
            channel_width_atr
        ),
        "momentum_20_atr": (
            momentum_20_atr
        ),
    }


def learn_thresholds(records):
    if not records:
        return None

    close_values = sorted(
        record[
            "directional_close_location"
        ]
        for record in records
    )

    channel_values = sorted(
        record["channel_width_atr"]
        for record in records
    )

    momentum_values = sorted(
        record["momentum_20_atr"]
        for record in records
    )

    return {
        "minimum_close_location": percentile(
            close_values,
            1 / 3,
        ),
        "maximum_channel_width": percentile(
            channel_values,
            2 / 3,
        ),
        "maximum_momentum_20": percentile(
            momentum_values,
            2 / 3,
        ),
    }


def quality_decision(
    features,
    thresholds,
    policy,
):
    close_pass = (
        features[
            "directional_close_location"
        ]
        > thresholds[
            "minimum_close_location"
        ]
    )

    channel_pass = (
        features["channel_width_atr"]
        < thresholds[
            "maximum_channel_width"
        ]
    )

    momentum_pass = (
        features["momentum_20_atr"]
        < thresholds[
            "maximum_momentum_20"
        ]
    )

    if policy == "close_location":
        return close_pass

    if policy == "channel_width":
        return channel_pass

    if policy == "momentum_20":
        return momentum_pass

    if policy == "combined":
        return (
            close_pass
            and channel_pass
            and momentum_pass
        )

    raise ValueError(
        f"Unknown quality policy: {policy}"
    )


def create_quality_strategy(
    thresholds,
    policy,
    counter,
):
    def generate_signal(candles):
        base_signal = (
            generate_atr_breakout_signal(
                candles
            )
        )

        if base_signal.direction == "HOLD":
            return base_signal

        features = signal_features(
            candles,
            base_signal.direction,
        )

        if features is None:
            return TradeSignal(
                symbol=base_signal.symbol,
                direction="HOLD",
                confidence=0.0,
                strategy_name=(
                    f"atr_quality_{policy}"
                ),
                reason=(
                    "Insufficient history for "
                    "quality evaluation."
                ),
            )

        approved = quality_decision(
            features=features,
            thresholds=thresholds,
            policy=policy,
        )

        if not approved:
            counter["rejected"] += 1

            return TradeSignal(
                symbol=base_signal.symbol,
                direction="HOLD",
                confidence=0.0,
                strategy_name=(
                    f"atr_quality_{policy}"
                ),
                reason=(
                    f"ATR breakout rejected by "
                    f"{policy} quality policy."
                ),
            )

        counter["approved"] += 1

        return TradeSignal(
            symbol=base_signal.symbol,
            direction=base_signal.direction,
            confidence=base_signal.confidence,
            strategy_name=(
                f"atr_quality_{policy}"
            ),
            reason=(
                f"ATR breakout approved by "
                f"{policy} quality policy."
            ),
        )

    return generate_signal


def run_backtest(
    symbol,
    candles,
    fold_start,
    fold_end,
    starting_balance,
    strategy_name,
):
    available = [
        candle
        for candle in candles
        if candle.timestamp <= fold_end
    ]

    return run_portfolio_backtest(
        candles_by_symbol={
            symbol: available,
        },
        strategy_configs=[
            strategy_config(
                symbol=symbol,
                strategy_name=strategy_name,
            )
        ],
        initial_balance=starting_balance,
        max_portfolio_leverage=30.0,
        max_total_risk_percent=(
            BASE_RISK_PERCENT
        ),
        trading_start_timestamp=fold_start,
    )


def fold_return(
    result,
    starting_balance,
):
    return (
        result.final_balance
        / starting_balance
        - 1
    ) * 100


def collect_all_records(
    candles_by_market,
):
    records = []

    for symbol, candles in (
        candles_by_market.items()
    ):
        records.extend(
            collect_market_records(
                symbol=symbol,
                candles=candles,
            )
        )

    return records


def training_records_before_fold(
    records,
    fold_number,
):
    return [
        record
        for record in records
        if record["fold"] < fold_number
    ]


def thresholds_available(
    training_records,
    fold_number,
):
    completed_folds = fold_number - 1

    return (
        completed_folds
        >= MINIMUM_TRAINING_FOLDS
        and len(training_records)
        >= MINIMUM_TRAINING_RECORDS
    )


def result_summary(
    market_results,
    policy,
):
    fixed_returns = []
    policy_returns = []

    fixed_drawdowns = []
    policy_drawdowns = []

    total_fixed_trades = 0
    total_policy_trades = 0

    for result in market_results.values():
        fixed_returns.append(
            result["fixed_return"]
        )

        policy_returns.append(
            result[
                f"{policy}_return"
            ]
        )

        fixed_drawdowns.append(
            result[
                "fixed_worst_drawdown"
            ]
        )

        policy_drawdowns.append(
            result[
                f"{policy}_worst_drawdown"
            ]
        )

        total_fixed_trades += (
            result["fixed_trades"]
        )

        total_policy_trades += (
            result[
                f"{policy}_trades"
            ]
        )

    return {
        "fixed_sum": sum(fixed_returns),
        "policy_sum": sum(
            policy_returns
        ),
        "difference": (
            sum(policy_returns)
            - sum(fixed_returns)
        ),
        "markets_beating_fixed": sum(
            policy_return
            > fixed_return
            for policy_return, fixed_return
            in zip(
                policy_returns,
                fixed_returns,
            )
        ),
        "markets_lower_drawdown": sum(
            policy_drawdown
            < fixed_drawdown
            for policy_drawdown,
            fixed_drawdown
            in zip(
                policy_drawdowns,
                fixed_drawdowns,
            )
        ),
        "profitable_markets": sum(
            value > 0
            for value in policy_returns
        ),
        "fixed_trades": (
            total_fixed_trades
        ),
        "policy_trades": (
            total_policy_trades
        ),
    }


def main():
    print(
        "TRADE IQ NESTED ATR QUALITY-FILTER "
        "WALK-FORWARD"
    )
    print("=" * 126)
    print(
        "Quality thresholds are learned only "
        "from earlier completed folds."
    )
    print(
        "Each candidate feature is tested "
        "independently before testing the "
        "combined filter."
    )
    print(
        "No external holdout data is accessed "
        "or reused."
    )

    candles_by_market = {
        symbol: load_candles_from_csv(path)
        for symbol, path in MARKETS.items()
    }

    print()
    print(
        "Collecting fixed-risk development "
        "records..."
    )

    all_records = collect_all_records(
        candles_by_market
    )

    print(
        "Classified fixed-risk records:",
        len(all_records),
    )

    balances = {
        symbol: {
            "fixed": INITIAL_BALANCE,
            **{
                policy: INITIAL_BALANCE
                for policy in POLICIES
            },
        }
        for symbol in MARKETS
    }

    market_results = {
        symbol: {
            "fixed_trades": 0,
            **{
                f"{policy}_trades": 0
                for policy in POLICIES
            },
            "fixed_worst_drawdown": 0.0,
            **{
                f"{policy}_worst_drawdown": 0.0
                for policy in POLICIES
            },
        }
        for symbol in MARKETS
    }

    for fold_number, (
        start_text,
        end_text,
    ) in enumerate(
        DEVELOPMENT_FOLDS,
        start=1,
    ):
        fold_start = start_timestamp(
            start_text
        )

        fold_end = end_timestamp(
            end_text
        )

        training_records = (
            training_records_before_fold(
                all_records,
                fold_number,
            )
        )

        active = thresholds_available(
            training_records,
            fold_number,
        )

        thresholds = (
            learn_thresholds(
                training_records
            )
            if active
            else None
        )

        print()
        print("=" * 126)
        print(
            f"POLICY SNAPSHOT BEFORE FOLD "
            f"{fold_number}"
        )
        print("=" * 126)
        print(
            "Training records:",
            len(training_records),
        )
        print(
            "Completed training folds:",
            fold_number - 1,
        )

        if thresholds is None:
            print(
                "Quality filters active: No"
            )
        else:
            print(
                "Quality filters active: Yes"
            )
            print(
                "Minimum close location:",
                round(
                    thresholds[
                        "minimum_close_location"
                    ],
                    4,
                ),
            )
            print(
                "Maximum channel width / ATR:",
                round(
                    thresholds[
                        "maximum_channel_width"
                    ],
                    4,
                ),
            )
            print(
                "Maximum 20-candle momentum / ATR:",
                round(
                    thresholds[
                        "maximum_momentum_20"
                    ],
                    4,
                ),
            )

        print()
        print(
            f"FOLD {fold_number}: "
            f"{start_text} to {end_text}"
        )
        print("-" * 126)

        for symbol, candles in (
            candles_by_market.items()
        ):
            fixed_start = balances[
                symbol
            ]["fixed"]

            fixed = run_backtest(
                symbol=symbol,
                candles=candles,
                fold_start=fold_start,
                fold_end=fold_end,
                starting_balance=fixed_start,
                strategy_name="atr_breakout",
            )

            fixed_return = fold_return(
                fixed,
                fixed_start,
            )

            balances[
                symbol
            ]["fixed"] = fixed.final_balance

            market_results[
                symbol
            ]["fixed_trades"] += (
                fixed.total_trades
            )

            market_results[
                symbol
            ][
                "fixed_worst_drawdown"
            ] = max(
                market_results[
                    symbol
                ][
                    "fixed_worst_drawdown"
                ],
                fixed.max_drawdown_percent,
            )

            line = (
                f"{symbol} | "
                f"Fixed {fixed_return:7.2f}% "
                f"({fixed.total_trades:2d} trades)"
            )

            for policy in POLICIES:
                policy_start = balances[
                    symbol
                ][policy]

                if thresholds is None:
                    policy_result = (
                        run_backtest(
                            symbol=symbol,
                            candles=candles,
                            fold_start=fold_start,
                            fold_end=fold_end,
                            starting_balance=(
                                policy_start
                            ),
                            strategy_name=(
                                "atr_breakout"
                            ),
                        )
                    )

                    rejected = 0

                else:
                    strategy_name = (
                        f"_nested_quality_"
                        f"{policy}"
                    )

                    counter = {
                        "approved": 0,
                        "rejected": 0,
                    }

                    STRATEGIES[
                        strategy_name
                    ] = create_quality_strategy(
                        thresholds=thresholds,
                        policy=policy,
                        counter=counter,
                    )

                    try:
                        policy_result = (
                            run_backtest(
                                symbol=symbol,
                                candles=candles,
                                fold_start=(
                                    fold_start
                                ),
                                fold_end=fold_end,
                                starting_balance=(
                                    policy_start
                                ),
                                strategy_name=(
                                    strategy_name
                                ),
                            )
                        )
                    finally:
                        STRATEGIES.pop(
                            strategy_name,
                            None,
                        )

                    rejected = counter[
                        "rejected"
                    ]

                policy_return = fold_return(
                    policy_result,
                    policy_start,
                )

                balances[
                    symbol
                ][policy] = (
                    policy_result.final_balance
                )

                market_results[
                    symbol
                ][
                    f"{policy}_trades"
                ] += (
                    policy_result.total_trades
                )

                market_results[
                    symbol
                ][
                    f"{policy}_worst_drawdown"
                ] = max(
                    market_results[
                        symbol
                    ][
                        f"{policy}_worst_drawdown"
                    ],
                    policy_result.max_drawdown_percent,
                )

                line += (
                    f" | {policy[:8]:8s} "
                    f"{policy_return:7.2f}% "
                    f"({policy_result.total_trades:2d}, "
                    f"rej {rejected:2d})"
                )

            print(line)

    for symbol in MARKETS:
        fixed_balance = balances[
            symbol
        ]["fixed"]

        market_results[
            symbol
        ]["fixed_return"] = (
            fixed_balance
            / INITIAL_BALANCE
            - 1
        ) * 100

        for policy in POLICIES:
            policy_balance = balances[
                symbol
            ][policy]

            market_results[
                symbol
            ][
                f"{policy}_return"
            ] = (
                policy_balance
                / INITIAL_BALANCE
                - 1
            ) * 100

    print()
    print("=" * 126)
    print("MARKET SUMMARY")
    print("=" * 126)

    for symbol, result in (
        market_results.items()
    ):
        line = (
            f"{symbol} | "
            f"Fixed "
            f"{result['fixed_return']:7.2f}%"
        )

        for policy in POLICIES:
            line += (
                f" | {policy[:8]:8s} "
                f"{result[f'{policy}_return']:7.2f}%"
            )

        print(line)

    print()
    print("=" * 126)
    print("CANDIDATE SUMMARY")
    print("=" * 126)

    summaries = {}

    for policy in POLICIES:
        summary = result_summary(
            market_results=market_results,
            policy=policy,
        )

        summaries[policy] = summary

        print()
        print(policy.upper())
        print("-" * 80)
        print(
            "Sum of fixed returns:",
            round(
                summary["fixed_sum"],
                2,
            ),
            "%",
        )
        print(
            "Sum of policy returns:",
            round(
                summary["policy_sum"],
                2,
            ),
            "%",
        )
        print(
            "Policy versus fixed:",
            round(
                summary["difference"],
                2,
            ),
            "percentage points",
        )
        print(
            "Markets beating fixed:",
            summary[
                "markets_beating_fixed"
            ],
            "/ 6",
        )
        print(
            "Markets lowering drawdown:",
            summary[
                "markets_lower_drawdown"
            ],
            "/ 6",
        )
        print(
            "Profitable policy markets:",
            summary[
                "profitable_markets"
            ],
            "/ 6",
        )
        print(
            "Trades retained:",
            summary[
                "policy_trades"
            ],
            "/",
            summary[
                "fixed_trades"
            ],
        )

    ranked = sorted(
        summaries.items(),
        key=lambda item: (
            item[1]["difference"],
            item[1][
                "markets_beating_fixed"
            ],
        ),
        reverse=True,
    )

    print()
    print("=" * 126)
    print("RANKING")
    print("=" * 126)

    for position, (
        policy,
        summary,
    ) in enumerate(ranked, start=1):
        print(
            f"{position}. "
            f"{policy} | "
            f"Difference "
            f"{summary['difference']:.2f}pp | "
            f"Beats fixed in "
            f"{summary['markets_beating_fixed']}/6 | "
            f"Profitable markets "
            f"{summary['profitable_markets']}/6"
        )

    print()
    print(
        "STATUS: "
        "NESTED_DEVELOPMENT_ONLY"
    )
    print(
        "The external holdout was not "
        "accessed or reused."
    )
    print(
        "No candidate should be promoted "
        "unless it improves results across "
        "markets without removing an "
        "unreasonable share of trades."
    )


if __name__ == "__main__":
    main()
