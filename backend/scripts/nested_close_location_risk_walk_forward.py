from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


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
from scripts.analyse_atr_breakout_quality import (
    collect_market_records,
    percentile,
)
from scripts.nested_atr_quality_filter_walk_forward import (
    signal_features,
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
CLOSE_LOCATION_PERCENTILE = 1 / 3

MINIMUM_TRAINING_FOLDS = 2
MINIMUM_TRAINING_RECORDS = 150


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


def threshold_available(
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
    records: list[dict],
) -> float:
    if not records:
        raise ValueError(
            "Cannot learn a close-location threshold "
            "without training records."
        )

    values = sorted(
        float(
            record[
                "directional_close_location"
            ]
        )
        for record in records
    )

    return percentile(
        values,
        CLOSE_LOCATION_PERCENTILE,
    )


def create_close_location_risk_adjuster(
    threshold: float | None,
):
    def adjuster(
        config,
        historical_candles,
        direction,
    ) -> float:
        if threshold is None:
            return config.risk_per_trade_percent

        features = signal_features(
            historical_candles,
            direction,
        )

        if features is None:
            return config.risk_per_trade_percent

        close_location = float(
            features[
                "directional_close_location"
            ]
        )

        if close_location > threshold:
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
        "max_total_risk_percent": (
            BASE_RISK_PERCENT
        ),
        "trading_start_timestamp": fold_start,
    }

    if risk_adjuster is not None:
        arguments[
            "risk_percent_adjuster"
        ] = risk_adjuster

    return run_portfolio_backtest(
        **arguments
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


def assert_identical_trade_sequence(
    fixed_result,
    risk_result,
    symbol: str,
    fold_number: int,
) -> None:
    if (
        fixed_result.total_trades
        != risk_result.total_trades
    ):
        raise RuntimeError(
            f"{symbol} fold {fold_number}: "
            "soft risk policy changed trade count."
        )

    fixed_sequence = [
        (
            trade.signal_timestamp,
            trade.entry_timestamp,
            trade.direction,
        )
        for trade in fixed_result.trades
    ]

    risk_sequence = [
        (
            trade.signal_timestamp,
            trade.entry_timestamp,
            trade.direction,
        )
        for trade in risk_result.trades
    ]

    if fixed_sequence != risk_sequence:
        raise RuntimeError(
            f"{symbol} fold {fold_number}: "
            "soft risk policy changed the trade sequence."
        )


def collect_all_records(
    candles_by_market,
) -> list[dict]:
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


def main() -> None:
    print(
        "TRADE IQ NESTED CLOSE-LOCATION "
        "SOFT-RISK WALK-FORWARD"
    )
    print("=" * 124)
    print(
        "The close-location threshold is learned "
        "only from earlier completed development folds."
    )
    print(
        "Weak-close trades are retained but use "
        "half the configured risk."
    )
    print(
        "Trade count, direction and timestamps must "
        "remain identical to fixed risk."
    )
    print(
        "No external holdout data is accessed or reused."
    )

    candles_by_market = {
        symbol: load_candles_from_csv(path)
        for symbol, path in MARKETS.items()
    }

    print()
    print(
        "Collecting fixed-risk development records..."
    )

    fixed_records = collect_all_records(
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

    soft_balances = {
        symbol: INITIAL_BALANCE
        for symbol in MARKETS
    }

    market_results = {
        symbol: {
            "fixed_folds": [],
            "soft_folds": [],
            "fixed_worst_drawdown": 0.0,
            "soft_worst_drawdown": 0.0,
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

        active = threshold_available(
            training_records,
            fold_number,
        )

        threshold = (
            learn_close_location_threshold(
                training_records
            )
            if active
            else None
        )

        risk_adjuster = (
            create_close_location_risk_adjuster(
                threshold
            )
        )

        print()
        print("=" * 124)
        print(
            f"POLICY SNAPSHOT BEFORE FOLD "
            f"{fold_number}"
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

        if threshold is None:
            print(
                "Soft-risk policy active: No"
            )
        else:
            print(
                "Soft-risk policy active: Yes"
            )
            print(
                "Frozen minimum close location:",
                round(threshold, 4),
            )
            print(
                "Normal risk:",
                BASE_RISK_PERCENT,
                "%",
            )
            print(
                "Weak-close risk:",
                BASE_RISK_PERCENT
                * REDUCED_RISK_MULTIPLIER,
                "%",
            )

        fold_start = start_timestamp(
            start_text
        )
        fold_end = end_timestamp(
            end_text
        )

        fixed_fold_sum = 0.0
        soft_fold_sum = 0.0
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
            fixed_start = fixed_balances[
                symbol
            ]

            soft_start = soft_balances[
                symbol
            ]

            fixed_result = run_fold(
                symbol=symbol,
                candles=candles,
                fold_start=fold_start,
                fold_end=fold_end,
                starting_balance=fixed_start,
            )

            soft_result = run_fold(
                symbol=symbol,
                candles=candles,
                fold_start=fold_start,
                fold_end=fold_end,
                starting_balance=soft_start,
                risk_adjuster=risk_adjuster,
            )

            assert_identical_trade_sequence(
                fixed_result=fixed_result,
                risk_result=soft_result,
                symbol=symbol,
                fold_number=fold_number,
            )

            fixed_return = fold_return(
                fixed_result,
                fixed_start,
            )

            soft_return = fold_return(
                soft_result,
                soft_start,
            )

            risk_percentages = (
                estimated_risk_percentages(
                    soft_result,
                    soft_start,
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

            soft_balances[
                symbol
            ] = soft_result.final_balance

            details = market_results[
                symbol
            ]

            details[
                "fixed_folds"
            ].append(fixed_return)

            details[
                "soft_folds"
            ].append(soft_return)

            details[
                "fixed_worst_drawdown"
            ] = max(
                details[
                    "fixed_worst_drawdown"
                ],
                fixed_result.max_drawdown_percent,
            )

            details[
                "soft_worst_drawdown"
            ] = max(
                details[
                    "soft_worst_drawdown"
                ],
                soft_result.max_drawdown_percent,
            )

            details[
                "trades"
            ] += fixed_result.total_trades

            details[
                "reduced_trades"
            ] += reduced_trades

            fixed_fold_sum += fixed_return
            soft_fold_sum += soft_return
            fold_trades += (
                fixed_result.total_trades
            )
            fold_reduced += reduced_trades

            if (
                soft_result.max_drawdown_percent
                < fixed_result.max_drawdown_percent
            ):
                lower_drawdown_markets += 1

            print(
                f"{symbol:7s} | "
                f"Fixed {fixed_return:7.2f}% | "
                f"Soft {soft_return:7.2f}% | "
                f"Difference "
                f"{soft_return - fixed_return:7.2f}pp | "
                f"Trades {fixed_result.total_trades:3d} | "
                f"Reduced {reduced_trades:3d} | "
                f"Fixed DD "
                f"{fixed_result.max_drawdown_percent:5.2f}% | "
                f"Soft DD "
                f"{soft_result.max_drawdown_percent:5.2f}% | "
                f"Soft PF "
                f"{profit_factor(soft_result.trades):6.3f}"
            )

        fold_results.append(
            {
                "fold": fold_number,
                "active": active,
                "threshold": threshold,
                "fixed_sum": fixed_fold_sum,
                "soft_sum": soft_fold_sum,
                "difference": (
                    soft_fold_sum
                    - fixed_fold_sum
                ),
                "trades": fold_trades,
                "reduced": fold_reduced,
                "lower_drawdown_markets": (
                    lower_drawdown_markets
                ),
            }
        )

        print()
        print(
            f"Fold {fold_number} sum | "
            f"Fixed {fixed_fold_sum:.2f}% | "
            f"Soft {soft_fold_sum:.2f}% | "
            f"Difference "
            f"{soft_fold_sum - fixed_fold_sum:.2f}pp | "
            f"Reduced {fold_reduced}/{fold_trades} | "
            f"Lower DD markets "
            f"{lower_drawdown_markets}/6"
        )

    print()
    print("=" * 124)
    print("MARKET SUMMARY")
    print("=" * 124)

    fixed_market_returns = []
    soft_market_returns = []

    total_trades = 0
    total_reduced = 0
    markets_beating_fixed = 0
    markets_lowering_drawdown = 0
    profitable_soft_markets = 0

    for symbol, details in (
        market_results.items()
    ):
        fixed_return = (
            fixed_balances[symbol]
            / INITIAL_BALANCE
            - 1
        ) * 100

        soft_return = (
            soft_balances[symbol]
            / INITIAL_BALANCE
            - 1
        ) * 100

        fixed_market_returns.append(
            fixed_return
        )
        soft_market_returns.append(
            soft_return
        )

        total_trades += details["trades"]
        total_reduced += details[
            "reduced_trades"
        ]

        if soft_return > fixed_return:
            markets_beating_fixed += 1

        if (
            details["soft_worst_drawdown"]
            < details[
                "fixed_worst_drawdown"
            ]
        ):
            markets_lowering_drawdown += 1

        if soft_return > 0:
            profitable_soft_markets += 1

        print(
            f"{symbol:7s} | "
            f"Fixed {fixed_return:7.2f}% | "
            f"Soft {soft_return:7.2f}% | "
            f"Difference "
            f"{soft_return - fixed_return:7.2f}pp | "
            f"Reduced "
            f"{details['reduced_trades']:3d}"
            f"/{details['trades']:3d} | "
            f"Fixed worst DD "
            f"{details['fixed_worst_drawdown']:5.2f}% | "
            f"Soft worst DD "
            f"{details['soft_worst_drawdown']:5.2f}%"
        )

    fixed_sum = sum(
        fixed_market_returns
    )

    soft_sum = sum(
        soft_market_returns
    )

    active_fold_results = [
        result
        for result in fold_results
        if result["active"]
    ]

    active_folds_beating_fixed = sum(
        result["soft_sum"]
        > result["fixed_sum"]
        for result in active_fold_results
    )

    print()
    print("=" * 124)
    print("AGGREGATE SUMMARY")
    print("=" * 124)
    print(
        "Sum of fixed market returns:",
        round(fixed_sum, 2),
        "%",
    )
    print(
        "Sum of soft-risk market returns:",
        round(soft_sum, 2),
        "%",
    )
    print(
        "Soft risk versus fixed:",
        round(
            soft_sum - fixed_sum,
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
        "Profitable soft-risk markets:",
        profitable_soft_markets,
        "/ 6",
    )
    print(
        "Active test folds beating fixed:",
        active_folds_beating_fixed,
        "/",
        len(active_fold_results),
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

    for result in active_fold_results:
        print(
            f"Fold {result['fold']} | "
            f"Threshold "
            f"{result['threshold']:.4f} | "
            f"Fixed {result['fixed_sum']:7.2f}% | "
            f"Soft {result['soft_sum']:7.2f}% | "
            f"Difference "
            f"{result['difference']:7.2f}pp | "
            f"Reduced "
            f"{result['reduced']:3d}"
            f"/{result['trades']:3d} | "
            f"Lower DD markets "
            f"{result['lower_drawdown_markets']}/6"
        )

    print()
    print(
        "STATUS: "
        "NESTED_CLOSE_LOCATION_SOFT_RISK_"
        "DEVELOPMENT_ONLY"
    )
    print(
        "The external holdout was not accessed "
        "or reused."
    )
    print(
        "This experiment changes position size only; "
        "it does not remove or add trades."
    )


if __name__ == "__main__":
    main()
