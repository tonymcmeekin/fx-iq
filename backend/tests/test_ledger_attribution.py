"""Tests for verified-ledger performance attribution."""

from __future__ import annotations

import json

import pytest

from app.analytics.ledger_attribution import (
    LedgerAttributionError,
    attribution_trade_from_close_event,
    attribution_trades_from_verified_events,
    build_ledger_attribution_report,
)
from app.paper_trading.ledger import (
    LedgerIntegrityError,
    append_event,
    read_events,
)


def candidate_trade(
    *,
    strategy_name: str = "atr_breakout",
    market: str = "EUR_GBP",
    direction: str = "BUY",
    exit_reason: str = "Take-profit hit.",
    account_return_percent: float = 0.75,
    candles_held: int = 4,
) -> dict:
    return {
        "strategy_name": strategy_name,
        "market": market,
        "direction": direction,
        "exit_reason": exit_reason,
        "account_return_percent": (account_return_percent),
        "candles_held": candles_held,
    }


def close_event(
    *,
    trade: dict | None = None,
    market: str = "EUR_GBP",
) -> dict:
    return {
        "event_type": "PAPER_POSITION_CLOSED",
        "payload": {
            "status": "CLOSED",
            "market": market,
            "candidate_trade": (candidate_trade() if trade is None else trade),
            "shadow_trade": {
                **candidate_trade(),
                "account_return_percent": 99.0,
            },
            "broker_orders_submitted": 0,
        },
    }


def test_converts_candidate_close_event():
    result = attribution_trade_from_close_event(
        close_event(),
    )

    assert result.strategy == "atr_breakout"
    assert result.symbol == "EUR_GBP"
    assert result.direction == "BUY"
    assert result.profit_percent == 0.75
    assert result.candles_held == 4


def test_uses_candidate_not_shadow_return():
    result = attribution_trade_from_close_event(
        close_event(),
    )

    assert result.profit_percent == 0.75
    assert result.profit_percent != 99.0


def test_accepts_strategy_and_symbol_aliases():
    trade = candidate_trade()
    trade["strategy"] = trade.pop("strategy_name")
    trade["symbol"] = trade.pop("market")

    result = attribution_trade_from_close_event(
        close_event(
            trade=trade,
        )
    )

    assert result.strategy == "atr_breakout"
    assert result.symbol == "EUR_GBP"


def test_uses_payload_market_when_trade_market_missing():
    trade = candidate_trade()
    trade.pop("market")

    result = attribution_trade_from_close_event(
        close_event(
            trade=trade,
            market="GBP_USD",
        )
    )

    assert result.symbol == "GBP_USD"


def test_rejects_non_close_event():
    with pytest.raises(
        LedgerAttributionError,
        match="not a PAPER_POSITION_CLOSED",
    ):
        attribution_trade_from_close_event(
            {
                "event_type": "SESSION_STARTED",
                "payload": {},
            }
        )


def test_rejects_missing_candidate_trade():
    with pytest.raises(
        LedgerAttributionError,
        match="candidate_trade",
    ):
        attribution_trade_from_close_event(
            {
                "event_type": ("PAPER_POSITION_CLOSED"),
                "payload": {},
            }
        )


def test_rejects_missing_holding_period():
    trade = candidate_trade()
    trade.pop("candles_held")

    with pytest.raises(
        LedgerAttributionError,
        match="holding period",
    ):
        attribution_trade_from_close_event(
            close_event(
                trade=trade,
            )
        )


def test_ignores_non_close_events_and_preserves_order():
    first = close_event(
        trade=candidate_trade(
            strategy_name="first",
        )
    )
    second = close_event(
        trade=candidate_trade(
            strategy_name="second",
        )
    )

    result = attribution_trades_from_verified_events(
        [
            {
                "event_type": "SESSION_STARTED",
                "payload": {},
            },
            first,
            {
                "event_type": "SIGNAL_EVALUATED",
                "payload": {},
            },
            second,
        ]
    )

    assert [trade.strategy for trade in result] == [
        "first",
        "second",
    ]


def test_missing_ledger_builds_empty_report(
    tmp_path,
):
    ledger_path = tmp_path / "events.jsonl"

    report = build_ledger_attribution_report(
        ledger_path,
    )

    assert report["completed_trade_count"] == 0
    assert report["verified_ledger_event_count"] == 0
    assert report["supported_close_event_count"] == 0
    assert report["ledger_writes_performed"] == 0
    assert report["broker_orders_submitted"] == 0


def test_builds_report_from_verified_ledger(
    tmp_path,
):
    ledger_path = tmp_path / "events.jsonl"

    append_event(
        ledger_path,
        "SESSION_STARTED",
        {
            "session_date": "2026-07-17",
        },
        event_id="start",
    )

    append_event(
        ledger_path,
        "PAPER_POSITION_CLOSED",
        close_event()["payload"],
        event_id="close-1",
    )

    append_event(
        ledger_path,
        "SESSION_COMPLETED",
        {
            "status": "SUCCESS",
        },
        event_id="complete",
    )

    report = build_ledger_attribution_report(
        ledger_path,
    )

    assert report["completed_trade_count"] == 1
    assert report["verified_ledger_event_count"] == 3
    assert report["supported_close_event_count"] == 1
    assert report["overall"]["net_profit_percent"] == 0.75
    assert report["by_strategy"][0]["strategy"] == ("atr_breakout")
    assert report["safe_for_live_trading"] is False
    assert report["protocol_live_trading_permitted"] is False


def test_tampered_ledger_is_rejected_before_attribution(
    tmp_path,
):
    ledger_path = tmp_path / "events.jsonl"

    append_event(
        ledger_path,
        "PAPER_POSITION_CLOSED",
        close_event()["payload"],
        event_id="close-1",
    )

    events = read_events(
        ledger_path,
    )

    events[0]["payload"]["candidate_trade"]["account_return_percent"] = 500.0

    ledger_path.write_text(
        json.dumps(events[0]) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        LedgerIntegrityError,
        match="Event hash mismatch",
    ):
        build_ledger_attribution_report(
            ledger_path,
        )


def test_report_generation_does_not_modify_ledger(
    tmp_path,
):
    ledger_path = tmp_path / "events.jsonl"

    append_event(
        ledger_path,
        "PAPER_POSITION_CLOSED",
        close_event()["payload"],
        event_id="close-1",
    )

    before = ledger_path.read_bytes()

    build_ledger_attribution_report(
        ledger_path,
    )

    after = ledger_path.read_bytes()

    assert after == before
