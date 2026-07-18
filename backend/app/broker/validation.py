from __future__ import annotations

import math

from app.broker.models import (
    BrokerDirection,
    BrokerEnvironment,
    BrokerOrderRequest,
)


class BrokerOrderValidationError(ValueError):
    pass


def validate_broker_order(
    request: BrokerOrderRequest,
) -> None:
    if request.environment is not BrokerEnvironment.PRACTICE:
        raise BrokerOrderValidationError(
            "Only the OANDA practice environment is permitted."
        )

    if request.paper_trading_only is not True:
        raise BrokerOrderValidationError(
            "paper_trading_only must remain true."
        )

    if request.live_trading_allowed is not False:
        raise BrokerOrderValidationError(
            "live_trading_allowed must remain false."
        )

    if request.direction not in {
        BrokerDirection.BUY,
        BrokerDirection.SELL,
    }:
        raise BrokerOrderValidationError(
            "Direction must be BUY or SELL."
        )

    instrument_parts = request.instrument.split("_")

    if (
        len(instrument_parts) != 2
        or any(len(part) != 3 for part in instrument_parts)
        or not all(part.isalpha() for part in instrument_parts)
        or request.instrument != request.instrument.upper()
    ):
        raise BrokerOrderValidationError(
            "Instrument must use OANDA format such as EUR_USD."
        )

    if isinstance(request.units, bool) or request.units <= 0:
        raise BrokerOrderValidationError(
            "Order units must be a positive integer."
        )

    for name, value in {
        "stop_loss": request.stop_loss,
        "take_profit": request.take_profit,
    }.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(float(value))
            or float(value) <= 0
        ):
            raise BrokerOrderValidationError(
                f"{name} must be a positive finite number."
            )

    if request.stop_loss == request.take_profit:
        raise BrokerOrderValidationError(
            "Stop-loss and take-profit cannot be equal."
        )

    if (
        request.direction is BrokerDirection.BUY
        and request.stop_loss >= request.take_profit
    ):
        raise BrokerOrderValidationError(
            "BUY stop-loss must be below take-profit."
        )

    if (
        request.direction is BrokerDirection.SELL
        and request.stop_loss <= request.take_profit
    ):
        raise BrokerOrderValidationError(
            "SELL stop-loss must be above take-profit."
        )
