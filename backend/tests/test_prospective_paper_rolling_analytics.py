import json
from pathlib import Path

import pytest

from app.paper_trading.ledger import (
    append_event,
)
from app.paper_trading.runtime_state import (
    empty_runtime_state,
    write_runtime_state,
)
from scripts import (
    report_prospective_paper_rolling_analytics as rolling,
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


def test_empty_report_is_insufficient(
    tmp_path,
):
    ledger_path, state_path = paths(tmp_path)

    write_state(state_path)

    result = rolling.build_rolling_analytics_report(
        ledger_path=ledger_path,
        state_path=state_path,
    )

    assert result["status"] == ("INSUFFICIENT_DATA")

    assert result["session_equity_curve"] == []

    assert result["candidate_max_drawdown_percent"] == 0.0


def test_session_equity_curve_and_returns(
    tmp_path,
):
    ledger_path, state_path = paths(tmp_path)

    write_state(
        state_path,
        candidate_balance=10098.0,
        shadow_balance=10049.5,
    )

    add_event(
        ledger_path,
        "SESSION_COMPLETED",
        {
            "session_date": "2026-07-17",
            "candidate_balance": 10100.0,
            "shadow_balance": 10050.0,
            "broker_orders_sent": 0,
        },
        number=1,
    )

    add_event(
        ledger_path,
        "SESSION_COMPLETED",
        {
            "session_date": "2026-07-18",
            "candidate_balance": 10098.0,
            "shadow_balance": 10049.5,
            "broker_orders_sent": 0,
        },
        number=2,
    )

    result = rolling.build_rolling_analytics_report(
        ledger_path=ledger_path,
        state_path=state_path,
    )

    curve = result["session_equity_curve"]

    assert len(curve) == 2

    assert curve[0]["candidate_session_return_percent"] == 1.0

    assert curve[1]["candidate_session_return_percent"] < 0

    assert result["profitable_sessions"] == 1

    assert result["losing_sessions"] == 1


def test_maximum_drawdown_is_calculated():
    result = rolling.maximum_drawdown_percent(
        [
            10000.0,
            11000.0,
            9900.0,
            10500.0,
        ]
    )

    assert result == 10.0


def test_trade_analytics_use_real_close_payload(
    tmp_path,
):
    ledger_path, state_path = paths(tmp_path)

    write_state(
        state_path,
        candidate_balance=10100.0,
        shadow_balance=10050.0,
    )

    add_event(
        ledger_path,
        "PAPER_POSITION_CLOSED",
        {
            "market": "EUR_GBP",
            "status": "CLOSED",
            "candidate_net_pnl": 150.0,
            "shadow_net_pnl": 75.0,
            "candidate_trade": {
                "account_return_percent": 1.5,
            },
            "broker_orders_submitted": 0,
        },
        number=1,
    )

    add_event(
        ledger_path,
        "PAPER_POSITION_CLOSED",
        {
            "market": "AUD_CAD",
            "status": "CLOSED",
            "candidate_net_pnl": -50.0,
            "shadow_net_pnl": -25.0,
            "candidate_trade": {
                "account_return_percent": -0.5,
            },
            "broker_orders_submitted": 0,
        },
        number=2,
    )

    result = rolling.build_rolling_analytics_report(
        ledger_path=ledger_path,
        state_path=state_path,
    )

    assert result["candidate_winning_trades"] == 1

    assert result["candidate_losing_trades"] == 1

    assert result["candidate_win_rate_percent"] == 50.0

    assert result["candidate_expectancy_amount"] == 50.0

    assert result["candidate_profit_factor"] == 3.0


def test_per_market_statistics(
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
        "PAPER_POSITION_OPENED",
        {
            "market": "EUR_GBP",
            "status": "FILLED",
            "broker_orders_submitted": 0,
        },
        number=2,
    )

    add_event(
        ledger_path,
        "PAPER_POSITION_CLOSED",
        {
            "market": "EUR_GBP",
            "candidate_net_pnl": 25.0,
            "shadow_net_pnl": 20.0,
            "broker_orders_submitted": 0,
        },
        number=3,
    )

    result = rolling.build_rolling_analytics_report(
        ledger_path=ledger_path,
        state_path=state_path,
    )

    market = result["per_market"]["EUR_GBP"]

    assert market["signals"] == 1
    assert market["buy_signals"] == 1
    assert market["positions_opened"] == 1
    assert market["positions_closed"] == 1
    assert market["candidate_net_pnl"] == 25.0
    assert market["winning_trades"] == 1


def test_missing_trade_pnl_is_not_invented(
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

    result = rolling.build_rolling_analytics_report(
        ledger_path=ledger_path,
        state_path=state_path,
    )

    assert result["candidate_trade_pnl_available"] is False

    assert result["candidate_expectancy_amount"] is None

    assert result["candidate_win_rate_percent"] is None


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
        rolling.RollingAnalyticsError,
        match="broker orders",
    ):
        rolling.build_rolling_analytics_report(
            ledger_path=ledger_path,
            state_path=state_path,
        )


def test_report_is_read_only_and_json_serializable(
    tmp_path,
):
    ledger_path, state_path = paths(tmp_path)

    write_state(state_path)

    add_event(
        ledger_path,
        "SESSION_COMPLETED",
        {
            "session_date": "2026-07-17",
            "candidate_balance": 10000.0,
            "shadow_balance": 10000.0,
            "broker_orders_sent": 0,
        },
        number=1,
    )

    ledger_before = ledger_path.read_bytes()

    state_before = state_path.read_bytes()

    result = rolling.build_rolling_analytics_report(
        ledger_path=ledger_path,
        state_path=state_path,
    )

    encoded = json.dumps(
        result,
        sort_keys=True,
    )

    assert "INSUFFICIENT_DATA" in encoded

    assert ledger_path.read_bytes() == ledger_before

    assert state_path.read_bytes() == state_before
