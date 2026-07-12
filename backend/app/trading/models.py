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
    gross_profit_percent: float = 0.0
    trading_cost_percent: float = 0.0
    spread_pips: float = 0.0
    commission_percent: float = 0.0
    slippage_pips: float = 0.0
    account_balance_before: float | None = None
    risk_amount: float | None = None
    position_size_units: float | None = None
    notional_value: float | None = None
    leverage_used: float | None = None
    position_limited_by_leverage: bool = False
    gross_profit_percent: float = 0.0
    trading_cost_percent: float = 0.0
    spread_pips: float = 0.0
    commission_percent: float = 0.0
