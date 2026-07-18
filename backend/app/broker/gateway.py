from __future__ import annotations

from app.broker.models import (
    BrokerOrderRequest,
    BrokerOrderResult,
    BrokerOrderStatus,
)
from app.broker.oanda_payload import (
    build_oanda_market_order_payload,
)
from app.broker.validation import BrokerOrderValidationError


class OandaPracticeShadowGateway:
    """
    Build and validate OANDA Practice order payloads without sending them.

    This gateway deliberately contains no HTTP client and cannot make
    network calls or submit broker orders.
    """

    def prepare_order(
        self,
        request: BrokerOrderRequest,
    ) -> BrokerOrderResult:
        try:
            payload = build_oanda_market_order_payload(
                request
            )
        except BrokerOrderValidationError as error:
            return BrokerOrderResult(
                status=BrokerOrderStatus.REJECTED,
                reason=str(error),
                payload=None,
                broker_order_id=None,
                broker_trade_id=None,
                network_calls_made=0,
                broker_orders_submitted=0,
                paper_trading_only=True,
                live_trading_allowed=False,
            )

        return BrokerOrderResult(
            status=BrokerOrderStatus.SHADOWED,
            reason=(
                "Order validated and prepared in shadow mode. "
                "Nothing was sent to OANDA."
            ),
            payload=payload,
            broker_order_id=None,
            broker_trade_id=None,
            network_calls_made=0,
            broker_orders_submitted=0,
            paper_trading_only=True,
            live_trading_allowed=False,
        )
