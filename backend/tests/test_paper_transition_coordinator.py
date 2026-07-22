from datetime import (
    UTC,
    date,
    datetime,
)

import pytest

from app.market_data.models import Candle
from app.paper_trading.ledger import (
    verify_ledger,
)
from app.paper_trading.runtime_state import (
    add_pending_entry,
    build_pending_entry,
    empty_runtime_state,
    read_runtime_state,
    write_runtime_state,
)
from app.paper_trading.transition_coordinator import (
    TransitionCoordinatorError,
    commit_prepared_transition,
    prepare_transition,
    run_recoverable_transition,
)
from app.paper_trading.transition_journal import (
    LEDGER_APPENDED,
    STATE_COMMITTED,
    advance_transition_journal,
    read_transition_journal,
    write_transition_journal,
)
from app.paper_trading.transition_ledger import (
    append_transition_events,
)

MARKET = "EUR_GBP"

SESSION_DATE = date(
    2026,
    7,
    16,
)

FIRST_ELIGIBLE_DATE = date(
    2026,
    7,
    14,
)

POLICY_FINGERPRINT = (
    "test-policy-fingerprint"
)

OCCURRED_AT = datetime(
    2026,
    7,
    16,
    23,
    15,
    tzinfo=UTC,
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


def paths(tmp_path):
    return {
        "journal_path": (
            tmp_path
            / "paper_ledger"
            / "transition.json"
        ),
        "ledger_path": (
            tmp_path
            / "paper_ledger"
            / "events.jsonl"
        ),
        "state_path": (
            tmp_path
            / "paper_ledger"
            / "state.json"
        ),
        "candle_store_directory": (
            tmp_path
            / "prospective"
        ),
    }


def transition_arguments(tmp_path):
    return {
        **paths(tmp_path),
        "session_date": SESSION_DATE,
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
        "occurred_at_utc": (
            OCCURRED_AT
        ),
    }


def test_prepare_writes_journal_not_state_or_ledger(
    tmp_path,
):
    selected_paths = paths(
        tmp_path
    )

    write_runtime_state(
        selected_paths[
            "state_path"
        ],
        pending_state(),
    )

    state_before = (
        read_runtime_state(
            selected_paths[
                "state_path"
            ]
        )
    )

    result = prepare_transition(
        **transition_arguments(
            tmp_path
        )
    )

    journal = read_transition_journal(
        selected_paths[
            "journal_path"
        ]
    )

    state_after = (
        read_runtime_state(
            selected_paths[
                "state_path"
            ]
        )
    )

    assert result[
        "status"
    ] == "PREPARED"

    assert journal is not None

    assert journal[
        "stage"
    ] == "PREPARED"

    assert state_after == state_before

    assert verify_ledger(
        selected_paths[
            "ledger_path"
        ]
    ) == []

    assert result[
        "positions_opened"
    ] == 1

    assert result[
        "position_marks"
    ] == 1


def test_commit_appends_ledger_and_writes_state(
    tmp_path,
):
    selected_paths = paths(
        tmp_path
    )

    write_runtime_state(
        selected_paths[
            "state_path"
        ],
        pending_state(),
    )

    prepare_transition(
        **transition_arguments(
            tmp_path
        )
    )

    result = (
        commit_prepared_transition(
            **selected_paths
        )
    )

    state = read_runtime_state(
        selected_paths[
            "state_path"
        ]
    )

    events = verify_ledger(
        selected_paths[
            "ledger_path"
        ]
    )

    assert result[
        "status"
    ] == "COMMITTED"

    assert result[
        "journal_removed"
    ] is True

    assert not selected_paths[
        "journal_path"
    ].exists()

    assert [
        event["event_type"]
        for event in events
    ] == [
        "PAPER_POSITION_OPENED",
        "PAPER_POSITION_MARKED",
    ]

    assert MARKET in state[
        "open_positions"
    ]

    assert MARKET not in state[
        "pending_entries"
    ]

    assert result[
        "broker_orders_submitted"
    ] == 0


def test_recovery_after_ledger_append_commits_state(
    tmp_path,
):
    selected_paths = paths(
        tmp_path
    )

    write_runtime_state(
        selected_paths[
            "state_path"
        ],
        pending_state(),
    )

    prepare_transition(
        **transition_arguments(
            tmp_path
        )
    )

    journal = read_transition_journal(
        selected_paths[
            "journal_path"
        ]
    )

    append_transition_events(
        ledger_path=selected_paths[
            "ledger_path"
        ],
        session_date=SESSION_DATE,
        transition_events=journal[
            "transition_events"
        ],
        occurred_at_utc=(
            OCCURRED_AT
        ),
    )

    ledger_appended = (
        advance_transition_journal(
            journal,
            next_stage=(
                LEDGER_APPENDED
            ),
        )
    )

    write_transition_journal(
        selected_paths[
            "journal_path"
        ],
        ledger_appended,
    )

    result = (
        commit_prepared_transition(
            **selected_paths
        )
    )

    state = read_runtime_state(
        selected_paths[
            "state_path"
        ]
    )

    assert result[
        "status"
    ] == "COMMITTED"

    assert result[
        "ledger_events_appended"
    ] == 0

    assert result[
        "state_written"
    ] is True

    assert MARKET in state[
        "open_positions"
    ]

    assert len(
        verify_ledger(
            selected_paths[
                "ledger_path"
            ]
        )
    ) == 2


def test_recovery_after_state_commit_only_removes_journal(
    tmp_path,
):
    selected_paths = paths(
        tmp_path
    )

    write_runtime_state(
        selected_paths[
            "state_path"
        ],
        pending_state(),
    )

    prepare_transition(
        **transition_arguments(
            tmp_path
        )
    )

    journal = read_transition_journal(
        selected_paths[
            "journal_path"
        ]
    )

    append_transition_events(
        ledger_path=selected_paths[
            "ledger_path"
        ],
        session_date=SESSION_DATE,
        transition_events=journal[
            "transition_events"
        ],
        occurred_at_utc=(
            OCCURRED_AT
        ),
    )

    ledger_appended = (
        advance_transition_journal(
            journal,
            next_stage=(
                LEDGER_APPENDED
            ),
        )
    )

    write_runtime_state(
        selected_paths[
            "state_path"
        ],
        journal[
            "target_state"
        ],
    )

    state_committed = (
        advance_transition_journal(
            ledger_appended,
            next_stage=(
                STATE_COMMITTED
            ),
        )
    )

    write_transition_journal(
        selected_paths[
            "journal_path"
        ],
        state_committed,
    )

    result = (
        commit_prepared_transition(
            **selected_paths
        )
    )

    assert result[
        "status"
    ] == "COMMITTED"

    assert result[
        "ledger_events_appended"
    ] == 0

    assert result[
        "state_written"
    ] is False

    assert not selected_paths[
        "journal_path"
    ].exists()


def test_complete_run_is_idempotent_on_repeated_candles(
    tmp_path,
):
    selected_paths = paths(
        tmp_path
    )

    write_runtime_state(
        selected_paths[
            "state_path"
        ],
        pending_state(),
    )

    first = run_recoverable_transition(
        **transition_arguments(
            tmp_path
        )
    )

    state_after_first = (
        read_runtime_state(
            selected_paths[
                "state_path"
            ]
        )
    )

    ledger_after_first = (
        verify_ledger(
            selected_paths[
                "ledger_path"
            ]
        )
    )

    second = run_recoverable_transition(
        **transition_arguments(
            tmp_path
        )
    )

    state_after_second = (
        read_runtime_state(
            selected_paths[
                "state_path"
            ]
        )
    )

    ledger_after_second = (
        verify_ledger(
            selected_paths[
                "ledger_path"
            ]
        )
    )

    assert first[
        "positions_opened"
    ] == 1

    assert second[
        "candles_added"
    ] == 0

    assert second[
        "transition_events"
    ] == 0

    assert state_after_second == (
        state_after_first
    )

    assert ledger_after_second == (
        ledger_after_first
    )


def test_existing_journal_is_recovered_before_new_prepare(
    tmp_path,
):
    selected_paths = paths(
        tmp_path
    )

    write_runtime_state(
        selected_paths[
            "state_path"
        ],
        pending_state(),
    )

    prepare_transition(
        **transition_arguments(
            tmp_path
        )
    )

    result = run_recoverable_transition(
        **transition_arguments(
            tmp_path
        )
    )

    assert result[
        "status"
    ] == "COMMITTED"

    assert result[
        "recovered_existing_journal"
    ] is True

    assert not selected_paths[
        "journal_path"
    ].exists()


def test_prepare_rejects_second_unfinished_journal(
    tmp_path,
):
    selected_paths = paths(
        tmp_path
    )

    write_runtime_state(
        selected_paths[
            "state_path"
        ],
        pending_state(),
    )

    arguments = transition_arguments(
        tmp_path
    )

    prepare_transition(
        **arguments
    )

    with pytest.raises(
        TransitionCoordinatorError,
        match="must be recovered",
    ):
        prepare_transition(
            **arguments
        )


def test_wrong_market_order_is_rejected_before_files(
    tmp_path,
):
    selected_paths = paths(
        tmp_path
    )

    with pytest.raises(
        TransitionCoordinatorError,
        match="exactly match",
    ):
        prepare_transition(
            **{
                **transition_arguments(
                    tmp_path
                ),
                "market_candles": {
                    "GBP_JPY": [],
                    MARKET: [],
                },
                "markets": [
                    MARKET,
                    "GBP_JPY",
                ],
            }
        )

    assert not selected_paths[
        "journal_path"
    ].exists()

    assert not selected_paths[
        "state_path"
    ].exists()


def test_candle_count_mismatch_blocks_recovery(
    tmp_path,
):
    selected_paths = paths(
        tmp_path
    )

    write_runtime_state(
        selected_paths[
            "state_path"
        ],
        pending_state(),
    )

    prepare_transition(
        **transition_arguments(
            tmp_path
        )
    )

    store_path = (
        selected_paths[
            "candle_store_directory"
        ]
        / f"{MARKET}.csv"
    )

    lines = store_path.read_text(
        encoding="utf-8"
    ).splitlines()

    store_path.write_text(
        lines[0] + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        TransitionCoordinatorError,
        match="candle count",
    ):
        commit_prepared_transition(
            **selected_paths
        )


def test_no_pending_transition_is_safe(
    tmp_path,
):
    result = (
        commit_prepared_transition(
            **paths(
                tmp_path
            )
        )
    )

    assert result == {
        "status": (
            "NO_PENDING_TRANSITION"
        ),
        "journal_removed": False,
        "ledger_events_appended": 0,
        "state_written": False,
        "broker_orders_submitted": 0,
    }


def test_timezone_naive_occurred_at_is_rejected(
    tmp_path,
):
    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        prepare_transition(
            **{
                **transition_arguments(
                    tmp_path
                ),
                "occurred_at_utc": (
                    datetime(
                        2026,
                        7,
                        16,
                        23,
                        15,
                    )
                ),
            }
        )


def test_completion_event_is_final_durable_event(
    tmp_path,
):
    selected_paths = paths(
        tmp_path
    )

    write_runtime_state(
        selected_paths[
            "state_path"
        ],
        pending_state(),
    )

    result = run_recoverable_transition(
        **transition_arguments(
            tmp_path
        ),
        completion_payload={
            "session_date": (
                SESSION_DATE.isoformat()
            ),
            "status": "SUCCESS",
            "markets_processed": 1,
            "actionable_signals": 1,
            "pending_entries": 1,
            "positions_opened": 0,
            "positions_closed": 0,
            "broker_orders_sent": 0,
            "market_summaries": [],
        },
    )

    assert result["status"] == (
        "COMMITTED"
    )

    events = verify_ledger(
        selected_paths[
            "ledger_path"
        ]
    )

    assert events[-1][
        "event_type"
    ] == "SESSION_COMPLETED"

    assert events[-1][
        "payload"
    ]["broker_orders_sent"] == 0

    assert not selected_paths[
        "journal_path"
    ].exists()


def test_state_committed_recovery_appends_completion(
    tmp_path,
):
    selected_paths = paths(
        tmp_path
    )

    write_runtime_state(
        selected_paths[
            "state_path"
        ],
        pending_state(),
    )

    prepare_transition(
        **transition_arguments(
            tmp_path
        ),
        completion_payload={
            "session_date": (
                SESSION_DATE.isoformat()
            ),
            "status": "SUCCESS",
            "markets_processed": 1,
            "actionable_signals": 1,
            "pending_entries": 1,
            "positions_opened": 0,
            "positions_closed": 0,
            "broker_orders_sent": 0,
            "market_summaries": [],
        },
    )

    journal = read_transition_journal(
        selected_paths[
            "journal_path"
        ]
    )

    append_transition_events(
        ledger_path=selected_paths[
            "ledger_path"
        ],
        session_date=SESSION_DATE,
        transition_events=journal[
            "transition_events"
        ],
        occurred_at_utc=OCCURRED_AT,
    )

    journal = (
        advance_transition_journal(
            journal,
            next_stage=(
                LEDGER_APPENDED
            ),
        )
    )

    write_runtime_state(
        selected_paths[
            "state_path"
        ],
        journal[
            "target_state"
        ],
    )

    journal = (
        advance_transition_journal(
            journal,
            next_stage=(
                STATE_COMMITTED
            ),
        )
    )

    write_transition_journal(
        selected_paths[
            "journal_path"
        ],
        journal,
    )

    assert "SESSION_COMPLETED" not in [
        event["event_type"]
        for event in verify_ledger(
            selected_paths[
                "ledger_path"
            ]
        )
    ]

    commit_prepared_transition(
        journal_path=selected_paths[
            "journal_path"
        ],
        ledger_path=selected_paths[
            "ledger_path"
        ],
        state_path=selected_paths[
            "state_path"
        ],
        candle_store_directory=(
            selected_paths[
                "candle_store_directory"
            ]
        ),
    )

    events = verify_ledger(
        selected_paths[
            "ledger_path"
        ]
    )

    assert events[-1][
        "event_type"
    ] == "SESSION_COMPLETED"

    assert not selected_paths[
        "journal_path"
    ].exists()


def test_prepare_recovers_candles_persisted_before_journal(
    tmp_path,
):
    from app.paper_trading.candle_store import (
        persist_prospective_candles,
    )

    selected_paths = paths(
        tmp_path
    )

    state_before = pending_state()

    write_runtime_state(
        selected_paths[
            "state_path"
        ],
        state_before,
    )

    arguments = transition_arguments(
        tmp_path
    )

    store_path = (
        selected_paths[
            "candle_store_directory"
        ]
        / f"{MARKET}.csv"
    )

    persist_prospective_candles(
        store_path,
        arguments[
            "market_candles"
        ][MARKET],
        expected_symbol=MARKET,
        first_eligible_market_date=(
            FIRST_ELIGIBLE_DATE
        ),
    )

    result = prepare_transition(
        **arguments
    )

    journal = read_transition_journal(
        selected_paths[
            "journal_path"
        ]
    )

    assert result[
        "candles_added"
    ] == 0

    assert result[
        "positions_opened"
    ] == 1

    assert journal[
        "target_state"
    ][
        "processed_candle_timestamps"
    ][MARKET] == (
        "2026-07-15T21:00:00Z"
    )

    assert (
        read_runtime_state(
            selected_paths[
                "state_path"
            ]
        )
        == state_before
    )
