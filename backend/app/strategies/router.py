from fastapi import APIRouter

from app.strategies.models import Strategy

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
