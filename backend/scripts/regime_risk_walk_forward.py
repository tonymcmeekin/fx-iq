from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.ai.regime_risk import regime_risk_adjuster
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


def run_fold(
    symbol: str,
    candles,
    fold_start,
    fold_end,
    starting_balance: float,
    use_regime_risk: bool,
):
    available_candles = [
        candle
        for candle in candles
        if candle.timestamp <= fold_end
    ]

    arguments = {
        "candles_by_symbol": {
            symbol: available_candles,
        },
        "strategy_configs": [
            strategy_config(
                STRATEGY_NAME,
                symbol,
            )
        ],
        "initial_balance": starting_balance,
        "max_portfolio_leverage": 30.0,
        "max_total_risk_percent": 0.5,
        "trading_start_timestamp": fold_start,
    }

    if use_regime_risk:
        arguments[
            "risk_percent_adjuster"
        ] = regime_risk_adjuster

    return run_portfolio_backtest(**arguments)


def average_risk_percent(
    result,
    starting_balance: float,
) -> float:
    if not result.trades:
        return 0.0

    percentages = []

    balance = starting_balance

    for trade in result.trades:
        if balance > 0:
            percentages.append(
                trade.risk_amount
                / balance
                * 100
            )

        balance += trade.net_pnl

    return sum(percentages) / len(percentages)


def reduced_risk_trade_count(
    result,
) -> int:
    return sum(
        trade.risk_amount
        < (
            trade.risk_amount
            / 0.75
        )
        for trade in []
    )


def run_market(
    symbol: str,
    candles,
) -> dict:
    regime_balance = INITIAL_BALANCE
    fixed_balance = INITIAL_BALANCE
    folds = []

    for fold_number, (
        start_text,
        end_text,
    ) in enumerate(
        DEVELOPMENT_FOLDS,
        start=1,
    ):
        fold_start = start_timestamp(start_text)
        fold_end = end_timestamp(end_text)

        regime_starting_balance = regime_balance
        fixed_starting_balance = fixed_balance

        regime_result = run_fold(
            symbol=symbol,
            candles=candles,
            fold_start=fold_start,
            fold_end=fold_end,
            starting_balance=regime_starting_balance,
            use_regime_risk=True,
        )

        fixed_result = run_fold(
            symbol=symbol,
            candles=candles,
            fold_start=fold_start,
            fold_end=fold_end,
            starting_balance=fixed_starting_balance,
            use_regime_risk=False,
        )

        regime_return = (
            regime_result.final_balance
            / regime_starting_balance
            - 1
        ) * 100

        fixed_return = (
            fixed_result.final_balance
            / fixed_starting_balance
            - 1
        ) * 100

        if (
            regime_result.total_trades
            != fixed_result.total_trades
        ):
            raise RuntimeError(
                f"{symbol} fold {fold_number}: "
                "risk sizing changed the trade count."
            )

        regime_trade_keys = [
            (
                trade.direction,
                trade.signal_timestamp,
                trade.entry_timestamp,
                trade.exit_timestamp,
                trade.entry_price,
                trade.exit_price,
                trade.exit_reason,
            )
            for trade in regime_result.trades
        ]

        fixed_trade_keys = [
            (
                trade.direction,
                trade.signal_timestamp,
                trade.entry_timestamp,
                trade.exit_timestamp,
                trade.entry_price,
                trade.exit_price,
                trade.exit_reason,
            )
            for trade in fixed_result.trades
        ]

        if regime_trade_keys != fixed_trade_keys:
            raise RuntimeError(
                f"{symbol} fold {fold_number}: "
                "risk sizing changed trade signals "
                "or execution timing."
            )

        reduced_trades = sum(
            regime_trade.risk_amount
            < fixed_trade.risk_amount
            for regime_trade, fixed_trade in zip(
                regime_result.trades,
                fixed_result.trades,
                strict=True,
            )
        )

        folds.append(
            {
                "fold": fold_number,
                "start": start_text,
                "end": end_text,
                "trades": regime_result.total_trades,
                "reduced_risk_trades": reduced_trades,
                "regime_return": regime_return,
                "fixed_return": fixed_return,
                "regime_drawdown": (
                    regime_result.max_drawdown_percent
                ),
                "fixed_drawdown": (
                    fixed_result.max_drawdown_percent
                ),
                "regime_pf": profit_factor(
                    regime_result.trades
                ),
                "fixed_pf": profit_factor(
                    fixed_result.trades
                ),
                "regime_average_risk": (
                    average_risk_percent(
                        regime_result,
                        regime_starting_balance,
                    )
                ),
            }
        )

        regime_balance = regime_result.final_balance
        fixed_balance = fixed_result.final_balance

    return {
        "symbol": symbol,
        "folds": folds,
        "regime_return": (
            regime_balance / INITIAL_BALANCE - 1
        ) * 100,
        "fixed_return": (
            fixed_balance / INITIAL_BALANCE - 1
        ) * 100,
        "regime_worst_drawdown": max(
            fold["regime_drawdown"]
            for fold in folds
        ),
        "fixed_worst_drawdown": max(
            fold["fixed_drawdown"]
            for fold in folds
        ),
        "trades": sum(
            fold["trades"]
            for fold in folds
        ),
        "reduced_risk_trades": sum(
            fold["reduced_risk_trades"]
            for fold in folds
        ),
        "regime_profitable_folds": sum(
            fold["regime_return"] > 0
            for fold in folds
        ),
        "fixed_profitable_folds": sum(
            fold["fixed_return"] > 0
            for fold in folds
        ),
        "lower_drawdown_folds": sum(
            fold["regime_drawdown"]
            < fold["fixed_drawdown"]
            for fold in folds
        ),
        "better_return_folds": sum(
            fold["regime_return"]
            > fold["fixed_return"]
            for fold in folds
        ),
    }


def print_market(
    result: dict,
) -> None:
    print()
    print("=" * 118)
    print(result["symbol"])
    print("=" * 118)

    for fold in result["folds"]:
        print(
            f"Fold {fold['fold']}: "
            f"{fold['start']} to {fold['end']}"
        )

        print(
            "  Regime risk | "
            f"Trades {fold['trades']:3d} | "
            f"Reduced {fold['reduced_risk_trades']:3d} | "
            f"Avg risk "
            f"{fold['regime_average_risk']:.3f}% | "
            f"Return {fold['regime_return']:7.2f}% | "
            f"PF {fold['regime_pf']:6.3f} | "
            f"DD {fold['regime_drawdown']:5.2f}%"
        )

        print(
            "  Fixed risk  | "
            f"Trades {fold['trades']:3d} | "
            f"Risk 0.500% | "
            f"Return {fold['fixed_return']:7.2f}% | "
            f"PF {fold['fixed_pf']:6.3f} | "
            f"DD {fold['fixed_drawdown']:5.2f}%"
        )

        print(
            "  Return difference:",
            round(
                fold["regime_return"]
                - fold["fixed_return"],
                2,
            ),
            "percentage points",
        )

        print(
            "  Drawdown difference:",
            round(
                fold["regime_drawdown"]
                - fold["fixed_drawdown"],
                2,
            ),
            "percentage points",
        )

        print("-" * 118)

    print("MARKET SUMMARY")
    print(
        "Regime-risk sequential return:",
        round(result["regime_return"], 2),
        "%",
    )
    print(
        "Fixed-risk sequential return:",
        round(result["fixed_return"], 2),
        "%",
    )
    print(
        "Return difference:",
        round(
            result["regime_return"]
            - result["fixed_return"],
            2,
        ),
        "percentage points",
    )
    print(
        "Regime-risk worst drawdown:",
        round(
            result["regime_worst_drawdown"],
            2,
        ),
        "%",
    )
    print(
        "Fixed-risk worst drawdown:",
        round(
            result["fixed_worst_drawdown"],
            2,
        ),
        "%",
    )
    print(
        "Lower-drawdown folds:",
        f"{result['lower_drawdown_folds']}/6",
    )
    print(
        "Better-return folds:",
        f"{result['better_return_folds']}/6",
    )
    print(
        "Reduced-risk trades:",
        f"{result['reduced_risk_trades']}/"
        f"{result['trades']}",
    )


def main() -> None:
    print(
        "REGIME-AWARE RISK SIZING "
        "SIX-MARKET WALK-FORWARD"
    )
    print("=" * 118)
    print(
        "Signal: fixed ATR breakout."
    )
    print(
        "Comparison: deterministic regime-adjusted risk "
        "versus fixed 0.5% risk."
    )
    print(
        "Only folds ending by 4 August 2024 are included."
    )
    print(
        "This is development evidence, not an untouched "
        "holdout."
    )

    results = []

    for symbol, path in MARKETS.items():
        candles = load_candles_from_csv(path)

        result = run_market(
            symbol=symbol,
            candles=candles,
        )

        results.append(result)
        print_market(result)

    profitable_markets = sum(
        result["regime_return"] > 0
        for result in results
    )

    better_return_markets = sum(
        result["regime_return"]
        > result["fixed_return"]
        for result in results
    )

    lower_drawdown_markets = sum(
        result["regime_worst_drawdown"]
        < result["fixed_worst_drawdown"]
        for result in results
    )

    equal_drawdown_markets = sum(
        result["regime_worst_drawdown"]
        == result["fixed_worst_drawdown"]
        for result in results
    )

    total_trades = sum(
        result["trades"]
        for result in results
    )

    total_reduced_trades = sum(
        result["reduced_risk_trades"]
        for result in results
    )

    regime_return_sum = sum(
        result["regime_return"]
        for result in results
    )

    fixed_return_sum = sum(
        result["fixed_return"]
        for result in results
    )

    print()
    print("=" * 118)
    print("SIX-MARKET DEVELOPMENT SUMMARY")
    print("=" * 118)

    for result in results:
        print(
            f"{result['symbol']:7s} | "
            f"Regime {result['regime_return']:7.2f}% | "
            f"Fixed {result['fixed_return']:7.2f}% | "
            f"Difference "
            f"{result['regime_return'] - result['fixed_return']:7.2f}pp | "
            f"Regime DD "
            f"{result['regime_worst_drawdown']:5.2f}% | "
            f"Fixed DD "
            f"{result['fixed_worst_drawdown']:5.2f}%"
        )

    print()
    print(
        "Profitable regime-risk markets:",
        profitable_markets,
        "/ 6",
    )
    print(
        "Markets with better return:",
        better_return_markets,
        "/ 6",
    )
    print(
        "Markets with lower worst drawdown:",
        lower_drawdown_markets,
        "/ 6",
    )
    print(
        "Markets with equal worst drawdown:",
        equal_drawdown_markets,
        "/ 6",
    )
    print(
        "Total trades:",
        total_trades,
    )
    print(
        "Trades receiving reduced risk:",
        total_reduced_trades,
    )
    print(
        "Sum of regime-risk returns:",
        round(regime_return_sum, 2),
        "%",
    )
    print(
        "Sum of fixed-risk returns:",
        round(fixed_return_sum, 2),
        "%",
    )

    development_pass = (
        lower_drawdown_markets >= 4
        and profitable_markets >= 3
        and regime_return_sum > 0
        and total_trades >= 400
    )

    print()
    print(
        "DEVELOPMENT RESULT:",
        "PASSED"
        if development_pass
        else "FAILED",
    )
    print(
        "RESEARCH STATUS: DEVELOPMENT_ONLY"
    )


if __name__ == "__main__":
    main()
