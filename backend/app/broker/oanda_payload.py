from __future__ import annotations

from decimal import Decimal

from app.broker.models import (
    BrokerOrderPayload,
    BrokerOrderRequest,
)
from app.broker.validation import validate_broker_order


def format_price(value: float) -> str:
    return format(
        Decimal(str(value)).normalize(),
        "f",
    )


def build_oanda_market_order_payload(
    request: BrokerOrderRequest,
) -> BrokerOrderPayload:
    validate_broker_order(request)

    return BrokerOrderPayload(
        order={
            "order": {
                "type": "MARKET",
                "instrument": request.instrument,
                "units": str(request.signed_units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {
                    "price": format_price(request.stop_loss),
                    "timeInForce": "GTC",
                },
                "takeProfitOnFill": {
                    "price": format_price(request.take_profit),
                    "timeInForce": "GTC",
                },
            }
        }
    )
