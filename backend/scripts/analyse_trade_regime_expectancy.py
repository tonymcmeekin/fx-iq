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
STRATEGY_NAME = "atr_breakout"
REGIME_LOOKBACK = 50


def trade_regime(
    candles,
    signal_timestamp,
):
    historical = [
        candle
        for candle in candles
        if candle.timestamp <= signal_timestamp
    ]

    if len(historical) < REGIME_LOOKBACK:
        return None

    return detect_market_regime(
        historical,
        lookback=REGIME_LOOKBACK,
    )


def run_market(
    symbol: str,
    candles,
):
    records = []

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
            max_total_risk_percent=0.5,
            trading_start_timestamp=fold_start,
        )

        for trade in result.trades:
            regime = trade_regime(
                candles=available,
                signal_timestamp=trade.signal_timestamp,
            )

            if regime is None:
                continue

            records.append(
                {
                    "market": symbol,
                    "fold": fold_number,
                    "trend": regime.trend,
                    "volatility": regime.volatility,
                    "confidence_band": (
                        "LOW"
                        if regime.confidence < 0.60
                        else "HIGH"
                    ),
                    "net_pnl": trade.net_pnl,
                    "account_return": (
                        trade.account_return_percent
                    ),
                    "winner": trade.net_pnl > 0,
                }
            )

    return records


def summarise(
    records,
    keys,
):
    groups = defaultdict(list)

    for record in records:
        key = tuple(
            record[field]
            for field in keys
        )
        groups[key].append(record)

    rows = []

    for key, items in groups.items():
        trades = len(items)
        wins = sum(
            item["winner"]
            for item in items
        )

        total_return = sum(
            item["account_return"]
            for item in items
        )

        average_return = (
            total_return / trades
            if trades
            else 0.0
        )

        gross_profit = sum(
            item["net_pnl"]
            for item in items
            if item["net_pnl"] > 0
        )

        gross_loss = abs(
            sum(
                item["net_pnl"]
                for item in items
                if item["net_pnl"] < 0
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

        rows.append(
            {
                "key": key,
                "trades": trades,
                "win_rate": (
                    wins / trades * 100
                    if trades
                    else 0.0
                ),
                "total_return": total_return,
                "average_return": average_return,
                "profit_factor": profit_factor,
            }
        )

    rows.sort(
        key=lambda row: (
            row["average_return"],
            row["trades"],
        ),
        reverse=True,
    )

    return rows


def print_summary(
    title,
    keys,
    records,
):
    print()
    print("=" * 110)
    print(title)
    print("=" * 110)

    rows = summarise(
        records=records,
        keys=keys,
    )

    for row in rows:
        label = " | ".join(
            str(value)
            for value in row["key"]
        )

        pf = row["profit_factor"]

        pf_text = (
            "inf"
            if pf == float("inf")
            else f"{pf:.3f}"
        )

        print(
            f"{label:40s} | "
            f"Trades {row['trades']:3d} | "
            f"Win {row['win_rate']:6.2f}% | "
            f"Avg {row['average_return']:8.4f}% | "
            f"Total {row['total_return']:8.2f}% | "
            f"PF {pf_text:>6s}"
        )


def main():
    print(
        "TRADE IQ DEVELOPMENT TRADE-REGIME EXPECTANCY"
    )
    print("=" * 110)
    print(
        "Fixed ATR breakout trades are classified using "
        "only information available at each signal close."
    )
    print(
        "Only the six development folds ending by "
        "4 August 2024 are included."
    )
    print(
        "No holdout evidence is reused."
    )

    records = []

    for symbol, path in MARKETS.items():
        candles = load_candles_from_csv(path)

        market_records = run_market(
            symbol=symbol,
            candles=candles,
        )

        records.extend(market_records)

        print(
            f"{symbol}: "
            f"{len(market_records)} classified trades"
        )

    print_summary(
        title="TREND REGIME",
        keys=["trend"],
        records=records,
    )

    print_summary(
        title="VOLATILITY REGIME",
        keys=["volatility"],
        records=records,
    )

    print_summary(
        title="TREND × VOLATILITY",
        keys=[
            "trend",
            "volatility",
        ],
        records=records,
    )

    print_summary(
        title="TREND × VOLATILITY × CONFIDENCE",
        keys=[
            "trend",
            "volatility",
            "confidence_band",
        ],
        records=records,
    )

    print_summary(
        title="MARKET × TREND",
        keys=[
            "market",
            "trend",
        ],
        records=records,
    )

    print()
    print("=" * 110)
    print("INTERPRETATION RULE")
    print("=" * 110)
    print(
        "Do not change risk solely because one small group "
        "looks profitable or unprofitable."
    )
    print(
        "A candidate rule should have adequate trades, "
        "consistent results across markets and positive "
        "average expectancy."
    )


if __name__ == "__main__":
    main()
