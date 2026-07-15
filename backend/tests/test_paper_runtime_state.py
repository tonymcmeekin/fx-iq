import json
from datetime import UTC, datetime

import pytest

from app.paper_trading.runtime_state import (
    RuntimeStateError,
    add_pending_entry,
    build_pending_entry,
    empty_runtime_state,
    mark_state_updated,
    read_runtime_state,
    remove_pending_entry,
    verify_runtime_state,
    write_runtime_state,
)


SIGNAL_TIME = datetime(
    2026,
    7,
    14,
    21,
    0,
    tzinfo=UTC,
)


def pending_entry(
    market="EUR_GBP",
):
    return build_pending_entry(
        market=market,
        signal_candle_timestamp=(
            SIGNAL_TIME
        ),
        direction="BUY",
        candidate_risk_percent=0.25,
        shadow_risk_percent=0.5,
        directional_close_location=0.7,
        policy_fingerprint=(
            "test-fingerprint"
        ),
        created_session_date=(
            "2026-07-15"
        ),
    )


def test_missing_state_returns_clean_initial_state(
    tmp_path,
):
    state = read_runtime_state(
        tmp_path / "state.json"
    )

    assert state == (
        empty_runtime_state()
    )

    assert state[
        "broker_orders_sent"
    ] == 0


def test_state_round_trip_is_atomic(
    tmp_path,
):
    state_path = (
        tmp_path / "state.json"
    )

    state = add_pending_entry(
        empty_runtime_state(),
        pending_entry(),
    )

    write_runtime_state(
        state_path,
        state,
    )

    assert read_runtime_state(
        state_path
    ) == state

    assert not (
        tmp_path / ".state.json.tmp"
    ).exists()


def test_pending_entry_addition_is_idempotent():
    state = empty_runtime_state()
    pending = pending_entry()

    first = add_pending_entry(
        state,
        pending,
    )

    second = add_pending_entry(
        first,
        pending,
    )

    assert first == second

    assert list(
        second["pending_entries"]
    ) == ["EUR_GBP"]


def test_different_pending_entry_is_rejected():
    state = add_pending_entry(
        empty_runtime_state(),
        pending_entry(),
    )

    changed = {
        **pending_entry(),
        "direction": "SELL",
    }

    with pytest.raises(
        RuntimeStateError,
        match="different pending entry",
    ):
        add_pending_entry(
            state,
            changed,
        )


def test_pending_entry_can_be_removed():
    state = add_pending_entry(
        empty_runtime_state(),
        pending_entry(),
    )

    updated, removed = (
        remove_pending_entry(
            state,
            "EUR_GBP",
        )
    )

    assert removed == (
        pending_entry()
    )

    assert updated[
        "pending_entries"
    ] == {}


def test_broker_order_count_must_remain_zero():
    state = empty_runtime_state()
    state["broker_orders_sent"] = 1

    with pytest.raises(
        RuntimeStateError,
        match="broker orders",
    ):
        verify_runtime_state(
            state
        )


def test_pending_and_open_position_cannot_overlap():
    state = add_pending_entry(
        empty_runtime_state(),
        pending_entry(),
    )

    state["open_positions"][
        "EUR_GBP"
    ] = {
        "market": "EUR_GBP",
    }

    with pytest.raises(
        RuntimeStateError,
        match="both a pending entry",
    ):
        verify_runtime_state(
            state
        )


def test_state_update_records_utc_time():
    state = mark_state_updated(
        empty_runtime_state(),
        updated_at_utc=datetime(
            2026,
            7,
            15,
            23,
            15,
            tzinfo=UTC,
        ),
        completed_session_date=(
            "2026-07-15"
        ),
    )

    assert state[
        "last_updated_at_utc"
    ] == "2026-07-15T23:15:00Z"

    assert state[
        "last_completed_session_date"
    ] == "2026-07-15"


def test_invalid_json_is_rejected(
    tmp_path,
):
    state_path = (
        tmp_path / "state.json"
    )

    state_path.write_text(
        "not-json",
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeStateError,
        match="valid JSON",
    ):
        read_runtime_state(
            state_path
        )


def test_state_file_contains_no_token(
    tmp_path,
):
    state_path = (
        tmp_path / "state.json"
    )

    write_runtime_state(
        state_path,
        empty_runtime_state(),
    )

    payload = json.loads(
        state_path.read_text(
            encoding="utf-8"
        )
    )

    assert "api_token" not in payload
    assert "OANDA_API_TOKEN" not in (
        state_path.read_text(
            encoding="utf-8"
        )
    )


def test_legacy_state_without_checkpoint_is_normalised(
    tmp_path,
):
    state_path = (
        tmp_path / "state.json"
    )

    legacy = empty_runtime_state()
    legacy.pop(
        "processed_candle_timestamps"
    )

    state_path.write_text(
        json.dumps(
            legacy
        ),
        encoding="utf-8",
    )

    state = read_runtime_state(
        state_path
    )

    assert state[
        "processed_candle_timestamps"
    ] == {}


def test_processed_candle_checkpoint_is_monotonic():
    from app.paper_trading.runtime_state import (
        mark_candle_processed,
    )

    first_timestamp = datetime(
        2026,
        7,
        14,
        21,
        0,
        tzinfo=UTC,
    )

    second_timestamp = datetime(
        2026,
        7,
        15,
        21,
        0,
        tzinfo=UTC,
    )

    first = mark_candle_processed(
        empty_runtime_state(),
        market="EUR_GBP",
        candle_timestamp=(
            first_timestamp
        ),
    )

    repeated = mark_candle_processed(
        first,
        market="EUR_GBP",
        candle_timestamp=(
            first_timestamp
        ),
    )

    second = mark_candle_processed(
        repeated,
        market="EUR_GBP",
        candle_timestamp=(
            second_timestamp
        ),
    )

    assert repeated == first

    assert second[
        "processed_candle_timestamps"
    ]["EUR_GBP"] == (
        "2026-07-15T21:00:00Z"
    )

    with pytest.raises(
        RuntimeStateError,
        match="cannot move backwards",
    ):
        mark_candle_processed(
            second,
            market="EUR_GBP",
            candle_timestamp=(
                first_timestamp
            ),
        )


def test_invalid_processed_checkpoint_is_rejected():
    state = empty_runtime_state()

    state[
        "processed_candle_timestamps"
    ]["EUR_GBP"] = "not-a-time"

    with pytest.raises(
        RuntimeStateError,
        match="valid ISO-8601",
    ):
        verify_runtime_state(
            state
        )
