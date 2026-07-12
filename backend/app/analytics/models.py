from pydantic import BaseModel


class EquityPoint(BaseModel):
    trade_number: int
    balance: float
    profit_percent: float
