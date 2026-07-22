import json

import pytest

from app.broker import (
    OandaPracticeReadOnlyClient,
    OandaReadOnlyError,
    reconcile_open_positions,
)

ACCOUNT_ID = "999-001-12345678-001"


class FakeResponse:
    def __init__(
        self,
        payload,
    ):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self._body


class RecordingOpener:
    def __init__(
        self,
        responses,
    ):
        self.responses = list(responses)
        self.requests = []
        self.timeouts = []

    def __call__(
        self,
        request,
        *,
        timeout,
    ):
        self.requests.append(request)
        self.timeouts.append(timeout)

        return FakeResponse(
            self.responses.pop(0)
        )


def account_list_payload(
    *account_ids,
):
    return {
        "accounts": [
            {"id": account_id}
            for account_id in account_ids
        ]
    }


def account_payload(
    *,
    account_id=ACCOUNT_ID,
    positions=None,
    trades=None,
    orders=None,
):
    return {
        "account": {
            "id": account_id,
            "currency": "GBP",
            "balance": "10000.00",
            "NAV": "10025.50",
            "marginUsed": "125.25",
            "marginAvailable": "9900.25",
            "trades": trades or [],
            "positions": positions or [],
            "orders": orders or [],
        },
        "lastTransactionID": "42",
    }


def test_lists_accessible_accounts_using_get():
    opener = RecordingOpener(
        [
            account_list_payload(
                ACCOUNT_ID,
                "999-001-87654321-001",
            )
        ]
    )

    client = OandaPracticeReadOnlyClient(
        token="practice-token",
        opener=opener,
    )

    result = client.list_account_ids()

    assert result == (
        ACCOUNT_ID,
        "999-001-87654321-001",
    )

    request = opener.requests[0]

    assert request.get_method() == "GET"
    assert (
        request.full_url
        == "https://api-fxpractice.oanda.com/v3/accounts"
    )
    assert (
        request.get_header("Authorization")
        == "Bearer practice-token"
    )


def test_account_snapshot_uses_get_only():
    opener = RecordingOpener(
        [
            account_payload(
                positions=[
                    {"instrument": "EUR_USD"},
                ],
                trades=[
                    {"id": "10"},
                ],
                orders=[
                    {"id": "11"},
                ],
            )
        ]
    )

    client = OandaPracticeReadOnlyClient(
        token="practice-token",
        account_id=ACCOUNT_ID,
        opener=opener,
    )

    snapshot = client.get_account_snapshot()

    assert len(opener.requests) == 1

    request = opener.requests[0]

    assert request.get_method() == "GET"
    assert request.data is None
    assert (
        request.full_url
        == (
            "https://api-fxpractice.oanda.com"
            f"/v3/accounts/{ACCOUNT_ID}"
        )
    )

    assert snapshot.account_id == ACCOUNT_ID
    assert snapshot.currency == "GBP"
    assert snapshot.balance == 10000.0
    assert snapshot.nav == 10025.5
    assert snapshot.margin_used == 125.25
    assert snapshot.margin_available == 9900.25
    assert snapshot.open_trade_count == 1
    assert snapshot.open_position_count == 1
    assert snapshot.pending_order_count == 1
    assert snapshot.last_transaction_id == "42"
    assert snapshot.network_calls_made == 1
    assert snapshot.broker_orders_submitted == 0
    assert snapshot.paper_trading_only is True
    assert snapshot.live_trading_allowed is False
    assert snapshot.read_only is True


def test_single_account_can_be_resolved_automatically():
    opener = RecordingOpener(
        [
            account_list_payload(ACCOUNT_ID),
            account_payload(),
        ]
    )

    snapshot = OandaPracticeReadOnlyClient(
        token="practice-token",
        opener=opener,
    ).get_account_snapshot()

    assert snapshot.account_id == ACCOUNT_ID
    assert len(opener.requests) == 2
    assert all(
        request.get_method() == "GET"
        for request in opener.requests
    )


def test_multiple_accounts_require_explicit_selection():
    opener = RecordingOpener(
        [
            account_list_payload(
                ACCOUNT_ID,
                "999-001-87654321-001",
            )
        ]
    )

    client = OandaPracticeReadOnlyClient(
        token="practice-token",
        opener=opener,
    )

    with pytest.raises(
        OandaReadOnlyError,
        match="Multiple OANDA Practice accounts",
    ):
        client.get_account_snapshot()


def test_response_account_must_match_request():
    opener = RecordingOpener(
        [
            account_payload(
                account_id="different-account",
            )
        ]
    )

    client = OandaPracticeReadOnlyClient(
        token="practice-token",
        account_id=ACCOUNT_ID,
        opener=opener,
    )

    with pytest.raises(
        OandaReadOnlyError,
        match="does not match",
    ):
        client.get_account_snapshot()


def test_reconciliation_detects_matching_positions():
    snapshot = OandaPracticeReadOnlyClient(
        token="practice-token",
        account_id=ACCOUNT_ID,
        opener=RecordingOpener(
            [
                account_payload(
                    positions=[
                        {
                            "instrument": "EUR_USD",
                        },
                        {
                            "instrument": "GBP_JPY",
                        },
                    ]
                )
            ]
        ),
    ).get_account_snapshot()

    report = reconcile_open_positions(
        internal_open_markets={
            "EUR_USD",
            "GBP_JPY",
        },
        snapshot=snapshot,
    )

    assert report.is_reconciled is True
    assert report.missing_at_broker == ()
    assert report.unexpected_at_broker == ()
    assert report.network_calls_made == 1
    assert report.broker_orders_submitted == 0
    assert report.paper_trading_only is True
    assert report.live_trading_allowed is False


def test_reconciliation_detects_divergence():
    snapshot = OandaPracticeReadOnlyClient(
        token="practice-token",
        account_id=ACCOUNT_ID,
        opener=RecordingOpener(
            [
                account_payload(
                    positions=[
                        {
                            "instrument": "USD_JPY",
                        }
                    ]
                )
            ]
        ),
    ).get_account_snapshot()

    report = reconcile_open_positions(
        internal_open_markets={
            "EUR_USD",
        },
        snapshot=snapshot,
    )

    assert report.is_reconciled is False
    assert report.missing_at_broker == (
        "EUR_USD",
    )
    assert report.unexpected_at_broker == (
        "USD_JPY",
    )
