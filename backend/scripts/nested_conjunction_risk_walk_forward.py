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
from scripts.nested_close_location_risk_walk_forward import (
    signal_features,
)
from scripts.nested_selective_regime_risk_walk_forward import (
    discover_robust_negative_groups,
)


MARKETS = {
    "EUR_USD": Path(
        "data/oanda_eur_usd_daily.csv"
    ),
    "GBP_USD": Path(
        "data/oanda_gbp_usd_daily.csv"
    ),
    "AUD_USD": Path(
        "data/oanda_aud_usd_daily.csv"
    ),
    "USD_JPY": Path(
        "data/oanda_usd_jpy_daily.csv"
    ),
    "USD_CAD": Path(
        "data/oanda_usd_cad_daily.csv"
    ),
    "NZD_USD": Path(
        "data/oanda_nzd_usd_daily.csv"
    ),
}

DEVELOPMENT_FOLDS = FOLDS[:6]

STRATEGY_NAME = "atr_breakout"

BASE_RISK_PERCENT = 0.5
REDUCED_RISK_MULTIPLIER = 0.5

REGIME_LOOKBACK = 50

CLOSE_LOCATION_PERCENTILE = 1 / 3

MINIMUM_TRAINING_FOLDS = 2
MINIMUM_TRAINING_RECORDS = 150


def percentile(
    sorted_values: list[float],
    fraction: float,
) -> float:
    if not sorted_values:
        raise ValueError(
            "Cannot calculate a percentile "
            "without values."
        )

    if fraction < 0 or fraction > 1:
        raise ValueError(
            "Percentile fraction must be "
            "between zero and one."
        )

    position = (
        len(sorted_values) - 1
    ) * fraction

    lower_index = int(position)

    upper_index = min(
        lower_index + 1,
        len(sorted_values) - 1,
    )

    interpolation = (
        position - lower_index
    )

    lower_value = sorted_values[
        lower_index
    ]

    upper_value = sorted_values[
        upper_index
    ]

    return (
        lower_value
        + (
            upper_value - lower_value
        )
        * interpolation
    )


def fold_return(
    result,
    starting_balance: float,
) -> float:
    return (
        result.final_balance
        / starting_balance
        - 1
    ) * 100


def training_records_before_fold(
    records: list[dict],
    fold_number: int,
) -> list[dict]:
    return [
        record
        for record in records
        if record["fold"] < fold_number
    ]


def policy_available(
    training_records: list[dict],
    fold_number: int,
) -> bool:
    return (
        fold_number - 1
        >= MINIMUM_TRAINING_FOLDS
        and len(training_records)
        >= MINIMUM_TRAINING_RECORDS
    )


def learn_close_location_threshold(
    training_records: list[dict],
) -> float:
    if not training_records:
        raise ValueError(
            "Cannot learn a close-location "
            "threshold without training records."
        )

    values = sorted(
        float(
            record[
                "directional_close_location"
            ]
        )
        for record in training_records
    )

    return percentile(
        values,
        CLOSE_LOCATION_PERCENTILE,
    )


def enrich_trade(
    *,
    symbol: str,
    fold_number: int,
    candles,
    trade,
) -> dict | None:
    historical = [
        candle
        for candle in candles
        if candle.timestamp
        <= trade.signal_timestamp
    ]

    features = signal_features(
        historical,
        trade.direction,
    )

    if features is None:
        return None

    if len(historical) < REGIME_LOOKBACK:
        return None

    try:
        regime = detect_market_regime(
            historical,
            lookback=REGIME_LOOKBACK,
        )
    except ValueError:
        return None

    return {
        "market": symbol,
        "fold": fold_number,
        "signal_timestamp": (
            trade.signal_timestamp
        ),
        "entry_timestamp": (
            trade.entry_timestamp
        ),
        "direction": trade.direction,
        "trend": regime.trend,
        "volatility": regime.volatility,
        "directional_close_location": (
            features[
                "directional_close_location"
            ]
        ),
        "return": (
            trade.account_return_percent
        ),
        "net_pnl": trade.net_pnl,
        "winner": trade.net_pnl > 0,
    }


def collect_enriched_records(
    candles_by_market,
) -> list[dict]:
    records = []

    for symbol, candles in (
        candles_by_market.items()
    ):
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
                initial_balance=(
                    INITIAL_BALANCE
                ),
                max_portfolio_leverage=30.0,
                max_total_risk_percent=(
                    BASE_RISK_PERCENT
                ),
                trading_start_timestamp=(
                    fold_start
                ),
            )

            for trade in result.trades:
                record = enrich_trade(
                    symbol=symbol,
                    fold_number=fold_number,
                    candles=available,
                    trade=trade,
                )

                if record is not None:
                    records.append(record)

    return records


def create_conjunction_adjuster(
    *,
    close_location_threshold:
        float | None,
    reduced_regime_groups:
        set[tuple[str, str, str]],
):
    def adjuster(
        config,
        historical_candles,
        direction,
    ) -> float:
        if close_location_threshold is None:
            return (
                config.risk_per_trade_percent
            )

        if not reduced_regime_groups:
            return (
                config.risk_per_trade_percent
            )

        features = signal_features(
            historical_candles,
            direction,
        )

        if features is None:
            return (
                config.risk_per_trade_percent
            )

        if (
            len(historical_candles)
            < REGIME_LOOKBACK
        ):
            return (
                config.risk_per_trade_percent
            )

        try:
            regime = detect_market_regime(
                historical_candles,
                lookback=REGIME_LOOKBACK,
            )
        except ValueError:
            return (
                config.risk_per_trade_percent
            )

        close_location = float(
            features[
                "directional_close_location"
            ]
        )

        regime_key = (
            regime.trend,
            regime.volatility,
            direction,
        )

        weak_close = (
            close_location
            <= close_location_threshold
        )

        weak_regime = (
            regime_key
            in reduced_regime_groups
        )

        if not (
            weak_close
            and weak_regime
        ):
            return (
                config.risk_per_trade_percent
            )

        return (
            config.risk_per_trade_percent
            * REDUCED_RISK_MULTIPLIER
        )

    return adjuster


def run_fold(
    *,
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
        "initial_balance": (
            starting_balance
        ),
        "max_portfolio_leverage": 30.0,
        "max_total_risk_percent": (
            BASE_RISK_PERCENT
        ),
        "trading_start_timestamp": (
            fold_start
        ),
    }

    if risk_adjuster is not None:
        arguments[
            "risk_percent_adjuster"
        ] = risk_adjuster

    return run_portfolio_backtest(
        **arguments
    )


def assert_identical_trade_sequence(
    *,
    fixed_result,
    conjunction_result,
    symbol: str,
    fold_number: int,
) -> None:
    if (
        fixed_result.total_trades
        != conjunction_result.total_trades
    ):
        raise RuntimeError(
            f"{symbol} fold {fold_number}: "
            "conjunction policy changed "
            "trade count."
        )

    fixed_sequence = [
        (
            trade.signal_timestamp,
            trade.entry_timestamp,
            trade.direction,
        )
        for trade in fixed_result.trades
    ]

    conjunction_sequence = [
        (
            trade.signal_timestamp,
            trade.entry_timestamp,
            trade.direction,
        )
        for trade
        in conjunction_result.trades
    ]

    if (
        fixed_sequence
        != conjunction_sequence
    ):
        raise RuntimeError(
            f"{symbol} fold {fold_number}: "
            "conjunction policy changed "
            "the trade sequence."
        )


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


def result_status(
    *,
    markets_beating_fixed: int,
    active_folds_beating_fixed: int,
    aggregate_improvement: float,
    reduced_trades: int,
) -> str:
    candidate = (
        markets_beating_fixed >= 4
        and active_folds_beating_fixed >= 3
        and aggregate_improvement > 0
        and reduced_trades > 0
    )

    if candidate:
        return (
            "PROMISING_NESTED_"
            "CONJUNCTION_CANDIDATE"
        )

    return (
        "NESTED_CONJUNCTION_"
        "DEVELOPMENT_FAILED"
    )


def main() -> None:
    print(
        "TRADE IQ NESTED CONJUNCTION "
        "SOFT-RISK WALK-FORWARD"
    )
    print("=" * 124)
    print(
        "Risk is reduced only when a weak "
        "close location and a learned "
        "robust-negative regime group agree."
    )
    print(
        "Both thresholds and regime groups "
        "are learned only from earlier "
        "completed development folds."
    )
    print(
        "Close-only, regime-only and neither "
        "trades retain configured risk."
    )
    print(
        "Trade count, direction and timestamps "
        "must remain identical to fixed risk."
    )
    print(
        "No external holdout data is "
        "accessed or reused."
    )

    candles_by_market = {
        symbol: load_candles_from_csv(
            path
        )
        for symbol, path in MARKETS.items()
    }

    print()
    print(
        "Collecting enriched fixed-risk "
        "development records..."
    )

    fixed_records = (
        collect_enriched_records(
            candles_by_market
        )
    )

    print(
        "Enriched fixed-risk records:",
        len(fixed_records),
    )

    if len(fixed_records) != 619:
        raise RuntimeError(
            "Expected 619 enriched "
            "development trades."
        )

    fixed_balances = {
        symbol: INITIAL_BALANCE
        for symbol in MARKETS
    }

    conjunction_balances = {
        symbol: INITIAL_BALANCE
        for symbol in MARKETS
    }

    market_results = {
        symbol: {
            "fixed_folds": [],
            "conjunction_folds": [],
            "fixed_worst_drawdown": 0.0,
            "conjunction_worst_drawdown": (
                0.0
            ),
            "trades": 0,
            "reduced_trades": 0,
        }
        for symbol in MARKETS
    }

    fold_results = []

    for fold_number, (
        start_text,
        end_text,
    ) in enumerate(
        DEVELOPMENT_FOLDS,
        start=1,
    ):
        training_records = (
            training_records_before_fold(
                fixed_records,
                fold_number,
            )
        )

        active = policy_available(
            training_records,
            fold_number,
        )

        close_threshold = (
            learn_close_location_threshold(
                training_records
            )
            if active
            else None
        )

        selected_groups = (
            discover_robust_negative_groups(
                training_records
            )
            if active
            else {}
        )

        group_keys = set(
            selected_groups
        )

        adjuster = (
            create_conjunction_adjuster(
                close_location_threshold=(
                    close_threshold
                ),
                reduced_regime_groups=(
                    group_keys
                ),
            )
        )

        print()
        print("=" * 124)
        print(
            f"POLICY SNAPSHOT BEFORE "
            f"FOLD {fold_number}"
        )
        print("=" * 124)
        print(
            "Training records:",
            len(training_records),
        )
        print(
            "Completed training folds:",
            fold_number - 1,
        )

        policy_active = (
            close_threshold is not None
            and bool(group_keys)
        )

        print(
            "Conjunction policy active:",
            "Yes"
            if policy_active
            else "No",
        )

        if close_threshold is not None:
            print(
                "Frozen minimum close location:",
                round(
                    close_threshold,
                    4,
                ),
            )

        if group_keys:
            print(
                "Frozen robust-negative "
                "regime groups:"
            )

            for key in sorted(group_keys):
                details = selected_groups[
                    key
                ]

                print(
                    " -",
                    " | ".join(key),
                    "| Trades:",
                    details["trades"],
                    "| Markets:",
                    details["markets"],
                    "| Average:",
                    round(
                        details[
                            "average_return"
                        ],
                        4,
                    ),
                    "%",
                )
        else:
            print(
                "Frozen robust-negative "
                "regime groups: None"
            )

        fold_start = start_timestamp(
            start_text
        )

        fold_end = end_timestamp(
            end_text
        )

        fixed_fold_sum = 0.0
        conjunction_fold_sum = 0.0
        fold_trades = 0
        fold_reduced = 0
        lower_drawdown_markets = 0

        print()
        print(
            f"FOLD {fold_number}: "
            f"{start_text} to {end_text}"
        )
        print("-" * 124)

        for symbol, candles in (
            candles_by_market.items()
        ):
            fixed_starting_balance = (
                fixed_balances[symbol]
            )

            conjunction_starting_balance = (
                conjunction_balances[
                    symbol
                ]
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

            conjunction_result = run_fold(
                symbol=symbol,
                candles=candles,
                fold_start=fold_start,
                fold_end=fold_end,
                starting_balance=(
                    conjunction_starting_balance
                ),
                risk_adjuster=adjuster,
            )

            assert_identical_trade_sequence(
                fixed_result=fixed_result,
                conjunction_result=(
                    conjunction_result
                ),
                symbol=symbol,
                fold_number=fold_number,
            )

            fixed_return = fold_return(
                fixed_result,
                fixed_starting_balance,
            )

            conjunction_return = fold_return(
                conjunction_result,
                conjunction_starting_balance,
            )

            risk_percentages = (
                estimated_risk_percentages(
                    conjunction_result,
                    conjunction_starting_balance,
                )
            )

            reduced_trades = sum(
                risk_percent
                < BASE_RISK_PERCENT - 0.01
                for risk_percent
                in risk_percentages
            )

            fixed_balances[
                symbol
            ] = fixed_result.final_balance

            conjunction_balances[
                symbol
            ] = (
                conjunction_result.final_balance
            )

            details = market_results[
                symbol
            ]

            details[
                "fixed_folds"
            ].append(
                fixed_return
            )

            details[
                "conjunction_folds"
            ].append(
                conjunction_return
            )

            details[
                "fixed_worst_drawdown"
            ] = max(
                details[
                    "fixed_worst_drawdown"
                ],
                fixed_result.max_drawdown_percent,
            )

            details[
                "conjunction_worst_drawdown"
            ] = max(
                details[
                    "conjunction_worst_drawdown"
                ],
                conjunction_result
                .max_drawdown_percent,
            )

            details[
                "trades"
            ] += fixed_result.total_trades

            details[
                "reduced_trades"
            ] += reduced_trades

            fixed_fold_sum += (
                fixed_return
            )

            conjunction_fold_sum += (
                conjunction_return
            )

            fold_trades += (
                fixed_result.total_trades
            )

            fold_reduced += (
                reduced_trades
            )

            if (
                conjunction_result
                .max_drawdown_percent
                < fixed_result
                .max_drawdown_percent
            ):
                lower_drawdown_markets += 1

            print(
                f"{symbol:7s} | "
                f"Fixed {fixed_return:7.2f}% | "
                f"Both-only "
                f"{conjunction_return:7.2f}% | "
                f"Difference "
                f"{conjunction_return - fixed_return:7.2f}pp | "
                f"Trades "
                f"{fixed_result.total_trades:3d} | "
                f"Reduced "
                f"{reduced_trades:3d} | "
                f"Fixed DD "
                f"{fixed_result.max_drawdown_percent:5.2f}% | "
                f"Both DD "
                f"{conjunction_result.max_drawdown_percent:5.2f}% | "
                f"PF "
                f"{profit_factor(conjunction_result.trades):6.3f}"
            )

        fold_difference = (
            conjunction_fold_sum
            - fixed_fold_sum
        )

        fold_results.append(
            {
                "fold": fold_number,
                "active": policy_active,
                "threshold": close_threshold,
                "groups": group_keys,
                "fixed_return_sum": (
                    fixed_fold_sum
                ),
                "conjunction_return_sum": (
                    conjunction_fold_sum
                ),
                "difference": fold_difference,
                "trades": fold_trades,
                "reduced_trades": (
                    fold_reduced
                ),
                "lower_drawdown_markets": (
                    lower_drawdown_markets
                ),
            }
        )

        print()
        print(
            f"Fold {fold_number} sum | "
            f"Fixed {fixed_fold_sum:.2f}% | "
            f"Both-only "
            f"{conjunction_fold_sum:.2f}% | "
            f"Difference "
            f"{fold_difference:.2f}pp | "
            f"Reduced "
            f"{fold_reduced}/{fold_trades} | "
            f"Lower DD markets "
            f"{lower_drawdown_markets}/6"
        )

    print()
    print("=" * 124)
    print("MARKET SUMMARY")
    print("=" * 124)

    fixed_total = 0.0
    conjunction_total = 0.0
    markets_beating_fixed = 0
    markets_lowering_drawdown = 0
    profitable_markets = 0
    total_trades = 0
    total_reduced = 0

    for symbol, details in (
        market_results.items()
    ):
        fixed_market_return = (
            fixed_balances[symbol]
            / INITIAL_BALANCE
            - 1
        ) * 100

        conjunction_market_return = (
            conjunction_balances[symbol]
            / INITIAL_BALANCE
            - 1
        ) * 100

        difference = (
            conjunction_market_return
            - fixed_market_return
        )

        fixed_total += (
            fixed_market_return
        )

        conjunction_total += (
            conjunction_market_return
        )

        total_trades += (
            details["trades"]
        )

        total_reduced += (
            details["reduced_trades"]
        )

        if difference > 0:
            markets_beating_fixed += 1

        if (
            details[
                "conjunction_worst_drawdown"
            ]
            < details[
                "fixed_worst_drawdown"
            ]
        ):
            markets_lowering_drawdown += 1

        if conjunction_market_return > 0:
            profitable_markets += 1

        print(
            f"{symbol:7s} | "
            f"Fixed "
            f"{fixed_market_return:7.2f}% | "
            f"Both-only "
            f"{conjunction_market_return:7.2f}% | "
            f"Difference "
            f"{difference:7.2f}pp | "
            f"Reduced "
            f"{details['reduced_trades']:3d}/"
            f"{details['trades']:3d} | "
            f"Fixed worst DD "
            f"{details['fixed_worst_drawdown']:5.2f}% | "
            f"Both worst DD "
            f"{details['conjunction_worst_drawdown']:5.2f}%"
        )

    active_folds = [
        fold
        for fold in fold_results
        if fold["active"]
    ]

    active_folds_beating_fixed = sum(
        fold["difference"] > 0
        for fold in active_folds
    )

    aggregate_improvement = (
        conjunction_total
        - fixed_total
    )

    print()
    print("=" * 124)
    print("AGGREGATE SUMMARY")
    print("=" * 124)
    print(
        "Sum of fixed market returns:",
        round(fixed_total, 2),
        "%",
    )
    print(
        "Sum of both-only market returns:",
        round(conjunction_total, 2),
        "%",
    )
    print(
        "Both-only versus fixed:",
        round(
            aggregate_improvement,
            2,
        ),
        "percentage points",
    )
    print(
        "Markets beating fixed:",
        markets_beating_fixed,
        "/ 6",
    )
    print(
        "Markets lowering worst drawdown:",
        markets_lowering_drawdown,
        "/ 6",
    )
    print(
        "Profitable both-only markets:",
        profitable_markets,
        "/ 6",
    )
    print(
        "Active test folds beating fixed:",
        active_folds_beating_fixed,
        "/",
        len(active_folds),
    )
    print(
        "Trades retained:",
        total_trades,
        "/",
        total_trades,
    )
    print(
        "Trades receiving reduced risk:",
        total_reduced,
        "/",
        total_trades,
    )

    print()
    print("=" * 124)
    print("ACTIVE FOLD ROBUSTNESS")
    print("=" * 124)

    for fold in active_folds:
        print(
            f"Fold {fold['fold']} | "
            f"Threshold "
            f"{fold['threshold']:.4f} | "
            f"Groups "
            f"{len(fold['groups'])} | "
            f"Fixed "
            f"{fold['fixed_return_sum']:7.2f}% | "
            f"Both-only "
            f"{fold['conjunction_return_sum']:7.2f}% | "
            f"Difference "
            f"{fold['difference']:7.2f}pp | "
            f"Reduced "
            f"{fold['reduced_trades']:3d}/"
            f"{fold['trades']:3d} | "
            f"Lower DD markets "
            f"{fold['lower_drawdown_markets']}/6"
        )

    status = result_status(
        markets_beating_fixed=(
            markets_beating_fixed
        ),
        active_folds_beating_fixed=(
            active_folds_beating_fixed
        ),
        aggregate_improvement=(
            aggregate_improvement
        ),
        reduced_trades=total_reduced,
    )

    print()
    print(
        "DEVELOPMENT RESULT:",
        (
            "PASSED INTERNAL CANDIDATE "
            "THRESHOLD"
            if status.startswith(
                "PROMISING"
            )
            else "FAILED"
        ),
    )
    print(
        "STATUS:",
        status,
    )
    print(
        "RESEARCH STATUS: "
        "NESTED_DEVELOPMENT_ONLY"
    )
    print(
        "The external holdout was not "
        "accessed or reused."
    )
    print(
        "This experiment changes position "
        "size only; it does not remove "
        "or add trades."
    )


if __name__ == "__main__":
    main()
