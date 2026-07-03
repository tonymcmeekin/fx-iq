from pathlib import Path

from fastapi import APIRouter

from app.market_data.csv_loader import load_candles_from_csv
from app.strategies.models import Strategy
from app.strategies.simple_trend import generate_simple_trend_signal
from app.strategies.ema_crossover import generate_ema_crossover_signal
from app.strategies.manager import list_available_strategy_names, run_strategy

router = APIRouter(prefix="/strategies", tags=["Strategies"])


@router.get("/", response_model=list[Strategy])
def list_strategies():
    return [
        Strategy(
            name="Trend Following",
            description="Trades in the direction of the long-term trend.",
            status="Planned",
        ),
        Strategy(
            name="Breakout",
            description="Trades price breakouts from consolidation.",
            status="Planned",
        ),
        Strategy(
            name="Mean Reversion",
            description="Trades moves back toward the average price.",
            status="Planned",
        ),
    ]


@router.get("/simple-trend-signal")
def get_simple_trend_signal():
    candles = load_candles_from_csv(Path("data/eur_usd_sample.csv"))
    return generate_simple_trend_signal(candles)

@router.get("/ema-crossover-signal")
def get_ema_crossover_signal():
    candles = load_candles_from_csv(Path("data/eur_usd_sample.csv"))
    return generate_ema_crossover_signal(candles)

@router.get("/available")
def get_available_strategies():
    return {"strategies": list_available_strategy_names()}


@router.get("/run/{strategy_name}")
def run_named_strategy(strategy_name: str):
    candles = load_candles_from_csv(Path("data/eur_usd_sample.csv"))
    return run_strategy(strategy_name, candles)
    