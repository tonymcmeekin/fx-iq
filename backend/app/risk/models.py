from pydantic import BaseModel


class RiskCheckResult(BaseModel):
    approved: bool
    reason: str
    max_risk_percent: float
