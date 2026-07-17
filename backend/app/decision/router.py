from fastapi import APIRouter, HTTPException

from app.decision.engine import evaluate_trade_decision
from app.decision.models import (
    DecisionEvaluationRequest,
    DecisionEvaluationResponse,
    TradeDecision,
)

router = APIRouter(prefix="/decision", tags=["Decision"])


@router.get("/sample", response_model=TradeDecision)
def sample_decision():
    return TradeDecision(
        signal="BUY EUR_USD",
        approved=True,
        decision="APPROVED_FOR_PAPER_TRADE",
        reason="Signal passed basic risk checks.",
    )


@router.post(
    "/evaluate",
    response_model=DecisionEvaluationResponse,
)
def evaluate_decision(
    request: DecisionEvaluationRequest,
) -> DecisionEvaluationResponse:
    try:
        return evaluate_trade_decision(request)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "status": "REJECTED",
                "error": str(error),
                "live_trading_allowed": False,
                "broker_orders_submitted": 0,
            },
        ) from error
