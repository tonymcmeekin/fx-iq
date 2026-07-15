from collections import defaultdict
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.market_data.csv_loader import (
    load_candles_from_csv,
)
from scripts.adaptive_regime_policy_walk_forward import (
    FOLDS,
)
from scripts.analyse_atr_breakout_quality import (
    collect_market_records,
    percentile,
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

MINIMUM_TRAINING_FOLDS = 2
MINIMUM_TRAINING_RECORDS = 150

CLOSE_LOCATION_PERCENTILE = 1 / 3


def account_return(record):
    for key in (
        "account_return",
        "return",
        "account_return_percent",
    ):
        if key in record:
            return float(record[key])

    raise KeyError(
        "No account-return field was found "
        f"in record keys: {sorted(record)}"
    )


def net_pnl(record):
    return float(
        record.get(
            "net_pnl",
            account_return(record),
        )
    )


def collect_records():
    records = []

    for symbol, path in MARKETS.items():
        candles = load_candles_from_csv(
            path
        )

        market_records = (
            collect_market_records(
                symbol=symbol,
                candles=candles,
            )
        )

        records.extend(market_records)

        print(
            f"{symbol}: "
            f"{len(market_records)} records"
        )

    return records


def training_records(
    records,
    test_fold,
):
    return [
        record
        for record in records
        if record["fold"] < test_fold
    ]


def test_records(
    records,
    test_fold,
):
    return [
        record
        for record in records
        if record["fold"] == test_fold
    ]


def learn_threshold(records):
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


def statistics(records):
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

    return {
        "trades": trades,
        "wins": wins,
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
    }


def pf_text(value):
    if value == float("inf"):
        return "inf"

    return f"{value:.3f}"


def print_statistics(
    label,
    records,
):
    result = statistics(records)

    print(
        f"{label:12s} | "
        f"Trades {result['trades']:3d} | "
        f"Win {result['win_rate']:6.2f}% | "
        f"Avg {result['average_return']:8.4f}% | "
        f"Total {result['total_return']:8.2f}% | "
        f"PF {pf_text(result['profit_factor']):>6s}"
    )

    return result


def classify(
    records,
    threshold,
):
    accepted = []
    rejected = []

    for record in records:
        close_location = float(
            record[
                "directional_close_location"
            ]
        )

        if close_location > threshold:
            accepted.append(record)
        else:
            rejected.append(record)

    return accepted, rejected


def main():
    print(
        "TRADE IQ MATCHED NESTED "
        "CLOSE-LOCATION REJECTION AUDIT"
    )
    print("=" * 112)
    print(
        "Thresholds are learned only from "
        "earlier completed development folds."
    )
    print(
        "The audit classifies original fixed-risk "
        "trades rather than running a replacement "
        "trade sequence."
    )
    print(
        "No external holdout data is accessed "
        "or reused."
    )
    print()

    records = collect_records()

    print()
    print(
        "Total fixed-risk records:",
        len(records),
    )

    all_tested = []
    all_accepted = []
    all_rejected = []

    fold_results = []

    for fold_number, (
        start_text,
        end_text,
    ) in enumerate(
        DEVELOPMENT_FOLDS,
        start=1,
    ):
        training = training_records(
            records,
            fold_number,
        )

        testing = test_records(
            records,
            fold_number,
        )

        active = (
            fold_number - 1
            >= MINIMUM_TRAINING_FOLDS
            and len(training)
            >= MINIMUM_TRAINING_RECORDS
        )

        print()
        print("=" * 112)
        print(
            f"FOLD {fold_number}: "
            f"{start_text} to {end_text}"
        )
        print("=" * 112)
        print(
            "Training records:",
            len(training),
        )
        print(
            "Test records:",
            len(testing),
        )

        if not active:
            print(
                "Filter inactive: insufficient "
                "earlier-fold evidence."
            )
            continue

        threshold = learn_threshold(
            training
        )

        accepted, rejected = classify(
            testing,
            threshold,
        )

        print(
            "Frozen minimum close location:",
            round(threshold, 4),
        )
        print()

        tested_stats = print_statistics(
            "ALL",
            testing,
        )

        accepted_stats = print_statistics(
            "ACCEPTED",
            accepted,
        )

        rejected_stats = print_statistics(
            "REJECTED",
            rejected,
        )

        print()
        print(
            "Rejected-trade contribution:",
            round(
                rejected_stats[
                    "total_return"
                ],
                2,
            ),
            "%",
        )
        print(
            "Accepted minus all average return:",
            round(
                accepted_stats[
                    "average_return"
                ]
                - tested_stats[
                    "average_return"
                ],
                4,
            ),
            "percentage points",
        )

        all_tested.extend(testing)
        all_accepted.extend(accepted)
        all_rejected.extend(rejected)

        fold_results.append(
            {
                "fold": fold_number,
                "threshold": threshold,
                "tested": tested_stats,
                "accepted": accepted_stats,
                "rejected": rejected_stats,
            }
        )

    print()
    print("=" * 112)
    print(
        "AGGREGATE MATCHED TEST RESULTS"
    )
    print("=" * 112)

    overall_stats = print_statistics(
        "ALL",
        all_tested,
    )

    accepted_stats = print_statistics(
        "ACCEPTED",
        all_accepted,
    )

    rejected_stats = print_statistics(
        "REJECTED",
        all_rejected,
    )

    print()
    print(
        "Tested folds:",
        ", ".join(
            str(result["fold"])
            for result in fold_results
        ),
    )
    print(
        "Original trades tested:",
        len(all_tested),
    )
    print(
        "Original trades accepted:",
        len(all_accepted),
    )
    print(
        "Original trades rejected:",
        len(all_rejected),
    )
    print(
        "Rejected percentage:",
        round(
            len(all_rejected)
            / len(all_tested)
            * 100,
            2,
        )
        if all_tested
        else 0.0,
        "%",
    )
    print(
        "Rejected trades total return:",
        round(
            rejected_stats[
                "total_return"
            ],
            2,
        ),
        "%",
    )
    print(
        "Accepted trades total return:",
        round(
            accepted_stats[
                "total_return"
            ],
            2,
        ),
        "%",
    )
    print(
        "Accepted minus all average return:",
        round(
            accepted_stats[
                "average_return"
            ]
            - overall_stats[
                "average_return"
            ],
            4,
        ),
        "percentage points",
    )

    print()
    print("=" * 112)
    print("MARKET ROBUSTNESS")
    print("=" * 112)

    market_results = {}

    for market in MARKETS:
        market_tested = [
            record
            for record in all_tested
            if record["market"] == market
        ]

        market_accepted = [
            record
            for record in all_accepted
            if record["market"] == market
        ]

        market_rejected = [
            record
            for record in all_rejected
            if record["market"] == market
        ]

        tested = statistics(
            market_tested
        )

        accepted = statistics(
            market_accepted
        )

        rejected = statistics(
            market_rejected
        )

        improvement = (
            accepted["average_return"]
            - tested["average_return"]
        )

        market_results[market] = {
            "improvement": improvement,
            "rejected_total": (
                rejected["total_return"]
            ),
            "rejected_trades": (
                rejected["trades"]
            ),
        }

        print(
            f"{market:7s} | "
            f"All avg "
            f"{tested['average_return']:8.4f}% | "
            f"Accepted avg "
            f"{accepted['average_return']:8.4f}% | "
            f"Improvement "
            f"{improvement:8.4f}pp | "
            f"Rejected "
            f"{rejected['trades']:3d} | "
            f"Rejected total "
            f"{rejected['total_return']:8.2f}%"
        )

    improving_markets = sum(
        result["improvement"] > 0
        for result in market_results.values()
    )

    harmful_rejection_groups = sum(
        result["rejected_total"] < 0
        for result in market_results.values()
    )

    print()
    print(
        "Markets where accepted-trade "
        "average exceeds all-trade average:",
        improving_markets,
        "/ 6",
    )
    print(
        "Markets where rejected trades "
        "had negative total return:",
        harmful_rejection_groups,
        "/ 6",
    )

    print()
    print("=" * 112)
    print("FOLD ROBUSTNESS")
    print("=" * 112)

    for result in fold_results:
        rejected = result["rejected"]
        accepted = result["accepted"]
        tested = result["tested"]

        print(
            f"Fold {result['fold']} | "
            f"Threshold "
            f"{result['threshold']:.4f} | "
            f"Rejected "
            f"{rejected['trades']:3d} | "
            f"Rejected total "
            f"{rejected['total_return']:8.2f}% | "
            f"Accepted improvement "
            f"{accepted['average_return'] - tested['average_return']:8.4f}pp"
        )

    successful_folds = sum(
        result["rejected"][
            "total_return"
        ] < 0
        for result in fold_results
    )

    print()
    print(
        "Folds where rejected trades "
        "had negative total return:",
        successful_folds,
        "/",
        len(fold_results),
    )

    print()
    print(
        "STATUS: MATCHED_NESTED_"
        "DEVELOPMENT_AUDIT_ONLY"
    )
    print(
        "The external holdout was not "
        "accessed or reused."
    )


if __name__ == "__main__":
    main()
