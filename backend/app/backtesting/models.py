from pydantic import BaseModel


class MockTrade(BaseModel):
    symbol: str
    profit_percent: float


class BacktestResult(BaseModel):
    strategy_name: str
    symbol: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_percent: float
    profit_percent: float
    max_drawdown_percent: float
