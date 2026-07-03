from fastapi import APIRouter

from app.risk.models import RiskCheckResult

router = APIRouter(prefix="/risk", tags=["Risk"])


@router.get("/sample-check", response_model=RiskCheckResult)
def sample_risk_check():
    return RiskCheckResult(
        approved=True,
        reason="Signal passed basic risk checks.",
        max_risk_percent=1.0,
    )
