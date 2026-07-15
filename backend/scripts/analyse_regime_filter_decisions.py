from collections import defaultdict
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.ai.regime import detect_market_regime
from app.ai.signal_filter import evaluate_signal_for_regime
from app.market_data.csv_loader import load_candles_from_csv
from app.strategies.manager import run_strategy
from app.trading.simulator import simulate_multi_candle_trade


MARKETS = {
    "EUR_USD": Path("data/oanda_eur_usd_daily.csv"),
    "GBP_USD": Path("data/oanda_gbp_usd_daily.csv"),
    "AUD_USD": Path("data/oanda_aud_usd_daily.csv"),
}

REGIME_LOOKBACK = 50
STOP_LOSS_PERCENT = 1.5
TAKE_PROFIT_PERCENT = 3.0
SPREAD_PIPS = 1.0
SLIPPAGE_PIPS = 0.5


def blank_bucket() -> dict:
    return {
        "signals": 0,
        "wins": 0,
        "losses": 0,
        "return_sum": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
    }


def update_bucket(bucket: dict, profit_percent: float) -> None:
    bucket["signals"] += 1
    bucket["return_sum"] += profit_percent

    if profit_percent > 0:
        bucket["wins"] += 1
        bucket["gross_profit"] += profit_percent
    elif profit_percent < 0:
        bucket["losses"] += 1
        bucket["gross_loss"] += abs(profit_percent)


def profit_factor(bucket: dict) -> float:
    if bucket["gross_loss"] == 0:
        return (
            float("inf")
            if bucket["gross_profit"] > 0
            else 0.0
        )

    return bucket["gross_profit"] / bucket["gross_loss"]


def print_bucket(label: str, bucket: dict) -> None:
    count = bucket["signals"]

    win_rate = (
        bucket["wins"] / count * 100
        if count
        else 0.0
    )

    average_return = (
        bucket["return_sum"] / count
        if count
        else 0.0
    )

    print(
        f"{label:48s} | "
        f"Signals {count:3d} | "
        f"Win {win_rate:6.2f}% | "
        f"Avg {average_return:8.4f}% | "
        f"Total {bucket['return_sum']:8.2f}% | "
        f"PF {profit_factor(bucket):6.3f}"
    )


def analyse_market(symbol: str, path: Path) -> None:
    candles = load_candles_from_csv(path)

    buckets = defaultdict(blank_bucket)

    index = REGIME_LOOKBACK - 1

    while index < len(candles) - 1:
        history = candles[: index + 1]

        signal = run_strategy(
            "atr_breakout",
            history,
        )

        if signal.direction == "HOLD":
            index += 1
            continue

        regime = detect_market_regime(
            candles=history,
            lookback=REGIME_LOOKBACK,
        )

        decision = evaluate_signal_for_regime(
            signal=signal,
            regime=regime,
            minimum_confidence=0.6,
        )

        entry_index = index + 1
        trade_candles = candles[entry_index:]

        if len(trade_candles) < 2:
            break

        trade = simulate_multi_candle_trade(
            candles=trade_candles,
            direction=signal.direction,
            stop_loss_percent=STOP_LOSS_PERCENT,
            take_profit_percent=TAKE_PROFIT_PERCENT,
            spread_pips=SPREAD_PIPS,
            slippage_pips=SLIPPAGE_PIPS,
        )

        outcome = (
            "APPROVED"
            if decision.decision == "APPROVED"
            else "REJECTED"
        )

        keys = [
            outcome,
            f"{outcome} | {signal.direction}",
            f"{outcome} | {regime.trend}",
            f"{outcome} | {regime.volatility}",
            (
                f"{outcome} | {signal.direction} | "
                f"{regime.trend}"
            ),
            (
                f"{outcome} | {signal.direction} | "
                f"{regime.volatility}"
            ),
        ]

        for key in keys:
            update_bucket(
                buckets[key],
                trade.profit_percent,
            )

        index = (
            entry_index
            + max(trade.candles_held, 1)
        )

    print()
    print("=" * 112)
    print(symbol)
    print("=" * 112)

    print_bucket("APPROVED — all", buckets["APPROVED"])
    print_bucket("REJECTED — all", buckets["REJECTED"])

    print()
    print("BY DIRECTION")
    print("-" * 112)

    for outcome in ["APPROVED", "REJECTED"]:
        for direction in ["BUY", "SELL"]:
            key = f"{outcome} | {direction}"
            print_bucket(key, buckets[key])

    print()
    print("BY TREND REGIME")
    print("-" * 112)

    for outcome in ["APPROVED", "REJECTED"]:
        for trend in [
            "TRENDING_UP",
            "TRENDING_DOWN",
            "RANGING",
        ]:
            key = f"{outcome} | {trend}"
            print_bucket(key, buckets[key])

    print()
    print("BY VOLATILITY")
    print("-" * 112)

    for outcome in ["APPROVED", "REJECTED"]:
        for volatility in [
            "LOW",
            "NORMAL",
            "HIGH",
        ]:
            key = f"{outcome} | {volatility}"
            print_bucket(key, buckets[key])

    print()
    print("DIRECTION × TREND")
    print("-" * 112)

    for outcome in ["APPROVED", "REJECTED"]:
        for direction in ["BUY", "SELL"]:
            for trend in [
                "TRENDING_UP",
                "TRENDING_DOWN",
                "RANGING",
            ]:
                key = (
                    f"{outcome} | {direction} | {trend}"
                )
                print_bucket(key, buckets[key])


def main() -> None:
    print("ATR REGIME FILTER DECISION DIAGNOSTICS")
    print("=" * 112)
    print(
        "This measures the hypothetical result of both approved "
        "and rejected ATR signals."
    )
    print(
        "Rejected trades are analysed only for diagnosis; "
        "they were not actually taken by the filtered strategy."
    )

    for symbol, path in MARKETS.items():
        analyse_market(symbol, path)


if __name__ == "__main__":
    main()
