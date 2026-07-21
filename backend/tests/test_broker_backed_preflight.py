from dataclasses import replace

import pytest

from app.broker.account_models import (
    OandaAccountSnapshot,
)
from app.paper_trading.runtime_state import (
    empty_runtime_state,
)
from app.safety.broker_preflight import (
    build_broker_backed_preflight,
)

ACCOUNT_ID = "101-004-39785237-001"


def snapshot(
    *,
    margin_available: float = 10000.0,
    positions: tuple[dict, ...] = (),
    orders: tuple[dict, ...] = (),
) -> OandaAccountSnapshot:
    return OandaAccountSnapshot(
        account_id=ACCOUNT_ID,
        currency="GBP",
        balance=10000.0,
        nav=10000.0,
        margin_used=0.0,
        margin_available=margin_available,
        open_trade_count=0,
        open_position_count=len(positions),
        pending_order_count=len(orders),
        last_transaction_id="1",
        trades=(),
        positions=positions,
        orders=orders,
    )


class FakeClient:
    def __init__(
        self,
        *,
        account_snapshot,
    ):
        self.account_snapshot = account_snapshot

    def get_account_snapshot(self):
        return self.account_snapshot


def client_factory(
    account_snapshot,
):
    def factory(
        *,
        token,
        account_id,
    ):
        assert token == "secret-token"
        assert account_id == ACCOUNT_ID

        return FakeClient(account_snapshot=(account_snapshot))

    return factory


def check_by_name(
    report,
    name,
):
    return next(check for check in report.checks if check.name == name)


def test_broker_backed_preflight_passes():
    report = build_broker_backed_preflight(
        token="secret-token",
        account_id=ACCOUNT_ID,
        runtime_state=(empty_runtime_state()),
        minimum_margin_available=1000.0,
        client_factory=client_factory(snapshot()),
    )

    assert report.passed is True
    assert report.failed_checks == ()


def test_broker_position_mismatch_fails():
    report = build_broker_backed_preflight(
        token="secret-token",
        account_id=ACCOUNT_ID,
        runtime_state=(empty_runtime_state()),
        client_factory=client_factory(
            snapshot(
                positions=(
                    {
                        "instrument": ("EUR_USD"),
                    },
                )
            )
        ),
    )

    assert report.passed is False

    assert (
        check_by_name(
            report,
            "position_reconciliation",
        ).passed
        is False
    )


def test_matching_open_position_passes():
    state = empty_runtime_state()

    state["open_positions"]["EUR_USD"] = {
        "market": "EUR_USD",
    }

    report = build_broker_backed_preflight(
        token="secret-token",
        account_id=ACCOUNT_ID,
        runtime_state=state,
        client_factory=client_factory(
            snapshot(
                positions=(
                    {
                        "instrument": ("EUR_USD"),
                    },
                )
            )
        ),
    )

    assert (
        check_by_name(
            report,
            "position_reconciliation",
        ).passed
        is True
    )


def test_insufficient_margin_fails():
    report = build_broker_backed_preflight(
        token="secret-token",
        account_id=ACCOUNT_ID,
        runtime_state=(empty_runtime_state()),
        minimum_margin_available=5000.0,
        client_factory=client_factory(snapshot(margin_available=4999.99)),
    )

    assert report.passed is False

    assert (
        check_by_name(
            report,
            "minimum_margin_available",
        ).passed
        is False
    )


def test_pending_broker_orders_fail():
    report = build_broker_backed_preflight(
        token="secret-token",
        account_id=ACCOUNT_ID,
        runtime_state=(empty_runtime_state()),
        client_factory=client_factory(snapshot(orders=({"id": "100"},))),
    )

    assert report.passed is False

    assert (
        check_by_name(
            report,
            "zero_pending_broker_orders",
        ).passed
        is False
    )


def test_non_practice_source_fails():
    changed_snapshot = replace(
        snapshot(),
        source="OANDA_LIVE",
    )

    report = build_broker_backed_preflight(
        token="secret-token",
        account_id=ACCOUNT_ID,
        runtime_state=(empty_runtime_state()),
        client_factory=client_factory(changed_snapshot),
    )

    assert report.passed is False

    assert (
        check_by_name(
            report,
            "practice_source",
        ).passed
        is False
    )


def test_non_read_only_snapshot_fails():
    changed_snapshot = replace(
        snapshot(),
        read_only=False,
    )

    report = build_broker_backed_preflight(
        token="secret-token",
        account_id=ACCOUNT_ID,
        runtime_state=(empty_runtime_state()),
        client_factory=client_factory(changed_snapshot),
    )

    assert report.passed is False

    assert (
        check_by_name(
            report,
            "read_only_client",
        ).passed
        is False
    )


def test_broker_error_becomes_failed_report():
    class FailingClient:
        def get_account_snapshot(self):
            raise ValueError("test broker failure")

    def failing_factory(
        *,
        token,
        account_id,
    ):
        return FailingClient()

    report = build_broker_backed_preflight(
        token="secret-token",
        account_id=ACCOUNT_ID,
        runtime_state=(empty_runtime_state()),
        client_factory=failing_factory,
    )

    assert report.passed is False
    assert len(report.checks) == 1
    assert report.checks[0].name == "broker_snapshot"

    assert "secret-token" not in (report.checks[0].message)


def test_negative_minimum_margin_rejected():
    with pytest.raises(
        ValueError,
        match="cannot be negative",
    ):
        build_broker_backed_preflight(
            token="secret-token",
            account_id=ACCOUNT_ID,
            runtime_state=(empty_runtime_state()),
            minimum_margin_available=-1.0,
        )
