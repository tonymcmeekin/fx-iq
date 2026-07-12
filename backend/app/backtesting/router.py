from pathlib import Path

from fastapi import APIRouter

from app.backtesting.calculations import calculate_backtest_result
from app.backtesting.engine import run_strategy_backtest
from app.backtesting.models import BacktestResult, MockTrade
from app.market_data.csv_loader import load_candles_from_csv

router = APIRouter(prefix="/backtesting", tags=["Backtesting"])

HISTORICAL_DATA_FILE = Path("data/eur_usd_daily.csv")
SAMPLE_DATA_FILE = Path("data/eur_usd_sample.csv")


def get_backtest_data_file() -> Path:
    if HISTORICAL_DATA_FILE.exists():
        return HISTORICAL_DATA_FILE

    return SAMPLE_DATA_FILE


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
def run_backtest(strategy_name: str) -> BacktestResult:
    data_file = get_backtest_data_file()
    candles = load_candles_from_csv(data_file)

    return run_strategy_backtest(strategy_name, candles)
