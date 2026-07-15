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
    start_timestamp,
    strategy_config,
)
from scripts.analyse_atr_breakout_quality import (
    calculate_features,
)
from scripts.nested_close_location_risk_walk_forward import (
    learn_close_location_threshold,
    threshold_available,
)
from scripts.nested_selective_regime_risk_walk_forward import (
    REGIME_LOOKBACK,
    discover_robust_negative_groups,
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

CATEGORY_ORDER = [
    "neither",
    "close_only",
    "regime_only",
    "both",
]

CATEGORY_LABELS = {
    "neither": "NEITHER",
    "close_only": "CLOSE ONLY",
    "regime_only": "REGIME ONLY",
    "both": "BOTH",
}


def account_return(record: dict) -> float:
    return float(record["return"])


def net_pnl(record: dict) -> float:
    return float(record["net_pnl"])


def trade_key(record: dict) -> tuple:
    return (
        record["market"],
        record["fold"],
        record["signal_timestamp"],
        record["entry_timestamp"],
        record["direction"],
    )


def collect_enriched_records(
    candles_by_market,
) -> list[dict]:
    records = []

    for symbol, candles in candles_by_market.items():
        market_count = 0

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
                        "atr_breakout",
                        symbol,
                    )
                ],
                initial_balance=INITIAL_BALANCE,
                max_portfolio_leverage=30.0,
                max_total_risk_percent=(
                    BASE_RISK_PERCENT
                ),
                trading_start_timestamp=fold_start,
            )

            for trade in result.trades:
                features = calculate_features(
                    available,
                    trade,
                )

                if features is None:
                    continue

                historical = [
                    candle
                    for candle in available
                    if (
                        candle.timestamp
                        <= trade.signal_timestamp
                    )
                ]

                if len(historical) < REGIME_LOOKBACK:
                    continue

                regime = detect_market_regime(
                    historical,
                    lookback=REGIME_LOOKBACK,
                )

                record = {
                    "market": symbol,
                    "fold": fold_number,
                    "direction": trade.direction,
                    "signal_timestamp": (
                        trade.signal_timestamp
                    ),
                    "entry_timestamp": (
                        trade.entry_timestamp
                    ),
                    "exit_timestamp": (
                        trade.exit_timestamp
                    ),
                    "return": (
                        trade.account_return_percent
                    ),
                    "net_pnl": trade.net_pnl,
                    "winner": trade.net_pnl > 0,
                    "trend": regime.trend,
                    "volatility": regime.volatility,
                }

                record.update(features)

                records.append(record)
                market_count += 1

        print(
            f"{symbol}: {market_count} "
            "enriched fixed-risk trades"
        )

    keys = [
        trade_key(record)
        for record in records
    ]

    if len(keys) != len(set(keys)):
        raise RuntimeError(
            "Duplicate enriched trade keys detected."
        )

    return records


def training_records_before_fold(
    records: list[dict],
    fold_number: int,
) -> list[dict]:
    return [
        record
        for record in records
        if record["fold"] < fold_number
    ]


def test_records_for_fold(
    records: list[dict],
    fold_number: int,
) -> list[dict]:
    return [
        record
        for record in records
        if record["fold"] == fold_number
    ]


def regime_key(
    record: dict,
) -> tuple[str, str, str]:
    return (
        str(record["trend"]),
        str(record["volatility"]),
        str(record["direction"]),
    )


def classify_overlap(
    record: dict,
    close_threshold: float,
    reduced_regime_groups: set[
        tuple[str, str, str]
    ],
) -> str:
    weak_close = (
        float(
            record[
                "directional_close_location"
            ]
        )
        <= close_threshold
    )

    weak_regime = (
        regime_key(record)
        in reduced_regime_groups
    )

    if weak_close and weak_regime:
        return "both"

    if weak_close:
        return "close_only"

    if weak_regime:
        return "regime_only"

    return "neither"


def partition_records(
    records: list[dict],
    close_threshold: float,
    reduced_regime_groups: set[
        tuple[str, str, str]
    ],
) -> dict[str, list[dict]]:
    groups = {
        category: []
        for category in CATEGORY_ORDER
    }

    for record in records:
        category = classify_overlap(
            record=record,
            close_threshold=close_threshold,
            reduced_regime_groups=(
                reduced_regime_groups
            ),
        )

        groups[category].append(record)

    return groups


def statistics(
    records: list[dict],
) -> dict:
    trades = len(records)

    returns = [
        account_return(record)
        for record in records
    ]

    total_return = sum(returns)

    wins = sum(
        value > 0
        for value in returns
    )

    gross_profit = sum(
        net_pnl(record)
        for record in records
        if net_pnl(record) > 0
    )

    gross_loss = abs(
        sum(
            net_pnl(record)
            for record in records
            if net_pnl(record) < 0
        )
    )

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else (
            float("inf")
            if gross_profit > 0
            else 0.0
        )
    )

    represented_markets = {
        record["market"]
        for record in records
    }

    return {
        "trades": trades,
        "win_rate": (
            wins / trades * 100
            if trades
            else 0.0
        ),
        "average_return": (
            total_return / trades
            if trades
            else 0.0
        ),
        "total_return": total_return,
        "profit_factor": profit_factor,
        "markets": len(
            represented_markets
        ),
    }


def pf_text(value: float) -> str:
    if value == float("inf"):
        return "inf"

    return f"{value:.3f}"


def print_statistics(
    category: str,
    records: list[dict],
) -> None:
    result = statistics(records)

    print(
        f"{CATEGORY_LABELS[category]:12s} | "
        f"Trades {result['trades']:3d} | "
        f"Win {result['win_rate']:6.2f}% | "
        f"Avg {result['average_return']:8.4f}% | "
        f"Total {result['total_return']:9.2f}% | "
        f"PF {pf_text(result['profit_factor']):>6s} | "
        f"Markets {result['markets']}"
    )


def print_regime_groups(
    selected_groups: dict,
) -> None:
    if not selected_groups:
        print(
            "Frozen reduced-risk regime groups: None"
        )
        return

    print(
        "Frozen reduced-risk regime groups:"
    )

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


def market_breakdown(
    active_records: list[dict],
) -> None:
    print()
    print("=" * 124)
    print("MARKET BREAKDOWN")
    print("=" * 124)

    for symbol in MARKETS:
        market_records = [
            record
            for record in active_records
            if record["market"] == symbol
        ]

        print()
        print(symbol)
        print("-" * 124)

        for category in CATEGORY_ORDER:
            category_records = [
                record
                for record in market_records
                if (
                    record[
                        "overlap_category"
                    ]
                    == category
                )
            ]

            print_statistics(
                category,
                category_records,
            )


def category_market_robustness(
    active_records: list[dict],
) -> None:
    print()
    print("=" * 124)
    print("CATEGORY MARKET ROBUSTNESS")
    print("=" * 124)

    for category in CATEGORY_ORDER:
        print()
        print(CATEGORY_LABELS[category])
        print("-" * 124)

        negative_markets = 0
        positive_markets = 0
        populated_markets = 0

        for symbol in MARKETS:
            selected = [
                record
                for record in active_records
                if (
                    record["market"] == symbol
                    and record[
                        "overlap_category"
                    ]
                    == category
                )
            ]

            result = statistics(selected)

            if result["trades"] > 0:
                populated_markets += 1

                if result["total_return"] < 0:
                    negative_markets += 1
                elif result["total_return"] > 0:
                    positive_markets += 1

            print(
                f"{symbol:7s} | "
                f"Trades {result['trades']:3d} | "
                f"Avg "
                f"{result['average_return']:8.4f}% | "
                f"Total "
                f"{result['total_return']:9.2f}% | "
                f"PF "
                f"{pf_text(result['profit_factor']):>6s}"
            )

        print(
            "Populated markets:",
            populated_markets,
            "| Negative:",
            negative_markets,
            "| Positive:",
            positive_markets,
        )


def category_fold_robustness(
    fold_groups: dict[
        int,
        dict[str, list[dict]],
    ],
) -> None:
    print()
    print("=" * 124)
    print("CATEGORY FOLD ROBUSTNESS")
    print("=" * 124)

    for category in CATEGORY_ORDER:
        print()
        print(CATEGORY_LABELS[category])
        print("-" * 124)

        negative_folds = 0
        positive_folds = 0
        populated_folds = 0

        for fold_number in sorted(fold_groups):
            records = fold_groups[
                fold_number
            ][category]

            result = statistics(records)

            if result["trades"] > 0:
                populated_folds += 1

                if result["total_return"] < 0:
                    negative_folds += 1
                elif result["total_return"] > 0:
                    positive_folds += 1

            print(
                f"Fold {fold_number} | "
                f"Trades {result['trades']:3d} | "
                f"Avg "
                f"{result['average_return']:8.4f}% | "
                f"Total "
                f"{result['total_return']:9.2f}% | "
                f"PF "
                f"{pf_text(result['profit_factor']):>6s}"
            )

        print(
            "Populated folds:",
            populated_folds,
            "| Negative:",
            negative_folds,
            "| Positive:",
            positive_folds,
        )


def main() -> None:
    print(
        "TRADE IQ MATCHED NESTED RISK-POLICY "
        "OVERLAP AUDIT"
    )
    print("=" * 124)
    print(
        "Original fixed-risk trades are classified "
        "by the nested close-location and nested "
        "regime-risk rules."
    )
    print(
        "The audit does not alter trade selection "
        "or position size."
    )
    print(
        "Thresholds and regime groups are learned "
        "only from earlier completed folds."
    )
    print(
        "No external holdout data is accessed "
        "or reused."
    )
    print()

    candles_by_market = {
        symbol: load_candles_from_csv(path)
        for symbol, path in MARKETS.items()
    }

    records = collect_enriched_records(
        candles_by_market
    )

    print()
    print(
        "Total enriched fixed-risk trades:",
        len(records),
    )

    active_records = []
    fold_groups = {}

    for fold_number, (
        start_text,
        end_text,
    ) in enumerate(
        DEVELOPMENT_FOLDS,
        start=1,
    ):
        training = (
            training_records_before_fold(
                records,
                fold_number,
            )
        )

        testing = test_records_for_fold(
            records,
            fold_number,
        )

        close_active = threshold_available(
            training,
            fold_number,
        )

        close_threshold = (
            learn_close_location_threshold(
                training
            )
            if close_active
            else None
        )

        selected_regime_groups = (
            discover_robust_negative_groups(
                training
            )
        )

        print()
        print("=" * 124)
        print(
            f"FOLD {fold_number}: "
            f"{start_text} to {end_text}"
        )
        print("=" * 124)
        print(
            "Training records:",
            len(training),
        )
        print(
            "Test records:",
            len(testing),
        )

        if close_threshold is None:
            print(
                "Overlap audit inactive: "
                "close-location threshold unavailable."
            )
            continue

        print(
            "Frozen minimum close location:",
            round(
                close_threshold,
                4,
            ),
        )

        print_regime_groups(
            selected_regime_groups
        )

        reduced_regime_keys = set(
            selected_regime_groups
        )

        groups = partition_records(
            records=testing,
            close_threshold=close_threshold,
            reduced_regime_groups=(
                reduced_regime_keys
            ),
        )

        fold_groups[fold_number] = groups

        for category in CATEGORY_ORDER:
            for record in groups[category]:
                copied = dict(record)
                copied[
                    "overlap_category"
                ] = category
                active_records.append(copied)

        print()

        for category in CATEGORY_ORDER:
            print_statistics(
                category,
                groups[category],
            )

        weak_close_count = (
            len(groups["close_only"])
            + len(groups["both"])
        )

        weak_regime_count = (
            len(groups["regime_only"])
            + len(groups["both"])
        )

        union_count = (
            weak_close_count
            + weak_regime_count
            - len(groups["both"])
        )

        overlap_rate = (
            len(groups["both"])
            / union_count
            * 100
            if union_count
            else 0.0
        )

        print()
        print(
            "Weak-close trades:",
            weak_close_count,
        )
        print(
            "Weak-regime trades:",
            weak_regime_count,
        )
        print(
            "Trades triggering either rule:",
            union_count,
        )
        print(
            "Trades triggering both:",
            len(groups["both"]),
        )
        print(
            "Overlap among rule-triggered trades:",
            round(overlap_rate, 2),
            "%",
        )

    print()
    print("=" * 124)
    print("AGGREGATE ACTIVE-FOLD RESULTS")
    print("=" * 124)

    for category in CATEGORY_ORDER:
        selected = [
            record
            for record in active_records
            if (
                record[
                    "overlap_category"
                ]
                == category
            )
        ]

        print_statistics(
            category,
            selected,
        )

    total_active = len(active_records)

    close_count = sum(
        record["overlap_category"]
        in {
            "close_only",
            "both",
        }
        for record in active_records
    )

    regime_count = sum(
        record["overlap_category"]
        in {
            "regime_only",
            "both",
        }
        for record in active_records
    )

    both_count = sum(
        record["overlap_category"]
        == "both"
        for record in active_records
    )

    union_count = sum(
        record["overlap_category"]
        != "neither"
        for record in active_records
    )

    print()
    print(
        "Active-fold trades classified:",
        total_active,
    )
    print(
        "Weak-close triggers:",
        close_count,
    )
    print(
        "Weak-regime triggers:",
        regime_count,
    )
    print(
        "Either-rule triggers:",
        union_count,
    )
    print(
        "Both-rule triggers:",
        both_count,
    )
    print(
        "Both as percentage of either-rule triggers:",
        round(
            both_count / union_count * 100,
            2,
        )
        if union_count
        else 0.0,
        "%",
    )

    category_market_robustness(
        active_records
    )

    category_fold_robustness(
        fold_groups
    )

    print()
    print("=" * 124)
    print("INTERPRETATION")
    print("=" * 124)
    print(
        "A combined policy is not justified merely "
        "because BOTH has a negative aggregate return."
    )
    print(
        "The BOTH group should also remain negative "
        "across multiple folds and markets and should "
        "be materially worse than the single-rule groups."
    )
    print(
        "If the single-rule and BOTH groups are unstable, "
        "the policies should remain separate research "
        "diagnostics."
    )
    print()
    print(
        "STATUS: "
        "MATCHED_NESTED_POLICY_OVERLAP_AUDIT_ONLY"
    )
    print(
        "The external holdout was not accessed "
        "or reused."
    )


if __name__ == "__main__":
    main()
