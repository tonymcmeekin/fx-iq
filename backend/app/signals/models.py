from pydantic import BaseModel


class TradeSignal(BaseModel):
    symbol: str
    direction: str
    confidence: float
    strategy_name: str
    reason: str
