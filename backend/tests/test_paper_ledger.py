import json

import pytest

from app.paper_trading.ledger import (
    GENESIS_HASH,
    LedgerIntegrityError,
    append_event,
    read_events,
    verify_ledger,
)


def test_missing_ledger_is_valid_and_empty(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    assert verify_ledger(
        ledger_path
    ) == []


def test_first_event_uses_genesis_hash(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    event = append_event(
        ledger_path,
        "SESSION_STARTED",
        {"session_date": "2026-07-16"},
        event_id="event-1",
        occurred_at_utc=(
            "2026-07-16T23:15:00Z"
        ),
    )

    assert event["sequence"] == 1

    assert event["previous_hash"] == (
        GENESIS_HASH
    )

    assert verify_ledger(
        ledger_path
    ) == [event]


def test_events_form_hash_chain(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    first = append_event(
        ledger_path,
        "SESSION_STARTED",
        {"session_date": "2026-07-16"},
        event_id="event-1",
        occurred_at_utc=(
            "2026-07-16T23:15:00Z"
        ),
    )

    second = append_event(
        ledger_path,
        "SESSION_COMPLETED",
        {"status": "SUCCESS"},
        event_id="event-2",
        occurred_at_utc=(
            "2026-07-16T23:16:00Z"
        ),
    )

    assert second["sequence"] == 2

    assert second["previous_hash"] == (
        first["event_hash"]
    )

    assert len(
        verify_ledger(
            ledger_path
        )
    ) == 2


def test_duplicate_event_id_is_rejected(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    append_event(
        ledger_path,
        "SESSION_STARTED",
        {},
        event_id="duplicate",
    )

    with pytest.raises(
        LedgerIntegrityError,
        match="Duplicate event ID",
    ):
        append_event(
            ledger_path,
            "SESSION_COMPLETED",
            {},
            event_id="duplicate",
        )


def test_unsupported_event_type_is_rejected(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    with pytest.raises(
        ValueError,
        match="Unsupported event type",
    ):
        append_event(
            ledger_path,
            "LIVE_ORDER_SENT",
            {},
        )


def test_non_dictionary_payload_is_rejected(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    with pytest.raises(
        TypeError,
        match="payload must be a dictionary",
    ):
        append_event(
            ledger_path,
            "SESSION_STARTED",
            [],
        )


def test_tampered_payload_is_detected(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    append_event(
        ledger_path,
        "SESSION_STARTED",
        {"status": "ORIGINAL"},
        event_id="event-1",
    )

    events = read_events(
        ledger_path
    )

    events[0]["payload"]["status"] = (
        "TAMPERED"
    )

    ledger_path.write_text(
        json.dumps(
            events[0]
        )
        + "\n"
    )

    with pytest.raises(
        LedgerIntegrityError,
        match="Event hash mismatch",
    ):
        verify_ledger(
            ledger_path
        )


def test_tampered_previous_hash_is_detected(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    append_event(
        ledger_path,
        "SESSION_STARTED",
        {},
        event_id="event-1",
    )

    append_event(
        ledger_path,
        "SESSION_COMPLETED",
        {},
        event_id="event-2",
    )

    events = read_events(
        ledger_path
    )

    events[1]["previous_hash"] = (
        GENESIS_HASH
    )

    ledger_path.write_text(
        "\n".join(
            json.dumps(event)
            for event in events
        )
        + "\n"
    )

    with pytest.raises(
        LedgerIntegrityError,
        match="Previous hash mismatch",
    ):
        verify_ledger(
            ledger_path
        )


def test_invalid_json_is_detected(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    ledger_path.write_text(
        "not-json\n"
    )

    with pytest.raises(
        LedgerIntegrityError,
        match="Invalid JSON",
    ):
        verify_ledger(
            ledger_path
        )


def test_blank_ledger_line_is_detected(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    ledger_path.write_text(
        "\n"
    )

    with pytest.raises(
        LedgerIntegrityError,
        match="Blank ledger line",
    ):
        verify_ledger(
            ledger_path
        )
