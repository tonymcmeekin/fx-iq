from datetime import UTC, datetime, time
from pathlib import Path

from app.market_data.csv_loader import load_candles_from_csv
from app.portfolio.engine import run_portfolio_backtest
from app.portfolio.models import PortfolioStrategyConfig


INITIAL_BALANCE = 10_000.0

MARKETS = {
    "EUR_USD": Path("data/oanda_eur_usd_daily.csv"),
    "GBP_USD": Path("data/oanda_gbp_usd_daily.csv"),
    "AUD_USD": Path("data/oanda_aud_usd_daily.csv"),
}

STRATEGIES = [
    "atr_breakout",
    "atr_regime_filtered",
]

FOLDS = [
    ("2013-01-28", "2014-12-16"),
    ("2014-12-17", "2016-11-20"),
    ("2016-11-21", "2018-10-23"),
    ("2018-10-24", "2020-09-27"),
    ("2020-09-28", "2022-08-30"),
    ("2022-08-31", "2024-08-04"),
    ("2024-08-05", "2026-07-09"),
]


def start_timestamp(date_text: str) -> datetime:
    return datetime.combine(
        datetime.fromisoformat(date_text).date(),
        time.min,
        tzinfo=UTC,
    )


def end_timestamp(date_text: str) -> datetime:
    return datetime.combine(
        datetime.fromisoformat(date_text).date(),
        time.max,
        tzinfo=UTC,
    )


def profit_factor(trades) -> float:
    gross_profit = sum(
        trade.net_pnl
        for trade in trades
        if trade.net_pnl > 0
    )

    gross_loss = abs(
        sum(
            trade.net_pnl
            for trade in trades
            if trade.net_pnl < 0
        )
    )

    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0

    return gross_profit / gross_loss


def run_market_strategy(
    symbol: str,
    candles,
    strategy_name: str,
) -> dict:
    sequential_balance = INITIAL_BALANCE
    fold_results = []

    for fold_number, (start_text, end_text) in enumerate(
        FOLDS,
        start=1,
    ):
        fold_start = start_timestamp(start_text)
        fold_end = end_timestamp(end_text)

        available_candles = [
            candle
            for candle in candles
            if candle.timestamp <= fold_end
        ]

        result = run_portfolio_backtest(
            candles_by_symbol={
                symbol: available_candles,
            },
            strategy_configs=[
                PortfolioStrategyConfig(
                    strategy_name=strategy_name,
                    symbol=symbol,
                    stop_loss_percent=1.5,
                    take_profit_percent=3.0,
                    risk_per_trade_percent=0.5,
                    spread_pips=1.0,
                    slippage_pips=0.5,
                )
            ],
            initial_balance=sequential_balance,
            max_portfolio_leverage=30.0,
            max_total_risk_percent=0.5,
            trading_start_timestamp=fold_start,
        )

        fold_return = (
            result.final_balance
            / sequential_balance
            - 1
        ) * 100

        pf = profit_factor(result.trades)

        passed = (
            fold_return > 0
            and pf >= 1.1
            and result.total_trades >= 8
            and result.max_drawdown_percent <= 10
        )

        fold_results.append(
            {
                "fold": fold_number,
                "start": start_text,
                "end": end_text,
                "trades": result.total_trades,
                "return": fold_return,
                "profit_factor": pf,
                "drawdown": result.max_drawdown_percent,
                "passed": passed,
                "ending_balance": result.final_balance,
            }
        )

        sequential_balance = result.final_balance

    sequential_return = (
        sequential_balance / INITIAL_BALANCE - 1
    ) * 100

    return {
        "symbol": symbol,
        "strategy": strategy_name,
        "folds": fold_results,
        "profitable_folds": sum(
            fold["return"] > 0
            for fold in fold_results
        ),
        "passing_folds": sum(
            fold["passed"]
            for fold in fold_results
        ),
        "total_trades": sum(
            fold["trades"]
            for fold in fold_results
        ),
        "sequential_return": sequential_return,
        "final_balance": sequential_balance,
        "worst_drawdown": max(
            fold["drawdown"]
            for fold in fold_results
        ),
    }


def print_strategy_result(result: dict) -> None:
    print()
    print(result["strategy"].upper())
    print("=" * 102)

    for fold in result["folds"]:
        status = "PASSED" if fold["passed"] else "FAILED"

        print(
            f"Fold {fold['fold']}: "
            f"{fold['start']} to {fold['end']} | "
            f"Trades {fold['trades']:3d} | "
            f"Return {fold['return']:7.2f}% | "
            f"PF {fold['profit_factor']:6.3f} | "
            f"DD {fold['drawdown']:5.2f}% | "
            f"{status}"
        )

    print("-" * 102)
    print(
        "Profitable folds:",
        f"{result['profitable_folds']}/7",
    )
    print(
        "Passing folds:",
        f"{result['passing_folds']}/7",
    )
    print("Total trades:", result["total_trades"])
    print(
        "Sequential return:",
        round(result["sequential_return"], 2),
        "%",
    )
    print(
        "Final balance: £",
        round(result["final_balance"], 2),
    )
    print(
        "Worst drawdown:",
        round(result["worst_drawdown"], 2),
        "%",
    )


def main() -> None:
    print(
        "ATR BREAKOUT VS REGIME-FILTERED ATR "
        "WALK-FORWARD COMPARISON"
    )
    print("=" * 102)
    print(
        "Fixed settings: SL 1.5% | TP 3.0% | "
        "Risk 0.5% | Spread 1 pip | Slippage 0.5 pip"
    )
    print(
        "Each fold trades only after its stated start date, "
        "while retaining earlier candles as regime warm-up."
    )

    all_results = []

    for symbol, path in MARKETS.items():
        candles = load_candles_from_csv(path)

        print()
        print("#" * 102)
        print(symbol)
        print("#" * 102)

        market_results = {}

        for strategy_name in STRATEGIES:
            result = run_market_strategy(
                symbol=symbol,
                candles=candles,
                strategy_name=strategy_name,
            )

            all_results.append(result)
            market_results[strategy_name] = result
            print_strategy_result(result)

        baseline = market_results["atr_breakout"]
        filtered = market_results["atr_regime_filtered"]

        print()
        print("MARKET IMPROVEMENT")
        print("-" * 102)
        print(
            "Return improvement:",
            round(
                filtered["sequential_return"]
                - baseline["sequential_return"],
                2,
            ),
            "percentage points",
        )
        print(
            "Drawdown improvement:",
            round(
                baseline["worst_drawdown"]
                - filtered["worst_drawdown"],
                2,
            ),
            "percentage points",
        )
        print(
            "Additional passing folds:",
            filtered["passing_folds"]
            - baseline["passing_folds"],
        )
        print(
            "Trades removed:",
            baseline["total_trades"]
            - filtered["total_trades"],
        )

    print()
    print("=" * 102)
    print("THREE-MARKET COMPARISON SUMMARY")
    print("=" * 102)

    for result in all_results:
        print(
            f"{result['symbol']:7s} | "
            f"{result['strategy']:20s} | "
            f"Profitable {result['profitable_folds']}/7 | "
            f"Passing {result['passing_folds']}/7 | "
            f"Trades {result['total_trades']:3d} | "
            f"Return {result['sequential_return']:7.2f}% | "
            f"DD {result['worst_drawdown']:5.2f}%"
        )

    baseline_results = [
        result
        for result in all_results
        if result["strategy"] == "atr_breakout"
    ]

    filtered_results = [
        result
        for result in all_results
        if result["strategy"] == "atr_regime_filtered"
    ]

    improved_return_markets = sum(
        filtered["sequential_return"]
        > baseline["sequential_return"]
        for baseline, filtered in zip(
            baseline_results,
            filtered_results,
            strict=True,
        )
    )

    reduced_drawdown_markets = sum(
        filtered["worst_drawdown"]
        < baseline["worst_drawdown"]
        for baseline, filtered in zip(
            baseline_results,
            filtered_results,
            strict=True,
        )
    )

    improved_passing_fold_markets = sum(
        filtered["passing_folds"]
        > baseline["passing_folds"]
        for baseline, filtered in zip(
            baseline_results,
            filtered_results,
            strict=True,
        )
    )

    filtered_profitable_markets = sum(
        result["sequential_return"] > 0
        for result in filtered_results
    )

    filtered_total_trades = sum(
        result["total_trades"]
        for result in filtered_results
    )

    promising = (
        improved_return_markets >= 2
        and reduced_drawdown_markets >= 2
        and filtered_profitable_markets >= 2
        and filtered_total_trades >= 200
    )

    print()
    print(
        "Markets with improved return:",
        improved_return_markets,
        "/ 3",
    )
    print(
        "Markets with reduced drawdown:",
        reduced_drawdown_markets,
        "/ 3",
    )
    print(
        "Markets with more passing folds:",
        improved_passing_fold_markets,
        "/ 3",
    )
    print(
        "Filtered strategy profitable markets:",
        filtered_profitable_markets,
        "/ 3",
    )
    print(
        "Filtered strategy total trades:",
        filtered_total_trades,
    )

    print()
    print(
        "OVERALL RESULT:",
        (
            "REGIME FILTER SHOWS REPEATABLE IMPROVEMENT"
            if promising
            else
            "REGIME FILTER IMPROVEMENT NOT YET REPEATABLE"
        ),
    )


if __name__ == "__main__":
    main()
