"""Tests for the read-only strategy attribution API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analytics import attribution_reporting
from app.main import app
from app.paper_trading.ledger import append_event

client = TestClient(app)


def candidate_trade() -> dict:
    return {
        "strategy_name": "atr_breakout",
        "market": "EUR_GBP",
        "direction": "BUY",
        "exit_reason": "Take-profit hit.",
        "account_return_percent": 0.75,
        "candles_held": 4,
    }


def append_close_event(
    ledger_path: Path,
) -> None:
    append_event(
        ledger_path,
        "PAPER_POSITION_CLOSED",
        {
            "status": "CLOSED",
            "market": "EUR_GBP",
            "candidate_trade": candidate_trade(),
            "shadow_trade": {
                **candidate_trade(),
                "account_return_percent": 99.0,
            },
            "broker_orders_submitted": 0,
        },
        event_id="close-1",
        occurred_at_utc="2026-07-17T08:00:00Z",
    )


@pytest.fixture
def ledger_path(
    tmp_path,
    monkeypatch,
) -> Path:
    path = tmp_path / "paper_ledger" / "events.jsonl"

    monkeypatch.setattr(
        attribution_reporting,
        "LEDGER_PATH",
        path,
    )

    return path


def test_empty_ledger_returns_valid_report(
    ledger_path,
):
    response = client.get("/analytics/strategy-attribution")

    assert response.status_code == 200

    result = response.json()

    assert result["completed_trade_count"] == 0
    assert result["supported_close_event_count"] == 0
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False


def test_verified_close_event_is_attributed(
    ledger_path,
):
    append_close_event(
        ledger_path,
    )

    response = client.get("/analytics/strategy-attribution")

    assert response.status_code == 200

    result = response.json()

    assert result["completed_trade_count"] == 1
    assert result["supported_close_event_count"] == 1
    assert result["overall"]["net_profit_percent"] == 0.75
    assert result["by_strategy"][0]["strategy"] == "atr_breakout"


def test_endpoint_uses_candidate_not_shadow_result(
    ledger_path,
):
    append_close_event(
        ledger_path,
    )

    response = client.get("/analytics/strategy-attribution")

    result = response.json()

    assert result["overall"]["net_profit_percent"] == 0.75
    assert result["overall"]["net_profit_percent"] != 99.0


def test_endpoint_does_not_modify_ledger(
    ledger_path,
):
    append_close_event(
        ledger_path,
    )

    before = ledger_path.read_bytes()

    response = client.get("/analytics/strategy-attribution")

    after = ledger_path.read_bytes()

    assert response.status_code == 200
    assert after == before


def test_tampered_ledger_returns_conflict(
    ledger_path,
):
    append_close_event(
        ledger_path,
    )

    events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]

    events[0]["payload"]["candidate_trade"]["account_return_percent"] = 500.0

    ledger_path.write_text(
        json.dumps(events[0]) + "\n",
        encoding="utf-8",
    )

    response = client.get("/analytics/strategy-attribution")

    assert response.status_code == 409

    detail = response.json()["detail"]

    assert detail["status"] == "ERROR"
    assert "Ledger integrity check failed" in detail["error"]
    assert detail["ledger_writes_performed"] == 0
    assert detail["broker_orders_submitted"] == 0
    assert detail["safe_for_live_trading"] is False
    assert detail["protocol_live_trading_permitted"] is False


def test_endpoint_accepts_no_ledger_path_parameter(
    ledger_path,
):
    response = client.get(
        "/analytics/strategy-attribution",
        params={
            "ledger_path": "/tmp/other.jsonl",
        },
    )

    assert response.status_code == 200
    assert response.json()["verified_ledger_event_count"] == 0
