"""Tests for the strategy attribution report CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.paper_trading.ledger import append_event
from scripts import report_strategy_attribution as report


def candidate_trade(
    *,
    strategy_name: str = "atr_breakout",
    market: str = "EUR_GBP",
    account_return_percent: float = 0.75,
) -> dict:
    return {
        "strategy_name": strategy_name,
        "market": market,
        "direction": "BUY",
        "exit_reason": "Take-profit hit.",
        "account_return_percent": (account_return_percent),
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
            "candidate_trade": (candidate_trade()),
            "shadow_trade": {
                **candidate_trade(),
                "account_return_percent": 99.0,
            },
            "broker_orders_submitted": 0,
        },
        event_id="close-1",
        occurred_at_utc=("2026-07-17T08:00:00Z"),
    )


@pytest.fixture
def ledger_path(
    tmp_path,
    monkeypatch,
) -> Path:
    path = tmp_path / "paper_ledger" / "events.jsonl"

    monkeypatch.setattr(
        report,
        "LEDGER_PATH",
        path,
    )

    return path


def test_empty_verified_ledger_returns_valid_report(
    ledger_path,
):
    result = report.perform_report()

    assert result["completed_trade_count"] == 0
    assert result["supported_close_event_count"] == 0
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False


def test_report_uses_configured_ledger(
    ledger_path,
):
    append_close_event(
        ledger_path,
    )

    result = report.perform_report()

    assert result["completed_trade_count"] == 1
    assert result["overall"]["net_profit_percent"] == 0.75
    assert result["by_strategy"][0]["strategy"] == "atr_breakout"


def test_execute_prints_report(
    ledger_path,
    capsys,
):
    append_close_event(
        ledger_path,
    )

    result = report.execute([])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert result == 0
    assert captured.err == ""
    assert payload["supported_close_event_count"] == 1
    assert payload["ledger_writes_performed"] == 0


def test_compact_output_is_valid_json(
    ledger_path,
    capsys,
):
    result = report.execute(["--compact"])

    captured = capsys.readouterr()

    assert result == 0
    assert "\n" not in captured.out.strip()
    assert json.loads(captured.out)["completed_trade_count"] == 0


def test_execute_does_not_modify_ledger(
    ledger_path,
):
    append_close_event(
        ledger_path,
    )

    before = ledger_path.read_bytes()

    result = report.execute([])

    after = ledger_path.read_bytes()

    assert result == 0
    assert after == before


def test_tampered_ledger_returns_error(
    ledger_path,
    capsys,
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

    result = report.execute([])

    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert result == 1
    assert captured.out == ""
    assert payload["status"] == "ERROR"
    assert "Ledger integrity check failed" in payload["error"]
    assert payload["ledger_writes_performed"] == 0
    assert payload["broker_orders_submitted"] == 0


def test_unknown_argument_is_rejected(
    ledger_path,
):
    with pytest.raises(
        SystemExit,
    ) as error:
        report.execute(["--ledger-path", "other.jsonl"])

    assert error.value.code == 2
