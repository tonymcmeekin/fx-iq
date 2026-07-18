from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BrokerEnvironment(StrEnum):
    PRACTICE = "practice"


class BrokerDirection(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class BrokerOrderStatus(StrEnum):
    SHADOWED = "SHADOWED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class BrokerOrderRequest:
    instrument: str
    direction: BrokerDirection
    units: int
    stop_loss: float
    take_profit: float
    environment: BrokerEnvironment = BrokerEnvironment.PRACTICE
    paper_trading_only: bool = True
    live_trading_allowed: bool = False

    @property
    def signed_units(self) -> int:
        if self.direction is BrokerDirection.BUY:
            return self.units

        return -self.units


@dataclass(frozen=True)
class BrokerOrderPayload:
    order: dict[str, object]


@dataclass(frozen=True)
class BrokerOrderResult:
    status: BrokerOrderStatus
    reason: str
    payload: BrokerOrderPayload | None
    broker_order_id: str | None
    broker_trade_id: str | None
    network_calls_made: int
    broker_orders_submitted: int
    paper_trading_only: bool
    live_trading_allowed: bool
