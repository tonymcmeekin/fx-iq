import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.broker.canary_preflight import (
    CanaryPreflightError,
    CanaryPreflightRequest,
    OandaCanaryReadOnlyPreflight,
)
from app.broker.models import BrokerDirection

ACCOUNT_ID = "999-001-12345678-001"
NOW = datetime(2026, 7, 22, 14, 10, tzinfo=UTC)


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
        return FakeResponse(self.responses.pop(0))


def responses():
    return [
        {
            "account": {
                "currency": "GBP",
                "guaranteedStopLossOrderMode": "ALLOWED",
                "trades": [],
                "orders": [],
            }
        },
        {
            "prices": [
                {
                    "instrument": "EUR_GBP",
                    "status": "tradeable",
                    "bids": [{"price": "0.85265", "liquidity": 1000000}],
                    "asks": [{"price": "0.85277", "liquidity": 1000000}],
                    "time": "2026-07-22T14:10:00.000000000Z",
                }
            ],
            "homeConversions": [
                {
                    "currency": "GBP",
                    "accountGain": "1",
                    "accountLoss": "1",
                    "positionValue": "1",
                }
            ],
        },
        {
            "instruments": [
                {
                    "name": "EUR_GBP",
                    "displayPrecision": 5,
                    "guaranteedStopLossOrderMode": "ALLOWED",
                    "guaranteedStopLossOrderExecutionPremium": "0.0005",
                    "minimumGuaranteedStopLossDistance": "0.0010",
                }
            ]
        },
    ]


def inspect(direction=BrokerDirection.BUY, *, opener=None, sleeper=lambda _: None):
    resolved_opener = opener or RecordingOpener(responses())
    result = OandaCanaryReadOnlyPreflight(
        token="practice-token",
        account_id=ACCOUNT_ID,
        opener=resolved_opener,
        sleeper=sleeper,
    ).inspect(CanaryPreflightRequest(direction=direction), now_utc=NOW)
    return result, resolved_opener


def test_buy_preflight_proposes_exact_gbp_capped_gslo_without_orders():
    result, opener = inspect()

    assert result.status == "PREFLIGHT_PASS"
    assert result.direction == "BUY"
    assert result.proposed_stop_loss == "0.84765"
    assert result.proposed_take_profit == "0.85777"
    assert result.price_bound == "0.8532"
    assert result.stop_loss_risk_gbp == "0.00555"
    assert result.gslo_execution_premium_gbp == "0.0005"
    assert result.worst_case_loss_gbp == "10.00605"
    assert result.remaining_loss_budget_gbp == "39.99395"
    assert result.network_calls_made == 3
    assert result.broker_orders_submitted == 0
    assert result.live_orders_submitted == 0
    assert result.live_execution_locked is True
    assert all(request.get_method() == "GET" for request in opener.requests)
    assert all("api-fxpractice.oanda.com" in request.full_url for request in opener.requests)


def test_sell_preflight_proposes_opposite_protection_prices_without_orders():
    result, opener = inspect(BrokerDirection.SELL)

    assert result.direction == "SELL"
    assert result.proposed_stop_loss == "0.85777"
    assert result.proposed_take_profit == "0.84765"
    assert result.price_bound == "0.85222"
    assert result.worst_case_loss_gbp == "10.00605"
    assert all(request.get_method() == "GET" for request in opener.requests)


def test_preflight_refreshes_a_stale_quote_with_get_only():
    fixture = responses()
    stale = deepcopy(fixture[1])
    stale["prices"][0]["time"] = "2026-07-22T14:09:00Z"
    opener = RecordingOpener([fixture[0], stale, fixture[1], fixture[2]])
    delays = []

    result, _ = inspect(opener=opener, sleeper=delays.append)

    assert result.quote_refresh_attempts == 2
    assert result.network_calls_made == 4
    assert delays == [0.25]
    assert all(request.get_method() == "GET" for request in opener.requests)


def test_preflight_rejects_budget_above_fifty_before_network():
    opener = RecordingOpener([])
    preflight = OandaCanaryReadOnlyPreflight(
        token="practice-token",
        account_id=ACCOUNT_ID,
        opener=opener,
    )

    with pytest.raises(CanaryPreflightError, match="cannot exceed GBP 50"):
        preflight.inspect(
            replace(
                CanaryPreflightRequest(direction=BrokerDirection.BUY),
                maximum_loss_gbp=50.01,
            ),
            now_utc=NOW,
        )

    assert opener.requests == []
