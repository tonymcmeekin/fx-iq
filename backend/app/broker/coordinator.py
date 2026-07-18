from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.broker.gateway import OandaPracticeShadowGateway
from app.broker.models import (
    BrokerDirection,
    BrokerOrderRequest,
    BrokerOrderResult,
    BrokerOrderStatus,
)


class ExecutionCoordinationError(ValueError):
    """Raised when a paper position cannot safely become a broker order."""


@dataclass(frozen=True)
class CoordinatedExecution:
    market: str | None
    account: str | None
    paper_position_status: str | None
    requested_units: float | None
    broker_units: int | None
    result: BrokerOrderResult


_REQUIRED_POSITION_FIELDS = {
    "market",
    "direction",
    "status",
    "stop_loss",
    "take_profit",
    "position_size_units",
}


def _rejected_result(
    reason: str,
) -> BrokerOrderResult:
    return BrokerOrderResult(
        status=BrokerOrderStatus.REJECTED,
        reason=reason,
        payload=None,
        broker_order_id=None,
        broker_trade_id=None,
        network_calls_made=0,
        broker_orders_submitted=0,
        paper_trading_only=True,
        live_trading_allowed=False,
    )


def _read_positive_number(
    position: dict[str, Any],
    field: str,
) -> float:
    value = position.get(field)

    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise ExecutionCoordinationError(
            f"Paper position field {field!r} must be a "
            "positive finite number."
        )

    return float(value)


def _broker_direction(
    value: object,
) -> BrokerDirection:
    try:
        return BrokerDirection(str(value).upper())
    except ValueError as error:
        raise ExecutionCoordinationError(
            "Paper position direction must be BUY or SELL."
        ) from error


def _broker_units(
    requested_units: float,
) -> int:
    """
    Convert risk-sized paper units to OANDA whole units.

    Fractional units are deliberately truncated rather than rounded up,
    ensuring broker exposure never exceeds the paper engine's requested
    position size.
    """

    units = int(requested_units)

    if units <= 0:
        raise ExecutionCoordinationError(
            "Paper position size is below one whole broker unit."
        )

    return units


class ExecutionCoordinator:
    """
    Single controlled bridge from paper positions to broker gateways.

    The default and currently supported gateway is shadow-only. This
    coordinator therefore cannot submit an order or make a network call.
    """

    def __init__(
        self,
        gateway: OandaPracticeShadowGateway | None = None,
    ) -> None:
        self._gateway = (
            gateway
            if gateway is not None
            else OandaPracticeShadowGateway()
        )

    def prepare_paper_position(
        self,
        position: dict[str, Any],
    ) -> CoordinatedExecution:
        market: str | None = None
        account: str | None = None
        status: str | None = None
        requested_units: float | None = None
        broker_units: int | None = None

        try:
            if not isinstance(position, dict):
                raise ExecutionCoordinationError(
                    "Paper position must be a dictionary."
                )

            missing_fields = sorted(
                _REQUIRED_POSITION_FIELDS - position.keys()
            )

            if missing_fields:
                raise ExecutionCoordinationError(
                    "Paper position is missing fields: "
                    + ", ".join(missing_fields)
                )

            market_value = position["market"]

            if not isinstance(market_value, str):
                raise ExecutionCoordinationError(
                    "Paper position market must be a string."
                )

            market = market_value

            account_value = position.get("account")

            if account_value is not None:
                if not isinstance(account_value, str):
                    raise ExecutionCoordinationError(
                        "Paper position account must be a string."
                    )

                account = account_value

            status_value = position["status"]

            if not isinstance(status_value, str):
                raise ExecutionCoordinationError(
                    "Paper position status must be a string."
                )

            status = status_value.upper()

            if status != "OPEN":
                raise ExecutionCoordinationError(
                    "Only OPEN paper positions may be prepared "
                    "for broker execution."
                )

            if position.get("broker_orders_submitted", 0) != 0:
                raise ExecutionCoordinationError(
                    "Paper position already records a broker order."
                )

            direction = _broker_direction(
                position["direction"]
            )

            stop_loss = _read_positive_number(
                position,
                "stop_loss",
            )
            take_profit = _read_positive_number(
                position,
                "take_profit",
            )
            requested_units = _read_positive_number(
                position,
                "position_size_units",
            )
            broker_units = _broker_units(requested_units)

            request = BrokerOrderRequest(
                instrument=market,
                direction=direction,
                units=broker_units,
                stop_loss=stop_loss,
                take_profit=take_profit,
                paper_trading_only=True,
                live_trading_allowed=False,
            )

            result = self._gateway.prepare_order(request)

        except ExecutionCoordinationError as error:
            result = _rejected_result(str(error))

        return CoordinatedExecution(
            market=market,
            account=account,
            paper_position_status=status,
            requested_units=requested_units,
            broker_units=broker_units,
            result=result,
        )
