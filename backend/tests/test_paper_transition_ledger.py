from datetime import UTC, date, datetime

import pytest

from app.paper_trading.ledger import (
    LedgerIntegrityError,
    verify_ledger,
)
from app.paper_trading.transition_ledger import (
    TransitionLedgerError,
    append_transition_events,
    transition_event_id,
)

SESSION_DATE = date(
    2026,
    7,
    16,
)

OCCURRED_AT = datetime(
    2026,
    7,
    16,
    23,
    15,
    tzinfo=UTC,
)


def position_event(
    event_type=(
        "PAPER_POSITION_OPENED"
    ),
    *,
    timestamp=(
        "2026-07-16T21:00:00Z"
    ),
    payload=None,
):
    resolved_payload = (
        payload
        if payload is not None
        else {
            "status": "FILLED",
            "market": "EUR_GBP",
            "entry_timestamp": (
                "2026-07-16T21:00:00Z"
            ),
            "broker_orders_submitted": 0,
        }
    )

    return {
        "event_type": event_type,
        "market": "EUR_GBP",
        "candle_timestamp": timestamp,
        "payload": resolved_payload,
    }


def test_transition_event_id_is_stable():
    event = position_event()

    first = transition_event_id(
        session_date=SESSION_DATE,
        event=event,
    )

    second = transition_event_id(
        session_date=SESSION_DATE,
        event=event,
    )

    assert first == second
    assert first.startswith(
        "paper-"
    )


def test_position_events_append_in_order(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    events = [
        position_event(),
        position_event(
            "PAPER_POSITION_MARKED",
            payload={
                "status": "OPEN",
                "market": "EUR_GBP",
                "candle_timestamp": (
                    "2026-07-16T21:00:00Z"
                ),
                "broker_orders_submitted": 0,
            },
        ),
    ]

    appended = append_transition_events(
        ledger_path=ledger_path,
        session_date=SESSION_DATE,
        transition_events=events,
        occurred_at_utc=(
            OCCURRED_AT
        ),
    )

    assert [
        event["event_type"]
        for event in appended
    ] == [
        "PAPER_POSITION_OPENED",
        "PAPER_POSITION_MARKED",
    ]

    verified = verify_ledger(
        ledger_path
    )

    assert verified == appended

    assert [
        event["sequence"]
        for event in verified
    ] == [1, 2]


def test_replaying_identical_events_is_idempotent(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    events = [
        position_event(),
    ]

    first = append_transition_events(
        ledger_path=ledger_path,
        session_date=SESSION_DATE,
        transition_events=events,
        occurred_at_utc=(
            OCCURRED_AT
        ),
    )

    second = append_transition_events(
        ledger_path=ledger_path,
        session_date=SESSION_DATE,
        transition_events=events,
        occurred_at_utc=(
            OCCURRED_AT
        ),
    )

    assert first == second

    assert len(
        verify_ledger(
            ledger_path
        )
    ) == 1


def test_conflicting_replay_is_rejected(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    original = position_event()

    append_transition_events(
        ledger_path=ledger_path,
        session_date=SESSION_DATE,
        transition_events=[
            original,
        ],
        occurred_at_utc=(
            OCCURRED_AT
        ),
    )

    conflicting = position_event(
        payload={
            **original[
                "payload"
            ],
            "entry_price": 9.999,
        }
    )

    with pytest.raises(
        LedgerIntegrityError,
        match="different content",
    ):
        append_transition_events(
            ledger_path=ledger_path,
            session_date=SESSION_DATE,
            transition_events=[
                conflicting,
            ],
            occurred_at_utc=(
                OCCURRED_AT
            ),
        )


def test_duplicate_identity_in_one_batch_is_rejected(
    tmp_path,
):
    event = position_event()

    with pytest.raises(
        TransitionLedgerError,
        match="duplicate deterministic",
    ):
        append_transition_events(
            ledger_path=(
                tmp_path
                / "events.jsonl"
            ),
            session_date=SESSION_DATE,
            transition_events=[
                event,
                event,
            ],
            occurred_at_utc=(
                OCCURRED_AT
            ),
        )


def test_invalid_timestamp_is_rejected(
    tmp_path,
):
    with pytest.raises(
        TransitionLedgerError,
        match="timestamp is invalid",
    ):
        append_transition_events(
            ledger_path=(
                tmp_path
                / "events.jsonl"
            ),
            session_date=SESSION_DATE,
            transition_events=[
                position_event(
                    timestamp="not-a-date",
                ),
            ],
            occurred_at_utc=(
                OCCURRED_AT
            ),
        )


def test_timezone_naive_timestamp_is_rejected(
    tmp_path,
):
    with pytest.raises(
        TransitionLedgerError,
        match="timezone-aware",
    ):
        append_transition_events(
            ledger_path=(
                tmp_path
                / "events.jsonl"
            ),
            session_date=SESSION_DATE,
            transition_events=[
                position_event(
                    timestamp=(
                        "2026-07-16T21:00:00"
                    ),
                ),
            ],
            occurred_at_utc=(
                OCCURRED_AT
            ),
        )


def test_unsupported_event_type_is_rejected(
    tmp_path,
):
    with pytest.raises(
        TransitionLedgerError,
        match="Unsupported transition",
    ):
        append_transition_events(
            ledger_path=(
                tmp_path
                / "events.jsonl"
            ),
            session_date=SESSION_DATE,
            transition_events=[
                position_event(
                    "LIVE_ORDER_SENT"
                ),
            ],
            occurred_at_utc=(
                OCCURRED_AT
            ),
        )


def test_payload_market_must_match(
    tmp_path,
):
    with pytest.raises(
        TransitionLedgerError,
        match="does not match",
    ):
        append_transition_events(
            ledger_path=(
                tmp_path
                / "events.jsonl"
            ),
            session_date=SESSION_DATE,
            transition_events=[
                position_event(
                    payload={
                        "status": "FILLED",
                        "market": "GBP_JPY",
                    }
                ),
            ],
            occurred_at_utc=(
                OCCURRED_AT
            ),
        )


def test_occurred_at_requires_timezone(
    tmp_path,
):
    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        append_transition_events(
            ledger_path=(
                tmp_path
                / "events.jsonl"
            ),
            session_date=SESSION_DATE,
            transition_events=[],
            occurred_at_utc=datetime(
                2026,
                7,
                16,
                23,
                15,
            ),
        )
