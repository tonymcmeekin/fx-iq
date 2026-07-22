import json
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError

import pytest

from app.broker import (
    LIVE_CANARY_BUILD_ENABLED,
    BrokerDirection,
    CanaryEnvironment,
    CanaryGatewayError,
    CanaryRehearsalRequest,
    OandaCanaryGateway,
)

ACCOUNT_ID = "999-001-12345678-001"
NOW = datetime(2026, 7, 22, 12, tzinfo=UTC)


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self._body


class RecordingOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, *, timeout):
        self.requests.append(request)
        response = self.responses.pop(0)
        if response == "NOT_FOUND":
            raise HTTPError(request.full_url, 404, "not found", {}, None)
        if response == "CONNECTION_LOST":
            raise URLError("connection lost")
        return FakeResponse(response)


def request():
    return CanaryRehearsalRequest(
        rehearsal_id="practice-rehearsal-001",
        instrument="EUR_USD",
        direction=BrokerDirection.BUY,
        stop_loss=1.09,
        take_profit=1.12,
    )


def complete_responses():
    return [
        {"account": {"trades": [], "orders": []}},
        "NOT_FOUND",
        {
            "prices": [
                {
                    "instrument": "EUR_USD",
                    "status": "tradeable",
                    "closeoutAsk": "1.10020",
                    "closeoutBid": "1.10000",
                    "time": "2026-07-22T12:00:00.000000000Z",
                }
            ]
        },
        {
            "orderFillTransaction": {
                "id": "101",
                "tradeOpened": {"tradeID": "202"},
            }
        },
        {
            "trade": {
                "id": "202",
                "state": "OPEN",
                "instrument": "EUR_USD",
                "stopLossOrder": {"id": "203"},
                "takeProfitOrder": {"id": "204"},
            }
        },
        {"orderFillTransaction": {"id": "205"}},
        {"trades": []},
    ]


def test_practice_canary_rehearses_full_lifecycle():
    opener = RecordingOpener(complete_responses())
    result = OandaCanaryGateway(
        token="practice-token",
        account_id=ACCOUNT_ID,
        opener=opener,
    ).rehearse(request(), now_utc=NOW)

    assert result.status == "PRACTICE_REHEARSAL_COMPLETE"
    assert result.network_calls_made == 7
    assert result.practice_entry_orders_submitted == 1
    assert result.practice_close_orders_submitted == 1
    assert result.live_orders_submitted == 0
    assert result.position_verified_open is True
    assert result.position_verified_closed is True
    assert LIVE_CANARY_BUILD_ENABLED is False
    assert [item.get_method() for item in opener.requests] == [
        "GET",
        "GET",
        "GET",
        "POST",
        "GET",
        "PUT",
        "GET",
    ]
    assert all("api-fxpractice.oanda.com" in item.full_url for item in opener.requests)
    order_body = json.loads(opener.requests[3].data)
    assert order_body["order"]["units"] == "1"
    assert order_body["order"]["stopLossOnFill"]["price"] == "1.09"
    assert order_body["order"]["takeProfitOnFill"]["price"] == "1.12"
    assert json.loads(opener.requests[5].data) == {"units": "ALL"}


def test_live_canary_is_build_locked_before_network_access():
    opener = RecordingOpener([])
    with pytest.raises(CanaryGatewayError, match="build-locked"):
        OandaCanaryGateway(
            token="live-token",
            account_id=ACCOUNT_ID,
            environment=CanaryEnvironment.LIVE,
            opener=opener,
        )
    assert opener.requests == []


def test_canary_requires_empty_practice_account():
    opener = RecordingOpener([{"account": {"trades": [{"id": "existing"}], "orders": []}}])
    gateway = OandaCanaryGateway(
        token="practice-token",
        account_id=ACCOUNT_ID,
        opener=opener,
    )
    with pytest.raises(CanaryGatewayError, match="no open trades"):
        gateway.rehearse(request(), now_utc=NOW)
    assert len(opener.requests) == 1


def test_canary_duplicate_id_is_rejected_before_pricing_or_submission():
    opener = RecordingOpener(
        [
            {"account": {"trades": [], "orders": []}},
            {"order": {"id": "existing"}},
        ]
    )
    gateway = OandaCanaryGateway(
        token="practice-token",
        account_id=ACCOUNT_ID,
        opener=opener,
    )
    with pytest.raises(CanaryGatewayError, match="duplicate order"):
        gateway.rehearse(request(), now_utc=NOW)
    assert len(opener.requests) == 2


def test_canary_rejects_stale_quote_before_submission():
    responses = complete_responses()[:3]
    responses[2]["prices"][0]["time"] = "2026-07-22T11:59:00Z"
    opener = RecordingOpener(responses)
    gateway = OandaCanaryGateway(
        token="practice-token",
        account_id=ACCOUNT_ID,
        opener=opener,
    )
    with pytest.raises(CanaryGatewayError, match="stale"):
        gateway.rehearse(request(), now_utc=NOW)
    assert all(item.get_method() == "GET" for item in opener.requests)


def test_post_fill_validation_failure_submits_emergency_close():
    responses = complete_responses()[:4]
    responses.extend(
        [
            {
                "trade": {
                    "id": "202",
                    "state": "OPEN",
                    "instrument": "EUR_USD",
                }
            },
            {"orderFillTransaction": {"id": "emergency-close"}},
        ]
    )
    opener = RecordingOpener(responses)
    gateway = OandaCanaryGateway(
        token="practice-token",
        account_id=ACCOUNT_ID,
        opener=opener,
    )
    with pytest.raises(CanaryGatewayError, match="Emergency close was submitted"):
        gateway.rehearse(request(), now_utc=NOW)
    assert opener.requests[-1].get_method() == "PUT"
    assert json.loads(opener.requests[-1].data) == {"units": "ALL"}


def test_invalid_order_is_rejected_before_network_access():
    opener = RecordingOpener([])
    invalid = CanaryRehearsalRequest(
        rehearsal_id="invalid-local-request",
        instrument="eurusd",
        direction=BrokerDirection.BUY,
        stop_loss=1.09,
        take_profit=1.12,
    )
    gateway = OandaCanaryGateway(
        token="practice-token",
        account_id=ACCOUNT_ID,
        opener=opener,
    )
    with pytest.raises(CanaryGatewayError, match="OANDA format"):
        gateway.rehearse(invalid, now_utc=NOW)
    assert opener.requests == []


def test_lost_entry_response_recovers_by_client_id_without_duplicate_post():
    responses = complete_responses()[:3]
    responses.extend(
        [
            "CONNECTION_LOST",
            {
                "order": {
                    "state": "FILLED",
                    "fillingTransactionID": "101",
                    "tradeOpenedID": "202",
                }
            },
            complete_responses()[4],
            complete_responses()[5],
            complete_responses()[6],
        ]
    )
    opener = RecordingOpener(responses)
    result = OandaCanaryGateway(
        token="practice-token",
        account_id=ACCOUNT_ID,
        opener=opener,
    ).rehearse(request(), now_utc=NOW)

    assert result.position_verified_closed is True
    assert [item.get_method() for item in opener.requests].count("POST") == 1
    assert "/orders/@canary_" in opener.requests[4].full_url
