from datetime import datetime
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.ai.regime_risk import (
    calculate_regime_risk,
    calculate_selective_regime_risk,
)
from app.ai.regime import detect_market_regime
from app.market_data.csv_loader import load_candles_from_csv
from app.portfolio.engine import run_portfolio_backtest
from app.portfolio.models import PortfolioStrategyConfig
from scripts.adaptive_regime_policy_walk_forward import (
    INITIAL_BALANCE,
    end_timestamp,
    profit_factor,
    start_timestamp,
)


BASE_RISK_PERCENT = 0.5
DEVELOPMENT_END = "2024-08-04"

MARKETS = {
    "EUR_USD": Path("data/oanda_eur_usd_daily.csv"),
    "GBP_USD": Path("data/oanda_gbp_usd_daily.csv"),
    "AUD_USD": Path("data/oanda_aud_usd_daily.csv"),
    "USD_JPY": Path("data/oanda_usd_jpy_daily.csv"),
    "USD_CAD": Path("data/oanda_usd_cad_daily.csv"),
    "NZD_USD": Path("data/oanda_nzd_usd_daily.csv"),
}

FOLDS = [
    ("2013-01-28", "2014-12-16"),
    ("2014-12-17", "2016-11-20"),
    ("2016-11-21", "2018-10-23"),
    ("2018-10-24", "2020-09-27"),
    ("2020-09-28", "2022-08-30"),
    ("2022-08-31", "2024-08-04"),
]


def strategy_config(
    symbol: str,
) -> PortfolioStrategyConfig:
    return PortfolioStrategyConfig(
        strategy_name="atr_breakout",
        symbol=symbol,
        stop_loss_percent=1.5,
        take_profit_percent=3.0,
        risk_per_trade_percent=BASE_RISK_PERCENT,
        spread_pips=1.0,
        slippage_pips=0.5,
    )


def broad_adjuster(config, history, direction):
    del direction

    try:
        regime = detect_market_regime(history)
    except ValueError:
        return config.risk_per_trade_percent

    decision = calculate_regime_risk(
        base_risk_percent=config.risk_per_trade_percent,
        regime=regime,
    )

    return decision.adjusted_risk_percent


def selective_adjuster(config, history, direction):
    try:
        regime = detect_market_regime(history)
    except ValueError:
        return config.risk_per_trade_percent

    decision = calculate_selective_regime_risk(
        base_risk_percent=config.risk_per_trade_percent,
        regime=regime,
        direction=direction,
    )

    return decision.adjusted_risk_percent


def run_fold(
    symbol: str,
    candles,
    fold_start: datetime,
    fold_end: datetime,
    starting_balance: float,
    risk_adjuster=None,
):
    available_candles = [
        candle
        for candle in candles
        if candle.timestamp <= fold_end
    ]

    return run_portfolio_backtest(
        candles_by_symbol={
            symbol: available_candles,
        },
        strategy_configs=[
            strategy_config(symbol),
        ],
        initial_balance=starting_balance,
        max_portfolio_leverage=30.0,
        max_total_risk_percent=BASE_RISK_PERCENT,
        trading_start_timestamp=fold_start,
        risk_percent_adjuster=risk_adjuster,
    )


def fold_return(result, starting_balance):
    return (
        result.final_balance
        / starting_balance
        - 1
    ) * 100


def run_market(symbol: str, candles) -> dict:
    fixed_balance = INITIAL_BALANCE
    broad_balance = INITIAL_BALANCE
    selective_balance = INITIAL_BALANCE

    folds = []

    for fold_number, (start_text, end_text) in enumerate(
        FOLDS,
        start=1,
    ):
        fold_start = start_timestamp(start_text)
        fold_end = end_timestamp(end_text)

        fixed = run_fold(
            symbol=symbol,
            candles=candles,
            fold_start=fold_start,
            fold_end=fold_end,
            starting_balance=fixed_balance,
        )

        broad = run_fold(
            symbol=symbol,
            candles=candles,
            fold_start=fold_start,
            fold_end=fold_end,
            starting_balance=broad_balance,
            risk_adjuster=broad_adjuster,
        )

        selective = run_fold(
            symbol=symbol,
            candles=candles,
            fold_start=fold_start,
            fold_end=fold_end,
            starting_balance=selective_balance,
            risk_adjuster=selective_adjuster,
        )

        fixed_return = fold_return(
            fixed,
            fixed_balance,
        )
        broad_return = fold_return(
            broad,
            broad_balance,
        )
        selective_return = fold_return(
            selective,
            selective_balance,
        )

        reduced_selective = sum(
            trade.risk_amount
            < trade.account_return_percent * 0
            for trade in []
        )

        folds.append(
            {
                "fold": fold_number,
                "start": start_text,
                "end": end_text,
                "fixed": fixed,
                "broad": broad,
                "selective": selective,
                "fixed_return": fixed_return,
                "broad_return": broad_return,
                "selective_return": selective_return,
            }
        )

        fixed_balance = fixed.final_balance
        broad_balance = broad.final_balance
        selective_balance = selective.final_balance

    return {
        "symbol": symbol,
        "folds": folds,
        "fixed_return": (
            fixed_balance / INITIAL_BALANCE - 1
        ) * 100,
        "broad_return": (
            broad_balance / INITIAL_BALANCE - 1
        ) * 100,
        "selective_return": (
            selective_balance / INITIAL_BALANCE - 1
        ) * 100,
        "fixed_worst_drawdown": max(
            fold["fixed"].max_drawdown_percent
            for fold in folds
        ),
        "broad_worst_drawdown": max(
            fold["broad"].max_drawdown_percent
            for fold in folds
        ),
        "selective_worst_drawdown": max(
            fold["selective"].max_drawdown_percent
            for fold in folds
        ),
        "trades": sum(
            fold["fixed"].total_trades
            for fold in folds
        ),
    }


def print_market(result: dict) -> None:
    print()
    print("=" * 122)
    print(result["symbol"])
    print("=" * 122)

    for fold in result["folds"]:
        fixed = fold["fixed"]
        broad = fold["broad"]
        selective = fold["selective"]

        print(
            f"Fold {fold['fold']}: "
            f"{fold['start']} to {fold['end']}"
        )
        print(
            "  Fixed     | "
            f"Trades {fixed.total_trades:3d} | "
            f"Return {fold['fixed_return']:7.2f}% | "
            f"PF {profit_factor(fixed.trades):6.3f} | "
            f"DD {fixed.max_drawdown_percent:5.2f}%"
        )
        print(
            "  Broad v1  | "
            f"Trades {broad.total_trades:3d} | "
            f"Return {fold['broad_return']:7.2f}% | "
            f"PF {profit_factor(broad.trades):6.3f} | "
            f"DD {broad.max_drawdown_percent:5.2f}%"
        )
        print(
            "  Select v2 | "
            f"Trades {selective.total_trades:3d} | "
            f"Return {fold['selective_return']:7.2f}% | "
            f"PF {profit_factor(selective.trades):6.3f} | "
            f"DD {selective.max_drawdown_percent:5.2f}%"
        )
        print(
            "  Selective versus fixed:",
            round(
                fold["selective_return"]
                - fold["fixed_return"],
                2,
            ),
            "percentage points",
        )
        print("-" * 122)

    print("MARKET SUMMARY")
    print(
        "Fixed sequential return:",
        round(result["fixed_return"], 2),
        "%",
    )
    print(
        "Broad v1 sequential return:",
        round(result["broad_return"], 2),
        "%",
    )
    print(
        "Selective v2 sequential return:",
        round(result["selective_return"], 2),
        "%",
    )
    print(
        "Selective versus fixed:",
        round(
            result["selective_return"]
            - result["fixed_return"],
            2,
        ),
        "percentage points",
    )
    print(
        "Fixed worst drawdown:",
        round(result["fixed_worst_drawdown"], 2),
        "%",
    )
    print(
        "Broad v1 worst drawdown:",
        round(result["broad_worst_drawdown"], 2),
        "%",
    )
    print(
        "Selective v2 worst drawdown:",
        round(result["selective_worst_drawdown"], 2),
        "%",
    )


def main() -> None:
    print(
        "TRADE IQ SELECTIVE REGIME-RISK "
        "RETROSPECTIVE DEVELOPMENT COMPARISON"
    )
    print("=" * 122)
    print(
        "Fixed 0.5% risk versus broad policy v1 versus "
        "selective direction-aware policy v2."
    )
    print(
        "Only folds ending by 4 August 2024 are included."
    )
    print(
        "Policy v2 was derived from these development results, "
        "so this is diagnostic evidence rather than an "
        "independent validation."
    )

    results = []

    for symbol, path in MARKETS.items():
        candles = load_candles_from_csv(path)

        candles = [
            candle
            for candle in candles
            if candle.timestamp
            <= end_timestamp(DEVELOPMENT_END)
        ]

        result = run_market(
            symbol=symbol,
            candles=candles,
        )

        results.append(result)
        print_market(result)

    print()
    print("=" * 122)
    print("SIX-MARKET SUMMARY")
    print("=" * 122)

    for result in results:
        print(
            f"{result['symbol']:7s} | "
            f"Fixed {result['fixed_return']:7.2f}% | "
            f"Broad {result['broad_return']:7.2f}% | "
            f"Selective {result['selective_return']:7.2f}% | "
            f"Selective vs fixed "
            f"{result['selective_return'] - result['fixed_return']:7.2f}pp | "
            f"Fixed DD {result['fixed_worst_drawdown']:5.2f}% | "
            f"Selective DD "
            f"{result['selective_worst_drawdown']:5.2f}%"
        )

    print()
    print(
        "Markets where selective beats fixed:",
        sum(
            result["selective_return"]
            > result["fixed_return"]
            for result in results
        ),
        "/",
        len(results),
    )
    print(
        "Markets where selective lowers drawdown:",
        sum(
            result["selective_worst_drawdown"]
            < result["fixed_worst_drawdown"]
            for result in results
        ),
        "/",
        len(results),
    )
    print(
        "Sum of fixed returns:",
        round(
            sum(
                result["fixed_return"]
                for result in results
            ),
            2,
        ),
        "%",
    )
    print(
        "Sum of broad v1 returns:",
        round(
            sum(
                result["broad_return"]
                for result in results
            ),
            2,
        ),
        "%",
    )
    print(
        "Sum of selective v2 returns:",
        round(
            sum(
                result["selective_return"]
                for result in results
            ),
            2,
        ),
        "%",
    )
    print(
        "Total trades:",
        sum(
            result["trades"]
            for result in results
        ),
    )

    print()
    print(
        "STATUS: RETROSPECTIVE_DEVELOPMENT_ONLY"
    )
    print(
        "The external holdout is not accessed or reused."
    )


if __name__ == "__main__":
    main()
