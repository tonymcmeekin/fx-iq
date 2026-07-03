from fastapi import APIRouter

from app.decision.models import TradeDecision

router = APIRouter(prefix="/decision", tags=["Decision"])


@router.get("/sample", response_model=TradeDecision)
def sample_decision():
    return TradeDecision(
        signal="BUY EUR_USD",
        approved=True,
        decision="APPROVED_FOR_PAPER_TRADE",
        reason="Signal passed basic risk checks.",
    )
