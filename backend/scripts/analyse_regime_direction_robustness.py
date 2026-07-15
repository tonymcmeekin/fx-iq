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
REGIME_LOOKBACK = 50
MINIMUM_TOTAL_TRADES = 40
MINIMUM_MARKETS = 4


def classify_trade(candles, trade):
    history = [
        candle
        for candle in candles
        if candle.timestamp <= trade.signal_timestamp
    ]

    if len(history) < REGIME_LOOKBACK:
        return None

    regime = detect_market_regime(
        history,
        lookback=REGIME_LOOKBACK,
    )

    return {
        "trend": regime.trend,
        "volatility": regime.volatility,
        "confidence": regime.confidence,
        "direction": trade.direction,
    }


def collect_market_records(symbol, candles):
    records = []

    for fold_number, (
        start_text,
        end_text,
    ) in enumerate(DEVELOPMENT_FOLDS, start=1):
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
            max_total_risk_percent=0.5,
            trading_start_timestamp=fold_start,
        )

        for trade in result.trades:
            classification = classify_trade(
                available,
                trade,
            )

            if classification is None:
                continue

            records.append(
                {
                    "market": symbol,
                    "fold": fold_number,
                    "trend": classification["trend"],
                    "volatility": classification["volatility"],
                    "confidence_band": (
                        "LOW"
                        if classification["confidence"] < 0.60
                        else "HIGH"
                    ),
                    "direction": classification["direction"],
                    "return": trade.account_return_percent,
                    "net_pnl": trade.net_pnl,
                }
            )

    return records


def statistics(records):
    trades = len(records)

    total_return = sum(
        record["return"]
        for record in records
    )

    gross_profit = sum(
        record["net_pnl"]
        for record in records
        if record["net_pnl"] > 0
    )

    gross_loss = abs(
        sum(
            record["net_pnl"]
            for record in records
            if record["net_pnl"] < 0
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
        "total_return": total_return,
        "average_return": (
            total_return / trades
            if trades
            else 0.0
        ),
        "profit_factor": profit_factor,
    }


def group_records(records):
    groups = defaultdict(list)

    for record in records:
        key = (
            record["trend"],
            record["volatility"],
            record["direction"],
        )

        groups[key].append(record)

    return groups


def leave_one_market_out(records):
    results = {}

    for excluded_market in MARKETS:
        retained = [
            record
            for record in records
            if record["market"] != excluded_market
        ]

        results[excluded_market] = statistics(retained)

    return results


def print_group(key, records):
    overall = statistics(records)

    market_groups = defaultdict(list)

    for record in records:
        market_groups[record["market"]].append(record)

    positive_markets = 0
    negative_markets = 0

    for market_records in market_groups.values():
        market_stats = statistics(market_records)

        if market_stats["average_return"] > 0:
            positive_markets += 1
        elif market_stats["average_return"] < 0:
            negative_markets += 1

    exclusions = leave_one_market_out(records)

    exclusion_signs = [
        result["average_return"] > 0
        for result in exclusions.values()
    ]

    all_exclusions_positive = all(exclusion_signs)
    all_exclusions_negative = not any(exclusion_signs)

    if (
        overall["trades"] >= MINIMUM_TOTAL_TRADES
        and len(market_groups) >= MINIMUM_MARKETS
        and all_exclusions_positive
    ):
        classification = "ROBUST POSITIVE"
    elif (
        overall["trades"] >= MINIMUM_TOTAL_TRADES
        and len(market_groups) >= MINIMUM_MARKETS
        and all_exclusions_negative
    ):
        classification = "ROBUST NEGATIVE"
    else:
        classification = "INCONCLUSIVE"

    trend, volatility, direction = key

    pf = overall["profit_factor"]
    pf_text = (
        "inf"
        if pf == float("inf")
        else f"{pf:.3f}"
    )

    print()
    print(
        f"{trend} | {volatility} | {direction}"
    )
    print("-" * 100)
    print(
        f"Trades: {overall['trades']} | "
        f"Markets: {len(market_groups)} | "
        f"Average return: "
        f"{overall['average_return']:.4f}% | "
        f"Total return: "
        f"{overall['total_return']:.2f}% | "
        f"PF: {pf_text}"
    )
    print(
        f"Positive markets: {positive_markets} | "
        f"Negative markets: {negative_markets}"
    )

    print("Leave-one-market-out average returns:")

    for excluded_market, result in exclusions.items():
        print(
            f"  Excluding {excluded_market}: "
            f"{result['average_return']:.4f}% "
            f"across {result['trades']} trades"
        )

    print("Classification:", classification)

    return {
        "key": key,
        "classification": classification,
        "statistics": overall,
    }


def main():
    print(
        "TRADE IQ REGIME × DIRECTION ROBUSTNESS ANALYSIS"
    )
    print("=" * 100)
    print(
        "Only development folds ending by 4 August 2024 "
        "are analysed."
    )
    print(
        "Each regime uses information available at the "
        "signal close."
    )
    print(
        "Leave-one-market-out testing checks whether a result "
        "depends on one currency pair."
    )

    records = []

    for symbol, path in MARKETS.items():
        candles = load_candles_from_csv(path)

        market_records = collect_market_records(
            symbol,
            candles,
        )

        records.extend(market_records)

        print(
            f"{symbol}: "
            f"{len(market_records)} classified trades"
        )

    groups = group_records(records)

    ordered_groups = sorted(
        groups.items(),
        key=lambda item: (
            statistics(item[1])["average_return"],
            statistics(item[1])["trades"],
        ),
        reverse=True,
    )

    results = []

    print()
    print("=" * 100)
    print("GROUP RESULTS")
    print("=" * 100)

    for key, group in ordered_groups:
        results.append(
            print_group(key, group)
        )

    robust_positive = [
        result
        for result in results
        if result["classification"]
        == "ROBUST POSITIVE"
    ]

    robust_negative = [
        result
        for result in results
        if result["classification"]
        == "ROBUST NEGATIVE"
    ]

    print()
    print("=" * 100)
    print("ROBUSTNESS SUMMARY")
    print("=" * 100)

    print("Robust positive groups:")

    if robust_positive:
        for result in robust_positive:
            print(
                "-",
                " | ".join(result["key"]),
                "| Trades:",
                result["statistics"]["trades"],
                "| Average:",
                round(
                    result["statistics"]["average_return"],
                    4,
                ),
                "%",
            )
    else:
        print("- None")

    print()
    print("Robust negative groups:")

    if robust_negative:
        for result in robust_negative:
            print(
                "-",
                " | ".join(result["key"]),
                "| Trades:",
                result["statistics"]["trades"],
                "| Average:",
                round(
                    result["statistics"]["average_return"],
                    4,
                ),
                "%",
            )
    else:
        print("- None")

    print()
    print(
        "Only robust negative groups are potential candidates "
        "for reduced risk."
    )
    print(
        "No group should receive increased risk at this stage."
    )


if __name__ == "__main__":
    main()
