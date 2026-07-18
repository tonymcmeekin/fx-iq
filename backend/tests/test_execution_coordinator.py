from app.broker import (
    BrokerOrderStatus,
    ExecutionCoordinator,
)


def make_position(
    **overrides,
):
    position = {
        "account": "candidate",
        "market": "EUR_USD",
        "direction": "BUY",
        "status": "OPEN",
        "entry_price": 1.1,
        "stop_loss": 1.095,
        "take_profit": 1.11,
        "position_size_units": 1250.75,
        "broker_orders_submitted": 0,
    }
    position.update(overrides)
    return position


def test_coordinator_prepares_open_paper_position():
    coordinated = (
        ExecutionCoordinator()
        .prepare_paper_position(
            make_position()
        )
    )

    assert coordinated.market == "EUR_USD"
    assert coordinated.account == "candidate"
    assert coordinated.paper_position_status == "OPEN"
    assert coordinated.requested_units == 1250.75
    assert coordinated.broker_units == 1250

    result = coordinated.result

    assert result.status is BrokerOrderStatus.SHADOWED
    assert result.payload is not None
    assert result.network_calls_made == 0
    assert result.broker_orders_submitted == 0
    assert result.paper_trading_only is True
    assert result.live_trading_allowed is False

    order = result.payload.order["order"]

    assert order["instrument"] == "EUR_USD"
    assert order["units"] == "1250"
    assert order["stopLossOnFill"]["price"] == "1.095"
    assert order["takeProfitOnFill"]["price"] == "1.11"


def test_sell_position_produces_negative_units():
    coordinated = (
        ExecutionCoordinator()
        .prepare_paper_position(
            make_position(
                direction="SELL",
                stop_loss=1.11,
                take_profit=1.095,
            )
        )
    )

    assert (
        coordinated.result.payload
        is not None
    )
    assert (
        coordinated.result.payload.order[
            "order"
        ]["units"]
        == "-1250"
    )


def test_fractional_units_are_never_rounded_up():
    coordinated = (
        ExecutionCoordinator()
        .prepare_paper_position(
            make_position(
                position_size_units=999.999,
            )
        )
    )

    assert coordinated.requested_units == 999.999
    assert coordinated.broker_units == 999
    assert (
        coordinated.result.status
        is BrokerOrderStatus.SHADOWED
    )


def test_closed_position_is_rejected():
    coordinated = (
        ExecutionCoordinator()
        .prepare_paper_position(
            make_position(status="CLOSED")
        )
    )

    assert (
        coordinated.result.status
        is BrokerOrderStatus.REJECTED
    )
    assert "Only OPEN" in coordinated.result.reason
    assert coordinated.result.network_calls_made == 0
    assert coordinated.result.broker_orders_submitted == 0


def test_position_with_existing_broker_order_is_rejected():
    coordinated = (
        ExecutionCoordinator()
        .prepare_paper_position(
            make_position(
                broker_orders_submitted=1,
            )
        )
    )

    assert (
        coordinated.result.status
        is BrokerOrderStatus.REJECTED
    )
    assert (
        "already records a broker order"
        in coordinated.result.reason
    )


def test_missing_position_field_is_rejected():
    position = make_position()
    del position["stop_loss"]

    coordinated = (
        ExecutionCoordinator()
        .prepare_paper_position(position)
    )

    assert (
        coordinated.result.status
        is BrokerOrderStatus.REJECTED
    )
    assert "stop_loss" in coordinated.result.reason


def test_position_below_one_unit_is_rejected():
    coordinated = (
        ExecutionCoordinator()
        .prepare_paper_position(
            make_position(
                position_size_units=0.75,
            )
        )
    )

    assert (
        coordinated.result.status
        is BrokerOrderStatus.REJECTED
    )
    assert (
        "below one whole broker unit"
        in coordinated.result.reason
    )


def test_invalid_buy_protection_is_rejected():
    coordinated = (
        ExecutionCoordinator()
        .prepare_paper_position(
            make_position(
                stop_loss=1.12,
                take_profit=1.11,
            )
        )
    )

    assert (
        coordinated.result.status
        is BrokerOrderStatus.REJECTED
    )
    assert coordinated.result.payload is None
    assert coordinated.result.network_calls_made == 0
    assert coordinated.result.broker_orders_submitted == 0
