from pydantic import BaseModel


class SimulatedTrade(BaseModel):
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    profit_percent: float
    exit_reason: str
    stop_loss: float | None = None
    take_profit: float | None = None
    candles_held: int = 1
