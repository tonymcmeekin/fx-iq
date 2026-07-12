from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.backtesting.calculations import calculate_backtest_result
from app.backtesting.engine import run_strategy_backtest
from app.backtesting.models import BacktestResult, MockTrade
from app.market_data.csv_loader import load_candles_from_csv

router = APIRouter(prefix="/backtesting", tags=["Backtesting"])


def get_backtest_data_file() -> Path:
    historical_file = Path("data/eur_usd_daily.csv")

    if historical_file.exists():
        return historical_file

    return Path("data/eur_usd_sample.csv")


@router.get("/sample", response_model=BacktestResult)
def sample_backtest() -> BacktestResult:
    trades = [
        MockTrade(symbol="EUR_USD", profit_percent=1.2),
        MockTrade(symbol="EUR_USD", profit_percent=-0.5),
        MockTrade(symbol="EUR_USD", profit_percent=0.8),
        MockTrade(symbol="EUR_USD", profit_percent=2.1),
        MockTrade(symbol="EUR_USD", profit_percent=-1.0),
    ]

    return calculate_backtest_result(
        strategy_name="Trend Following",
        symbol="EUR_USD",
        trades=trades,
    )


@router.get("/run/{strategy_name}", response_model=BacktestResult)
def run_backtest(
    strategy_name: str,
    stop_loss_percent: float = Query(
        default=1.0,
        gt=0,
        le=100,
        description="Stop-loss distance as a percentage of entry price.",
    ),
    take_profit_percent: float = Query(
        default=2.0,
        gt=0,
        le=100,
        description="Take-profit distance as a percentage of entry price.",
    ),
    spread_pips: float = Query(
        default=0.0,
        ge=0,
        le=100,
        description="Round-trip spread cost measured in pips.",
    ),
    commission_percent: float = Query(
        default=0.0,
        ge=0,
        le=100,
        description="Commission cost as a percentage of trade value.",
    ),
) -> BacktestResult:
    data_file = get_backtest_data_file()
    candles = load_candles_from_csv(data_file)

    try:
        return run_strategy_backtest(
            strategy_name=strategy_name,
            candles=candles,
            stop_loss_percent=stop_loss_percent,
            take_profit_percent=take_profit_percent,
            spread_pips=spread_pips,
            commission_percent=commission_percent,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error
