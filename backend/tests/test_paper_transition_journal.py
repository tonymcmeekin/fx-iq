import json
from datetime import UTC, date, datetime

import pytest

from app.paper_trading.runtime_state import (
    empty_runtime_state,
)
from app.paper_trading.transition_journal import (
    LEDGER_APPENDED,
    PREPARED,
    STATE_COMMITTED,
    TransitionJournalError,
    advance_transition_journal,
    build_transition_journal,
    read_transition_journal,
    remove_transition_journal,
    verify_transition_journal,
    write_transition_journal,
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


def transition_event():
    return {
        "event_type": (
            "PAPER_POSITION_OPENED"
        ),
        "market": "EUR_GBP",
        "candle_timestamp": (
            "2026-07-16T21:00:00Z"
        ),
        "payload": {
            "status": "FILLED",
            "market": "EUR_GBP",
            "entry_timestamp": (
                "2026-07-16T21:00:00Z"
            ),
            "broker_orders_submitted": 0,
        },
    }


def journal():
    return build_transition_journal(
        session_date=SESSION_DATE,
        policy_fingerprint=(
            "test-policy-fingerprint"
        ),
        occurred_at_utc=(
            OCCURRED_AT
        ),
        transition_events=[
            transition_event(),
        ],
        target_state=(
            empty_runtime_state()
        ),
        candle_counts_before={
            "EUR_GBP": 1,
            "EUR_JPY": 2,
        },
        candle_counts_after={
            "EUR_GBP": 2,
            "EUR_JPY": 2,
        },
    )


def test_builds_prepared_journal():
    built = journal()

    assert built[
        "stage"
    ] == PREPARED

    assert built[
        "broker_orders_submitted"
    ] == 0

    assert len(
        built["checksum"]
    ) == 64


def test_journal_round_trip_is_atomic(
    tmp_path,
):
    journal_path = (
        tmp_path
        / "transition.json"
    )

    built = journal()

    write_transition_journal(
        journal_path,
        built,
    )

    assert read_transition_journal(
        journal_path
    ) == built

    assert not (
        tmp_path
        / ".transition.json.tmp"
    ).exists()


def test_missing_journal_returns_none(
    tmp_path,
):
    assert read_transition_journal(
        tmp_path
        / "missing.json"
    ) is None


def test_checksum_tampering_is_detected():
    built = journal()

    built[
        "policy_fingerprint"
    ] = "tampered"

    with pytest.raises(
        TransitionJournalError,
        match="checksum mismatch",
    ):
        verify_transition_journal(
            built
        )


def test_invalid_json_is_rejected(
    tmp_path,
):
    journal_path = (
        tmp_path
        / "transition.json"
    )

    journal_path.write_text(
        "not-json",
        encoding="utf-8",
    )

    with pytest.raises(
        TransitionJournalError,
        match="valid JSON",
    ):
        read_transition_journal(
            journal_path
        )


def test_journal_advances_one_stage_at_a_time():
    prepared = journal()

    ledger_appended = (
        advance_transition_journal(
            prepared,
            next_stage=(
                LEDGER_APPENDED
            ),
        )
    )

    state_committed = (
        advance_transition_journal(
            ledger_appended,
            next_stage=(
                STATE_COMMITTED
            ),
        )
    )

    assert ledger_appended[
        "stage"
    ] == LEDGER_APPENDED

    assert state_committed[
        "stage"
    ] == STATE_COMMITTED


def test_advancing_same_stage_is_idempotent():
    prepared = journal()

    repeated = (
        advance_transition_journal(
            prepared,
            next_stage=PREPARED,
        )
    )

    assert repeated == prepared


def test_journal_cannot_skip_stage():
    with pytest.raises(
        TransitionJournalError,
        match="cannot skip",
    ):
        advance_transition_journal(
            journal(),
            next_stage=(
                STATE_COMMITTED
            ),
        )


def test_journal_cannot_move_backwards():
    ledger_appended = (
        advance_transition_journal(
            journal(),
            next_stage=(
                LEDGER_APPENDED
            ),
        )
    )

    with pytest.raises(
        TransitionJournalError,
        match="cannot move backwards",
    ):
        advance_transition_journal(
            ledger_appended,
            next_stage=PREPARED,
        )


def test_candle_counts_must_match_in_order():
    with pytest.raises(
        TransitionJournalError,
        match="must match in order",
    ):
        build_transition_journal(
            session_date=(
                SESSION_DATE
            ),
            policy_fingerprint="test",
            occurred_at_utc=(
                OCCURRED_AT
            ),
            transition_events=[],
            target_state=(
                empty_runtime_state()
            ),
            candle_counts_before={
                "EUR_GBP": 1,
                "EUR_JPY": 1,
            },
            candle_counts_after={
                "EUR_JPY": 1,
                "EUR_GBP": 1,
            },
        )


def test_after_count_cannot_decrease():
    with pytest.raises(
        TransitionJournalError,
        match="Invalid after",
    ):
        build_transition_journal(
            session_date=(
                SESSION_DATE
            ),
            policy_fingerprint="test",
            occurred_at_utc=(
                OCCURRED_AT
            ),
            transition_events=[],
            target_state=(
                empty_runtime_state()
            ),
            candle_counts_before={
                "EUR_GBP": 2,
            },
            candle_counts_after={
                "EUR_GBP": 1,
            },
        )


def test_broker_orders_are_rejected():
    built = journal()

    built[
        "broker_orders_submitted"
    ] = 1

    built_without_checksum = {
        key: value
        for key, value in built.items()
        if key != "checksum"
    }

    import hashlib

    from app.paper_trading.transition_journal import (
        canonical_json,
    )

    built["checksum"] = hashlib.sha256(
        canonical_json(
            built_without_checksum
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(
        TransitionJournalError,
        match="broker orders",
    ):
        verify_transition_journal(
            built
        )


def test_remove_journal_is_idempotent(
    tmp_path,
):
    journal_path = (
        tmp_path
        / "transition.json"
    )

    write_transition_journal(
        journal_path,
        journal(),
    )

    remove_transition_journal(
        journal_path
    )

    remove_transition_journal(
        journal_path
    )

    assert not journal_path.exists()


def test_journal_contains_no_api_token(
    tmp_path,
):
    journal_path = (
        tmp_path
        / "transition.json"
    )

    write_transition_journal(
        journal_path,
        journal(),
    )

    text = journal_path.read_text(
        encoding="utf-8"
    )

    payload = json.loads(
        text
    )

    assert "api_token" not in payload
    assert "OANDA_API_TOKEN" not in text
    assert "test-token" not in text
