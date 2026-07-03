from pydantic import BaseModel


class TradeDecision(BaseModel):
    signal: str
    approved: bool
    decision: str
    reason: str
