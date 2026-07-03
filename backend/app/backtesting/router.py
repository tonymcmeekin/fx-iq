from pathlib import Path

from fastapi import APIRouter

from app.backtesting.calculations import calculate_backtest_result
from app.backtesting.engine import run_simple_trend_backtest
from app.backtesting.models import BacktestResult, MockTrade
from app.market_data.csv_loader import load_candles_from_csv

router = APIRouter(prefix="/backtesting", tags=["Backtesting"])


@router.get("/sample", response_model=BacktestResult)
def sample_backtest():
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


@router.get("/simple-trend", response_model=BacktestResult)
def simple_trend_backtest():
    candles = load_candles_from_csv(Path("data/eur_usd_sample.csv"))
    return run_simple_trend_backtest(candles)
