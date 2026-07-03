from pathlib import Path

from fastapi import APIRouter

from app.market_data.csv_loader import load_candles_from_csv
from app.strategies.models import Strategy
from app.strategies.simple_trend import generate_simple_trend_signal

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
