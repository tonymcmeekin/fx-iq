import json
from pathlib import Path

import pytest

from app.paper_trading.ledger import append_event
from app.paper_trading.runtime_state import (
    empty_runtime_state,
    write_runtime_state,
)
from scripts import (
    report_prospective_paper_performance as report,
)


def paths(
    tmp_path: Path,
) -> tuple[Path, Path]:
    return (
        tmp_path / "events.jsonl",
        tmp_path / "state.json",
    )


def write_state(
    state_path: Path,
    *,
    candidate_balance: float = 10000.0,
    shadow_balance: float = 10000.0,
) -> None:
    state = empty_runtime_state()

    state["candidate_balance"] = candidate_balance

    state["shadow_balance"] = shadow_balance

    state["candidate_peak_equity"] = max(
        10000.0,
        candidate_balance,
    )

    state["shadow_peak_equity"] = max(
        10000.0,
        shadow_balance,
    )

    write_runtime_state(
        state_path,
        state,
    )


def add_event(
    ledger_path: Path,
    event_type: str,
    payload: dict,
    *,
    number: int,
) -> None:
    append_event(
        ledger_path,
        event_type,
        payload,
        event_id=f"event-{number}",
        occurred_at_utc=(f"2026-07-{number:02d}T08:00:00Z"),
    )


def test_empty_ledger_returns_insufficient_data(
    tmp_path,
):
    ledger_path, state_path = paths(tmp_path)

    write_state(state_path)

    result = report.build_performance_report(
        ledger_path=ledger_path,
        state_path=state_path,
    )

    assert result["status"] == ("INSUFFICIENT_DATA")

    assert result["ledger_events"] == 0
    assert result["completed_sessions"] == 0
    assert result["signals_evaluated"] == 0
    assert result["positions_closed"] == 0
    assert result["broker_orders_sent"] == 0


def test_hold_only_session_is_reported(
    tmp_path,
):
    ledger_path, state_path = paths(tmp_path)

    write_state(state_path)

    add_event(
        ledger_path,
        "SESSION_STARTED",
        {
            "session_date": "2026-07-17",
            "broker_orders_sent": 0,
        },
        number=1,
    )

    add_event(
        ledger_path,
        "SIGNAL_EVALUATED",
        {
            "session_date": "2026-07-17",
            "market": "EUR_GBP",
            "direction": "HOLD",
        },
        number=2,
    )

    add_event(
        ledger_path,
        "SESSION_COMPLETED",
        {
            "session_date": "2026-07-17",
            "broker_orders_sent": 0,
        },
        number=3,
    )

    result = report.build_performance_report(
        ledger_path=ledger_path,
        state_path=state_path,
    )

    assert result["completed_sessions"] == 1
    assert result["markets_observed"] == 1
    assert result["signals_evaluated"] == 1
    assert result["hold_signals"] == 1
    assert result["actionable_signals"] == 0
    assert result["positions_opened"] == 0
    assert result["positions_closed"] == 0


def test_actionable_signals_are_counted(
    tmp_path,
):
    ledger_path, state_path = paths(tmp_path)

    write_state(state_path)

    add_event(
        ledger_path,
        "SIGNAL_EVALUATED",
        {
            "market": "EUR_GBP",
            "direction": "BUY",
        },
        number=1,
    )

    add_event(
        ledger_path,
        "SIGNAL_EVALUATED",
        {
            "market": "AUD_CAD",
            "direction": "SELL",
        },
        number=2,
    )

    result = report.build_performance_report(
        ledger_path=ledger_path,
        state_path=state_path,
    )

    assert result["buy_signals"] == 1
    assert result["sell_signals"] == 1
    assert result["actionable_signals"] == 2
    assert result["markets"] == [
        "AUD_CAD",
        "EUR_GBP",
    ]


def test_position_events_and_balances_are_reported(
    tmp_path,
):
    ledger_path, state_path = paths(tmp_path)

    write_state(
        state_path,
        candidate_balance=10150.0,
        shadow_balance=10075.0,
    )

    add_event(
        ledger_path,
        "PAPER_POSITION_OPENED",
        {
            "market": "EUR_GBP",
            "status": "FILLED",
            "broker_orders_submitted": 0,
        },
        number=1,
    )

    add_event(
        ledger_path,
        "PAPER_POSITION_MARKED",
        {
            "market": "EUR_GBP",
            "status": "OPEN",
            "broker_orders_submitted": 0,
        },
        number=2,
    )

    add_event(
        ledger_path,
        "PAPER_POSITION_CLOSED",
        {
            "market": "EUR_GBP",
            "status": "CLOSED",
            "candidate_realized_pnl": 150.0,
            "shadow_realized_pnl": 75.0,
            "broker_orders_submitted": 0,
        },
        number=3,
    )

    result = report.build_performance_report(
        ledger_path=ledger_path,
        state_path=state_path,
    )

    assert result["positions_opened"] == 1
    assert result["position_marks"] == 1
    assert result["positions_closed"] == 1

    assert result["candidate_return_percent"] == 1.5

    assert result["shadow_return_percent"] == 0.75

    assert result["candidate_realized_pnl"] == 150.0

    assert result["shadow_realized_pnl"] == 75.0


def test_missing_realized_pnl_is_not_invented(
    tmp_path,
):
    ledger_path, state_path = paths(tmp_path)

    write_state(state_path)

    add_event(
        ledger_path,
        "PAPER_POSITION_CLOSED",
        {
            "market": "EUR_GBP",
            "status": "CLOSED",
            "broker_orders_submitted": 0,
        },
        number=1,
    )

    result = report.build_performance_report(
        ledger_path=ledger_path,
        state_path=state_path,
    )

    assert result["candidate_realized_pnl_available"] is False

    assert result["candidate_realized_pnl"] is None

    assert result["shadow_realized_pnl_available"] is False

    assert result["shadow_realized_pnl"] is None


def test_duplicate_completed_dates_are_reported(
    tmp_path,
):
    ledger_path, state_path = paths(tmp_path)

    write_state(state_path)

    for number in (1, 2):
        add_event(
            ledger_path,
            "SESSION_COMPLETED",
            {
                "session_date": "2026-07-17",
                "broker_orders_sent": 0,
            },
            number=number,
        )

    result = report.build_performance_report(
        ledger_path=ledger_path,
        state_path=state_path,
    )

    assert result["duplicate_completed_session_dates"] == ["2026-07-17"]


def test_broker_orders_are_rejected(
    tmp_path,
):
    ledger_path, state_path = paths(tmp_path)

    write_state(state_path)

    add_event(
        ledger_path,
        "SESSION_COMPLETED",
        {
            "session_date": "2026-07-17",
            "broker_orders_sent": 1,
        },
        number=1,
    )

    with pytest.raises(
        report.PerformanceReportError,
        match="broker orders",
    ):
        report.build_performance_report(
            ledger_path=ledger_path,
            state_path=state_path,
        )


def test_report_does_not_modify_runtime_files(
    tmp_path,
):
    ledger_path, state_path = paths(tmp_path)

    write_state(state_path)

    add_event(
        ledger_path,
        "SESSION_COMPLETED",
        {
            "session_date": "2026-07-17",
            "broker_orders_sent": 0,
        },
        number=1,
    )

    ledger_before = ledger_path.read_bytes()

    state_before = state_path.read_bytes()

    report.build_performance_report(
        ledger_path=ledger_path,
        state_path=state_path,
    )

    assert ledger_path.read_bytes() == ledger_before

    assert state_path.read_bytes() == state_before


def test_real_report_output_is_json_serializable(
    tmp_path,
):
    ledger_path, state_path = paths(tmp_path)

    write_state(state_path)

    result = report.build_performance_report(
        ledger_path=ledger_path,
        state_path=state_path,
    )

    encoded = json.dumps(
        result,
        sort_keys=True,
    )

    assert "INSUFFICIENT_DATA" in encoded
