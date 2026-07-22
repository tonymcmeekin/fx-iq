from datetime import (
    UTC,
    date,
    datetime,
)

import pytest

from app.market_data.models import Candle
from app.paper_trading.daily_transition import (
    DailyTransitionError,
    process_new_market_candles,
    run_persisted_daily_transition,
)
from app.paper_trading.runtime_state import (
    add_pending_entry,
    build_pending_entry,
    empty_runtime_state,
    read_runtime_state,
)

MARKET = "EUR_GBP"

POLICY_FINGERPRINT = (
    "test-policy-fingerprint"
)

FIRST_ELIGIBLE_DATE = date(
    2026,
    7,
    14,
)

SIGNAL_TIMESTAMP = datetime(
    2026,
    7,
    14,
    21,
    0,
    tzinfo=UTC,
)

ENTRY_TIMESTAMP = datetime(
    2026,
    7,
    15,
    21,
    0,
    tzinfo=UTC,
)


def candle(
    timestamp,
    *,
    open_price=1.0,
    high=1.01,
    low=0.99,
    close=1.0,
):
    return Candle(
        symbol=MARKET,
        timeframe="D",
        timestamp=timestamp,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1000,
    )


def pending_state():
    pending = build_pending_entry(
        market=MARKET,
        signal_candle_timestamp=(
            SIGNAL_TIMESTAMP
        ),
        direction="BUY",
        candidate_risk_percent=0.25,
        shadow_risk_percent=0.5,
        directional_close_location=0.9,
        policy_fingerprint=(
            POLICY_FINGERPRINT
        ),
        created_session_date=(
            "2026-07-14"
        ),
    )

    return add_pending_entry(
        empty_runtime_state(),
        pending,
    )


def test_new_entry_candle_is_filled_and_marked():
    candles = [
        candle(
            SIGNAL_TIMESTAMP,
        ),
        candle(
            ENTRY_TIMESTAMP,
            open_price=1.0,
            high=1.02,
            low=0.99,
            close=1.01,
        ),
    ]

    updated, result = (
        process_new_market_candles(
            pending_state(),
            market=MARKET,
            candles=candles,
            previous_candle_count=1,
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )
    )

    assert result[
        "new_candles_processed"
    ] == 1

    assert result[
        "positions_opened"
    ] == 1

    assert result[
        "position_marks"
    ] == 1

    assert result[
        "positions_closed"
    ] == 0

    assert MARKET not in updated[
        "pending_entries"
    ]

    assert MARKET in updated[
        "open_positions"
    ]

    assert [
        event["event_type"]
        for event in result["events"]
    ] == [
        "PAPER_POSITION_OPENED",
        "PAPER_POSITION_MARKED",
    ]


def test_entry_candle_can_close_at_target():
    candles = [
        candle(
            SIGNAL_TIMESTAMP,
        ),
        candle(
            ENTRY_TIMESTAMP,
            open_price=1.0,
            high=1.04,
            low=0.99,
            close=1.03,
        ),
    ]

    updated, result = (
        process_new_market_candles(
            pending_state(),
            market=MARKET,
            candles=candles,
            previous_candle_count=1,
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )
    )

    assert result[
        "positions_opened"
    ] == 1

    assert result[
        "positions_closed"
    ] == 1

    assert MARKET not in updated[
        "pending_entries"
    ]

    assert MARKET not in updated[
        "open_positions"
    ]

    assert updated[
        "candidate_balance"
    ] > 10000.0

    assert updated[
        "shadow_balance"
    ] > 10000.0

    assert [
        event["event_type"]
        for event in result["events"]
    ] == [
        "PAPER_POSITION_OPENED",
        "PAPER_POSITION_CLOSED",
    ]


def test_ambiguous_entry_candle_uses_stop():
    candles = [
        candle(
            SIGNAL_TIMESTAMP,
        ),
        candle(
            ENTRY_TIMESTAMP,
            open_price=1.0,
            high=1.04,
            low=0.98,
            close=1.01,
        ),
    ]

    updated, result = (
        process_new_market_candles(
            pending_state(),
            market=MARKET,
            candles=candles,
            previous_candle_count=1,
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )
    )

    closure = result[
        "lifecycle_results"
    ][-1]

    assert closure[
        "status"
    ] == "CLOSED"

    assert closure[
        "stop_hit"
    ] is True

    assert closure[
        "target_hit"
    ] is True

    assert "both stop-loss" in (
        closure[
            "exit_reason"
        ]
    )

    assert updated[
        "candidate_balance"
    ] < 10000.0

    assert updated[
        "shadow_balance"
    ] < 10000.0


def test_no_new_candles_is_idempotent():
    candles = [
        candle(
            SIGNAL_TIMESTAMP,
        ),
    ]

    state = pending_state()

    updated, result = (
        process_new_market_candles(
            state,
            market=MARKET,
            candles=candles,
            previous_candle_count=1,
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )
    )

    assert updated == state

    assert result[
        "new_candles_processed"
    ] == 0

    assert result["events"] == []


def test_waiting_pending_entry_remains_pending():
    candles = [
        candle(
            SIGNAL_TIMESTAMP,
        ),
    ]

    updated, result = (
        process_new_market_candles(
            pending_state(),
            market=MARKET,
            candles=candles,
            previous_candle_count=0,
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )
    )

    assert MARKET in updated[
        "pending_entries"
    ]

    assert MARKET not in updated[
        "open_positions"
    ]

    assert result[
        "positions_opened"
    ] == 0

    assert result["events"] == []


def test_previous_count_cannot_exceed_store():
    with pytest.raises(
        DailyTransitionError,
        match="exceeds stored candles",
    ):
        process_new_market_candles(
            empty_runtime_state(),
            market=MARKET,
            candles=[
                candle(
                    SIGNAL_TIMESTAMP
                )
            ],
            previous_candle_count=2,
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )


def test_transition_rejects_wrong_market():
    wrong = candle(
        SIGNAL_TIMESTAMP
    ).model_copy(
        update={
            "symbol": "GBP_JPY",
        }
    )

    with pytest.raises(
        DailyTransitionError,
        match="does not match",
    ):
        process_new_market_candles(
            empty_runtime_state(),
            market=MARKET,
            candles=[wrong],
            previous_candle_count=0,
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )


def test_persisted_transition_updates_state_once(
    tmp_path,
):
    state_path = (
        tmp_path
        / "paper_ledger"
        / "state.json"
    )

    candle_directory = (
        tmp_path
        / "prospective"
    )

    from app.paper_trading.runtime_state import (
        write_runtime_state,
    )

    write_runtime_state(
        state_path,
        pending_state(),
    )

    result = (
        run_persisted_daily_transition(
            state_path=state_path,
            candle_store_directory=(
                candle_directory
            ),
            market_candles={
                MARKET: [
                    candle(
                        SIGNAL_TIMESTAMP,
                    ),
                    candle(
                        ENTRY_TIMESTAMP,
                        open_price=1.0,
                        high=1.02,
                        low=0.99,
                        close=1.01,
                    ),
                ],
            },
            markets=[MARKET],
            first_eligible_market_date=(
                FIRST_ELIGIBLE_DATE
            ),
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )
    )

    assert result[
        "candles_added"
    ] == 2

    # The signal candle is already represented by the pending
    # entry, so only the following entry candle is unprocessed.
    assert result[
        "new_candles_processed"
    ] == 1

    assert result[
        "positions_opened"
    ] == 1

    assert result[
        "position_marks"
    ] == 1

    assert result[
        "runtime_state_updated"
    ] is True

    state = read_runtime_state(
        state_path
    )

    assert MARKET in state[
        "open_positions"
    ]

    assert MARKET not in state[
        "pending_entries"
    ]

    assert result[
        "broker_orders_submitted"
    ] == 0


def test_persisted_transition_repeat_is_noop(
    tmp_path,
):
    state_path = (
        tmp_path
        / "paper_ledger"
        / "state.json"
    )

    candle_directory = (
        tmp_path
        / "prospective"
    )

    from app.paper_trading.runtime_state import (
        write_runtime_state,
    )

    write_runtime_state(
        state_path,
        pending_state(),
    )

    arguments = {
        "state_path": state_path,
        "candle_store_directory": (
            candle_directory
        ),
        "market_candles": {
            MARKET: [
                candle(
                    SIGNAL_TIMESTAMP,
                ),
                candle(
                    ENTRY_TIMESTAMP,
                    open_price=1.0,
                    high=1.02,
                    low=0.99,
                    close=1.01,
                ),
            ],
        },
        "markets": [MARKET],
        "first_eligible_market_date": (
            FIRST_ELIGIBLE_DATE
        ),
        "policy_fingerprint": (
            POLICY_FINGERPRINT
        ),
    }

    first = (
        run_persisted_daily_transition(
            **arguments
        )
    )

    state_after_first = (
        read_runtime_state(
            state_path
        )
    )

    second = (
        run_persisted_daily_transition(
            **arguments
        )
    )

    state_after_second = (
        read_runtime_state(
            state_path
        )
    )

    assert first[
        "positions_opened"
    ] == 1

    assert second[
        "candles_added"
    ] == 0

    assert second[
        "new_candles_processed"
    ] == 0

    assert second["events"] == []

    assert second[
        "runtime_state_updated"
    ] is False

    assert (
        state_after_second
        == state_after_first
    )


def test_market_order_must_match():
    with pytest.raises(
        DailyTransitionError,
        match="exactly match",
    ):
        run_persisted_daily_transition(
            state_path=(
                pytest.Path
                if False
                else __import__(
                    "pathlib"
                ).Path(
                    "/tmp/unused-state"
                )
            ),
            candle_store_directory=(
                __import__(
                    "pathlib"
                ).Path(
                    "/tmp/unused-candles"
                )
            ),
            market_candles={
                "GBP_JPY": [],
                MARKET: [],
            },
            markets=[
                MARKET,
                "GBP_JPY",
            ],
            first_eligible_market_date=(
                FIRST_ELIGIBLE_DATE
            ),
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )


def test_persisted_candles_are_reprocessed_after_prejournal_crash(
    tmp_path,
):
    """
    Simulate this failure sequence:

    1. Candles are atomically persisted.
    2. The process crashes before a transition journal/state commit.
    3. The next run sees zero newly added CSV rows.
    4. The pending signal timestamp still identifies the unprocessed
       entry candle, so the transition is correctly replayed.
    """
    from app.paper_trading.candle_store import (
        persist_prospective_candles,
    )
    from app.paper_trading.runtime_state import (
        write_runtime_state,
    )

    state_path = (
        tmp_path
        / "paper_ledger"
        / "state.json"
    )

    candle_directory = (
        tmp_path / "prospective"
    )

    store_path = (
        candle_directory
        / f"{MARKET}.csv"
    )

    candles = [
        candle(
            SIGNAL_TIMESTAMP,
        ),
        candle(
            ENTRY_TIMESTAMP,
            open_price=1.0,
            high=1.02,
            low=0.99,
            close=1.01,
        ),
    ]

    write_runtime_state(
        state_path,
        pending_state(),
    )

    persist_prospective_candles(
        store_path,
        candles,
        expected_symbol=MARKET,
        first_eligible_market_date=(
            FIRST_ELIGIBLE_DATE
        ),
    )

    result = (
        run_persisted_daily_transition(
            state_path=state_path,
            candle_store_directory=(
                candle_directory
            ),
            market_candles={
                MARKET: candles,
            },
            markets=[MARKET],
            first_eligible_market_date=(
                FIRST_ELIGIBLE_DATE
            ),
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )
    )

    state = read_runtime_state(
        state_path
    )

    assert result[
        "candles_added"
    ] == 0

    assert result[
        "new_candles_processed"
    ] == 1

    assert result[
        "positions_opened"
    ] == 1

    assert MARKET in state[
        "open_positions"
    ]

    assert state[
        "processed_candle_timestamps"
    ][MARKET] == (
        "2026-07-15T21:00:00Z"
    )


def test_timestamp_checkpoint_overrides_stale_count(
    tmp_path,
):
    from app.paper_trading.runtime_state import (
        mark_candle_processed,
        write_runtime_state,
    )

    state_path = (
        tmp_path
        / "paper_ledger"
        / "state.json"
    )

    candle_directory = (
        tmp_path / "prospective"
    )

    checkpointed = (
        mark_candle_processed(
            pending_state(),
            market=MARKET,
            candle_timestamp=(
                SIGNAL_TIMESTAMP
            ),
        )
    )

    write_runtime_state(
        state_path,
        checkpointed,
    )

    candles = [
        candle(
            SIGNAL_TIMESTAMP,
        ),
        candle(
            ENTRY_TIMESTAMP,
            open_price=1.0,
            high=1.02,
            low=0.99,
            close=1.01,
        ),
    ]

    result = (
        run_persisted_daily_transition(
            state_path=state_path,
            candle_store_directory=(
                candle_directory
            ),
            market_candles={
                MARKET: candles,
            },
            markets=[MARKET],
            first_eligible_market_date=(
                FIRST_ELIGIBLE_DATE
            ),
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )
    )

    assert result[
        "new_candles_processed"
    ] == 1

    assert result[
        "positions_opened"
    ] == 1
