import pytest

from app.broker import (
    BrokerDirection,
    BrokerOrderRequest,
    BrokerOrderStatus,
    BrokerOrderValidationError,
    OandaPracticeShadowGateway,
    build_oanda_market_order_payload,
    validate_broker_order,
)


def make_request(
    *,
    direction: BrokerDirection = BrokerDirection.BUY,
    stop_loss: float = 1.095,
    take_profit: float = 1.11,
) -> BrokerOrderRequest:
    return BrokerOrderRequest(
        instrument="EUR_USD",
        direction=direction,
        units=1250,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


def test_buy_payload_uses_positive_units():
    payload = build_oanda_market_order_payload(
        make_request()
    )

    order = payload.order["order"]

    assert order["instrument"] == "EUR_USD"
    assert order["units"] == "1250"
    assert order["type"] == "MARKET"
    assert order["stopLossOnFill"]["price"] == "1.095"
    assert order["takeProfitOnFill"]["price"] == "1.11"


def test_sell_payload_uses_negative_units():
    payload = build_oanda_market_order_payload(
        make_request(
            direction=BrokerDirection.SELL,
            stop_loss=1.11,
            take_profit=1.095,
        )
    )

    assert payload.order["order"]["units"] == "-1250"


def test_shadow_gateway_never_submits_order():
    result = OandaPracticeShadowGateway().prepare_order(
        make_request()
    )

    assert result.status is BrokerOrderStatus.SHADOWED
    assert result.payload is not None
    assert result.network_calls_made == 0
    assert result.broker_orders_submitted == 0
    assert result.broker_order_id is None
    assert result.broker_trade_id is None
    assert result.paper_trading_only is True
    assert result.live_trading_allowed is False


def test_shadow_gateway_rejects_invalid_order():
    result = OandaPracticeShadowGateway().prepare_order(
        make_request(
            stop_loss=1.12,
            take_profit=1.11,
        )
    )

    assert result.status is BrokerOrderStatus.REJECTED
    assert result.payload is None
    assert result.network_calls_made == 0
    assert result.broker_orders_submitted == 0


def test_live_trading_flag_is_rejected():
    request = BrokerOrderRequest(
        instrument="EUR_USD",
        direction=BrokerDirection.BUY,
        units=1250,
        stop_loss=1.095,
        take_profit=1.11,
        live_trading_allowed=True,
    )

    with pytest.raises(
        BrokerOrderValidationError,
        match="live_trading_allowed",
    ):
        validate_broker_order(request)


@pytest.mark.parametrize(
    ("instrument", "units"),
    [
        ("EURUSD", 1000),
        ("eur_usd", 1000),
        ("EUR_USD", 0),
        ("EUR_USD", -1000),
    ],
)
def test_invalid_instrument_or_units_are_rejected(
    instrument: str,
    units: int,
):
    request = BrokerOrderRequest(
        instrument=instrument,
        direction=BrokerDirection.BUY,
        units=units,
        stop_loss=1.095,
        take_profit=1.11,
    )

    with pytest.raises(BrokerOrderValidationError):
        validate_broker_order(request)
