from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class Candle(BaseModel):
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_price_range(self) -> Candle:
        if self.high < self.low:
            raise ValueError("high must be greater than or equal to low")

        if not self.low <= self.open <= self.high:
            raise ValueError("open must be between low and high")

        if not self.low <= self.close <= self.high:
            raise ValueError("close must be between low and high")

        return self


class Strategy(BaseModel):
    name: str
    description: str
    status: str
