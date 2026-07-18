from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OandaAccountSnapshot:
    account_id: str
    currency: str
    balance: float
    nav: float
    margin_used: float
    margin_available: float
    open_trade_count: int
    open_position_count: int
    pending_order_count: int
    last_transaction_id: str | None
    trades: tuple[dict[str, Any], ...]
    positions: tuple[dict[str, Any], ...]
    orders: tuple[dict[str, Any], ...]
    source: str = "OANDA_PRACTICE"
    read_only: bool = True
    network_calls_made: int = 1
    broker_orders_submitted: int = 0
    paper_trading_only: bool = True
    live_trading_allowed: bool = False
