from datetime import datetime

from pydantic import BaseModel, Field


class Candle(BaseModel):
    symbol: str = Field(..., examples=["EUR_USD"])
    timeframe: str = Field(..., examples=["H1"])
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None
