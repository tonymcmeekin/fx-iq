from collections import defaultdict
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.indicators.volatility import average_true_range
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

BREAKOUT_PERIOD = 20
ATR_PERIOD = 14
ATR_MULTIPLIER = 0.25

FEATURES = [
    (
        "breakout_excess_atr",
        "Breakout distance beyond threshold / ATR",
    ),
    (
        "body_atr",
        "Signal-candle body / ATR",
    ),
    (
        "directional_close_location",
        "Directional closing position within candle",
    ),
    (
        "channel_width_atr",
        "Previous 20-candle channel width / ATR",
    ),
    (
        "momentum_5_atr",
        "Five-candle directional momentum / ATR",
    ),
    (
        "momentum_20_atr",
        "Twenty-candle directional momentum / ATR",
    ),
    (
        "directional_gap_atr",
        "Directional opening gap / ATR",
    ),
]

BIN_ORDER = {
    "LOW": 0,
    "MID": 1,
    "HIGH": 2,
}


def calculate_features(candles, trade):
    history = [
        candle
        for candle in candles
        if candle.timestamp <= trade.signal_timestamp
    ]

    minimum_required = max(
        BREAKOUT_PERIOD + 1,
        ATR_PERIOD + 1,
        21,
    )

    if len(history) < minimum_required:
        return None

    current = history[-1]
    previous = history[-2]

    previous_channel = history[
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
        history,
        period=ATR_PERIOD,
    )

    if atr <= 0:
        return None

    upper_threshold = (
        previous_high
        + ATR_MULTIPLIER * atr
    )

    lower_threshold = (
        previous_low
        - ATR_MULTIPLIER * atr
    )

    candle_range = current.high - current.low

    if trade.direction == "BUY":
        breakout_excess = (
            current.close - upper_threshold
        ) / atr

        close_location = (
            (current.close - current.low)
            / candle_range
            if candle_range > 0
            else 0.5
        )

        momentum_5 = (
            current.close - history[-6].close
        ) / atr

        momentum_20 = (
            current.close - history[-21].close
        ) / atr

        directional_gap = (
            current.open - previous.close
        ) / atr

    elif trade.direction == "SELL":
        breakout_excess = (
            lower_threshold - current.close
        ) / atr

        close_location = (
            (current.high - current.close)
            / candle_range
            if candle_range > 0
            else 0.5
        )

        momentum_5 = (
            history[-6].close - current.close
        ) / atr

        momentum_20 = (
            history[-21].close - current.close
        ) / atr

        directional_gap = (
            previous.close - current.open
        ) / atr

    else:
        return None

    return {
        "breakout_excess_atr": breakout_excess,
        "body_atr": (
            abs(current.close - current.open)
            / atr
        ),
        "directional_close_location": close_location,
        "channel_width_atr": (
            previous_high - previous_low
        ) / atr,
        "momentum_5_atr": momentum_5,
        "momentum_20_atr": momentum_20,
        "directional_gap_atr": directional_gap,
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
            features = calculate_features(
                available,
                trade,
            )

            if features is None:
                continue

            record = {
                "market": symbol,
                "fold": fold_number,
                "direction": trade.direction,
                "return": (
                    trade.account_return_percent
                ),
                "net_pnl": trade.net_pnl,
                "winner": trade.net_pnl > 0,
            }

            record.update(features)
            records.append(record)

    return records


def percentile(sorted_values, fraction):
    if not sorted_values:
        return 0.0

    position = (
        len(sorted_values) - 1
    ) * fraction

    lower_index = int(position)
    upper_index = min(
        lower_index + 1,
        len(sorted_values) - 1,
    )

    weight = position - lower_index

    return (
        sorted_values[lower_index]
        * (1 - weight)
        + sorted_values[upper_index]
        * weight
    )


def feature_thresholds(records, feature):
    values = sorted(
        record[feature]
        for record in records
    )

    return (
        percentile(values, 1 / 3),
        percentile(values, 2 / 3),
    )


def assign_bin(value, lower, upper):
    if value <= lower:
        return "LOW"

    if value <= upper:
        return "MID"

    return "HIGH"


def statistics(records):
    trades = len(records)

    total_return = sum(
        record["return"]
        for record in records
    )

    winners = sum(
        record["winner"]
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

    if gross_loss > 0:
        profit_factor = (
            gross_profit / gross_loss
        )
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    return {
        "trades": trades,
        "win_rate": (
            winners / trades * 100
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


def market_consistency(records):
    grouped = defaultdict(list)

    for record in records:
        grouped[record["market"]].append(
            record
        )

    positive = 0
    negative = 0

    for items in grouped.values():
        average = statistics(
            items
        )["average_return"]

        if average > 0:
            positive += 1
        elif average < 0:
            negative += 1

    return positive, negative


def print_statistics(label, records):
    result = statistics(records)
    positive, negative = market_consistency(
        records
    )

    profit_factor = (
        "inf"
        if result["profit_factor"]
        == float("inf")
        else (
            f"{result['profit_factor']:.3f}"
        )
    )

    print(
        f"{label:8s} | "
        f"Trades {result['trades']:3d} | "
        f"Win {result['win_rate']:6.2f}% | "
        f"Avg {result['average_return']:8.4f}% | "
        f"Total {result['total_return']:8.2f}% | "
        f"PF {profit_factor:>6s} | "
        f"Positive markets {positive} | "
        f"Negative markets {negative}"
    )


def leave_one_market_out_slopes(
    records,
    feature,
    lower,
    upper,
):
    results = {}

    for excluded_market in MARKETS:
        retained = [
            record
            for record in records
            if record["market"]
            != excluded_market
        ]

        low_records = [
            record
            for record in retained
            if assign_bin(
                record[feature],
                lower,
                upper,
            )
            == "LOW"
        ]

        high_records = [
            record
            for record in retained
            if assign_bin(
                record[feature],
                lower,
                upper,
            )
            == "HIGH"
        ]

        low_average = statistics(
            low_records
        )["average_return"]

        high_average = statistics(
            high_records
        )["average_return"]

        results[excluded_market] = (
            high_average - low_average
        )

    return results


def analyse_feature(
    records,
    feature,
    description,
):
    lower, upper = feature_thresholds(
        records,
        feature,
    )

    grouped = defaultdict(list)

    for record in records:
        label = assign_bin(
            record[feature],
            lower,
            upper,
        )

        grouped[label].append(record)

    print()
    print("=" * 118)
    print(description)
    print("=" * 118)
    print(
        "Tercile boundaries:",
        f"{lower:.4f}",
        "and",
        f"{upper:.4f}",
    )

    for label in sorted(
        grouped,
        key=lambda item: BIN_ORDER[item],
    ):
        print_statistics(
            label,
            grouped[label],
        )

    low_average = statistics(
        grouped["LOW"]
    )["average_return"]

    mid_average = statistics(
        grouped["MID"]
    )["average_return"]

    high_average = statistics(
        grouped["HIGH"]
    )["average_return"]

    slope = high_average - low_average

    exclusion_slopes = (
        leave_one_market_out_slopes(
            records=records,
            feature=feature,
            lower=lower,
            upper=upper,
        )
    )

    all_positive = all(
        value > 0
        for value in exclusion_slopes.values()
    )

    all_negative = all(
        value < 0
        for value in exclusion_slopes.values()
    )

    monotonic_positive = (
        low_average
        <= mid_average
        <= high_average
    )

    monotonic_negative = (
        low_average
        >= mid_average
        >= high_average
    )

    if all_positive and monotonic_positive:
        classification = (
            "ROBUST POSITIVE QUALITY RELATIONSHIP"
        )
    elif all_negative and monotonic_negative:
        classification = (
            "ROBUST NEGATIVE QUALITY RELATIONSHIP"
        )
    else:
        classification = "INCONCLUSIVE"

    print()
    print(
        "High-minus-low average return:",
        round(slope, 4),
        "percentage points",
    )

    print(
        "Monotonic low-to-high:",
        (
            "POSITIVE"
            if monotonic_positive
            else (
                "NEGATIVE"
                if monotonic_negative
                else "NO"
            )
        ),
    )

    print(
        "Leave-one-market-out "
        "high-minus-low differences:"
    )

    for market, value in (
        exclusion_slopes.items()
    ):
        print(
            f"  Excluding {market}: "
            f"{value:.4f} percentage points"
        )

    print("Classification:", classification)

    return {
        "feature": feature,
        "description": description,
        "lower_average": low_average,
        "middle_average": mid_average,
        "high_average": high_average,
        "slope": slope,
        "classification": classification,
    }


def analyse_direction(records, direction):
    selected = [
        record
        for record in records
        if record["direction"] == direction
    ]

    print()
    print("=" * 118)
    print(f"{direction} TRADE SUMMARY")
    print("=" * 118)

    print_statistics(
        direction,
        selected,
    )


def main():
    print(
        "TRADE IQ ATR BREAKOUT QUALITY "
        "DIAGNOSTIC"
    )
    print("=" * 118)
    print(
        "Fixed ATR breakout trades are analysed "
        "using features known at the signal close."
    )
    print(
        "Only the six development folds ending "
        "4 August 2024 are included."
    )
    print(
        "No external holdout data is accessed "
        "or reused."
    )

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
            f"{len(market_records)} "
            "classified trades"
        )

    print()
    print(
        "Total classified trades:",
        len(records),
    )

    analyse_direction(records, "BUY")
    analyse_direction(records, "SELL")

    results = []

    for feature, description in FEATURES:
        results.append(
            analyse_feature(
                records=records,
                feature=feature,
                description=description,
            )
        )

    print()
    print("=" * 118)
    print("QUALITY DIAGNOSTIC SUMMARY")
    print("=" * 118)

    ordered = sorted(
        results,
        key=lambda result: abs(
            result["slope"]
        ),
        reverse=True,
    )

    for result in ordered:
        print(
            f"{result['description']:52s} | "
            f"Low {result['lower_average']:8.4f}% | "
            f"Mid {result['middle_average']:8.4f}% | "
            f"High {result['high_average']:8.4f}% | "
            f"High-low {result['slope']:8.4f}pp | "
            f"{result['classification']}"
        )

    robust = [
        result
        for result in results
        if result["classification"]
        != "INCONCLUSIVE"
    ]

    print()
    print("Robust feature relationships:")

    if robust:
        for result in robust:
            print(
                "-",
                result["description"],
                ":",
                result["classification"],
            )
    else:
        print("- None")

    print()
    print(
        "INTERPRETATION: A feature should not "
        "become a filter merely because one "
        "tercile performed well."
    )
    print(
        "The strongest candidates are monotonic "
        "and retain the same high-versus-low "
        "relationship after every market is "
        "excluded."
    )
    print(
        "STATUS: DEVELOPMENT_DIAGNOSTIC_ONLY"
    )


if __name__ == "__main__":
    main()
