from datetime import datetime

from pydantic import BaseModel, Field


class PortfolioStrategyConfig(BaseModel):
    strategy_name: str
    symbol: str
    stop_loss_percent: float = 1.0
    take_profit_percent: float = 2.0
    risk_per_trade_percent: float = 0.25
    spread_pips: float = 0.0
    commission_percent: float = 0.0
    slippage_pips: float = 0.0
    pip_size: float = 0.0001
    allowed_directions: set[str] | None = None


class PortfolioTrade(BaseModel):
    strategy_name: str
    symbol: str
    direction: str

    signal_timestamp: datetime
    entry_timestamp: datetime
    exit_timestamp: datetime

    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float

    position_size_units: float
    notional_value: float
    risk_amount: float
    leverage_at_entry: float

    gross_pnl: float
    trading_cost: float
    net_pnl: float
    account_return_percent: float

    exit_reason: str


class PortfolioEquityPoint(BaseModel):
    timestamp: datetime
    balance: float
    equity: float
    unrealized_pnl: float
    open_positions: int
    gross_leverage: float


class PortfolioStrategySummary(BaseModel):
    strategy_name: str
    symbol: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    net_pnl: float


class PortfolioBacktestResult(BaseModel):
    initial_balance: float
    final_balance: float
    final_equity: float

    return_percent: float
    max_drawdown_percent: float

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_percent: float

    rejected_entries: int
    maximum_open_positions: int
    maximum_gross_leverage: float

    trades: list[PortfolioTrade] = Field(default_factory=list)
    equity_curve: list[PortfolioEquityPoint] = Field(
        default_factory=list
    )
    strategy_summaries: list[PortfolioStrategySummary] = Field(
        default_factory=list
    )
