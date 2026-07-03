from fastapi import APIRouter

from app.signals.models import TradeSignal

router = APIRouter(prefix="/signals", tags=["Signals"])


@router.get("/sample", response_model=TradeSignal)
def get_sample_signal():
    return TradeSignal(
        symbol="EUR_USD",
        direction="BUY",
        confidence=0.72,
        strategy_name="Trend Following",
        reason="Price is above moving average and momentum is positive.",
    )
