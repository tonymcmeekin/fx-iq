from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path

from app.market_data.models import Candle
from app.paper_trading.candle_store import (
    persist_prospective_candles,
    read_candle_store,
)
from app.paper_trading.daily_transition import (
    DailyTransitionError,
    process_new_market_candles,
)
from app.paper_trading.runtime_state import (
    read_runtime_state,
    verify_runtime_state,
    write_runtime_state,
)
from app.paper_trading.transition_journal import (
    LEDGER_APPENDED,
    PREPARED,
    STATE_COMMITTED,
    TransitionJournalError,
    advance_transition_journal,
    build_transition_journal,
    parse_utc_datetime,
    read_transition_journal,
    remove_transition_journal,
    write_transition_journal,
)
from app.paper_trading.transition_ledger import (
    append_transition_events,
    transition_event_id,
)
from app.paper_trading.ledger import (
    verify_ledger,
)
from app.paper_trading.session import (
    append_event_once,
    deterministic_event_id,
    utc_isoformat,
)


class TransitionCoordinatorError(RuntimeError):
    """Raised when a recoverable paper transition is invalid."""


def validate_transition_inputs(
    *,
    market_candles: dict[
        str,
        list[Candle],
    ],
    markets: list[str],
    policy_fingerprint: str,
    occurred_at_utc: datetime,
) -> None:
    if list(
        market_candles
    ) != markets:
        raise TransitionCoordinatorError(
            "Market candle order must exactly match "
            "the frozen market order."
        )

    if not markets:
        raise TransitionCoordinatorError(
            "At least one market is required."
        )

    if len(markets) != len(
        set(markets)
    ):
        raise TransitionCoordinatorError(
            "Markets must not contain duplicates."
        )

    for market in markets:
        if (
            not isinstance(market, str)
            or not market.strip()
        ):
            raise TransitionCoordinatorError(
                "Market names must be non-empty strings."
            )

    if (
        not isinstance(
            policy_fingerprint,
            str,
        )
        or not policy_fingerprint.strip()
    ):
        raise TransitionCoordinatorError(
            "Policy fingerprint is required."
        )

    if occurred_at_utc.tzinfo is None:
        raise ValueError(
            "Occurred-at time must be timezone-aware."
        )


def transition_summary(
    *,
    journal: dict,
    status: str,
    journal_removed: bool,
    ledger_events_appended: int,
    state_written: bool,
) -> dict:
    target_state = journal[
        "target_state"
    ]

    before = journal[
        "candle_counts_before"
    ]

    after = journal[
        "candle_counts_after"
    ]

    transition_events = journal[
        "transition_events"
    ]

    return {
        "status": status,
        "session_date": journal[
            "session_date"
        ],
        "journal_stage": journal[
            "stage"
        ],
        "journal_removed": (
            journal_removed
        ),
        "markets": list(before),
        "candles_added": sum(
            after[market]
            - before[market]
            for market in before
        ),
        "transition_events": len(
            transition_events
        ),
        "positions_opened": sum(
            event["event_type"]
            == "PAPER_POSITION_OPENED"
            for event in transition_events
        ),
        "position_marks": sum(
            event["event_type"]
            == "PAPER_POSITION_MARKED"
            for event in transition_events
        ),
        "positions_closed": sum(
            event["event_type"]
            == "PAPER_POSITION_CLOSED"
            for event in transition_events
        ),
        "ledger_events_appended": (
            ledger_events_appended
        ),
        "state_written": state_written,
        "pending_entries_total": len(
            target_state[
                "pending_entries"
            ]
        ),
        "open_positions_total": len(
            target_state[
                "open_positions"
            ]
        ),
        "candidate_balance": (
            target_state[
                "candidate_balance"
            ]
        ),
        "shadow_balance": (
            target_state[
                "shadow_balance"
            ]
        ),
        "broker_orders_submitted": 0,
    }


def verify_journal_candle_counts(
    *,
    journal: dict,
    candle_store_directory: Path,
) -> None:
    after_counts = journal[
        "candle_counts_after"
    ]

    for market, expected_count in (
        after_counts.items()
    ):
        stored = read_candle_store(
            candle_store_directory
            / f"{market}.csv",
            expected_symbol=market,
        )

        if len(stored) != expected_count:
            raise TransitionCoordinatorError(
                "Stored candle count does not match "
                f"the journal for {market}."
            )


def verify_journal_ledger_events(
    *,
    journal: dict,
    ledger_path: Path,
) -> None:
    session_date = date.fromisoformat(
        journal[
            "session_date"
        ]
    )

    expected_by_id = {
        transition_event_id(
            session_date=session_date,
            event=event,
        ): event
        for event in journal[
            "transition_events"
        ]
    }

    ledger_events = verify_ledger(
        ledger_path
    )

    ledger_by_id = {
        event["event_id"]: event
        for event in ledger_events
    }

    for event_id, transition_event in (
        expected_by_id.items()
    ):
        ledger_event = ledger_by_id.get(
            event_id
        )

        if ledger_event is None:
            raise TransitionCoordinatorError(
                "Journal transition event is missing "
                "from the ledger."
            )

        if (
            ledger_event["event_type"]
            != transition_event[
                "event_type"
            ]
            or ledger_event["payload"]
            != transition_event[
                "payload"
            ]
        ):
            raise TransitionCoordinatorError(
                "Journal transition event conflicts "
                "with the ledger."
            )


def prepare_transition(
    *,
    journal_path: Path,
    ledger_path: Path | None = None,
    state_path: Path,
    candle_store_directory: Path,
    session_date: date,
    market_candles: dict[
        str,
        list[Candle],
    ],
    markets: list[str],
    first_eligible_market_date: date,
    policy_fingerprint: str,
    occurred_at_utc: datetime,
    initial_state: dict | None = None,
    completion_payload: dict | None = None,
) -> dict:
    """
    Persist candles and prepare an in-memory state transition.

    The target state is stored in a durable journal. Runtime state
    and position ledger events are not committed by this function.

    ledger_path is accepted so callers can use one consistent path
    bundle across prepare, commit and recovery. It is deliberately
    not read or written during preparation.
    """
    del ledger_path

    validate_transition_inputs(
        market_candles=market_candles,
        markets=markets,
        policy_fingerprint=(
            policy_fingerprint
        ),
        occurred_at_utc=(
            occurred_at_utc
        ),
    )

    existing_journal = (
        read_transition_journal(
            journal_path
        )
    )

    if existing_journal is not None:
        raise TransitionCoordinatorError(
            "An unfinished transition journal already "
            "exists and must be recovered first."
        )

    original_state = (
        read_runtime_state(
            state_path
        )
    )

    if initial_state is None:
        updated_state = deepcopy(
            original_state
        )
    else:
        updated_state = deepcopy(
            verify_runtime_state(
                initial_state
            )
        )

    candle_counts_before: dict[
        str,
        int,
    ] = {}

    candle_counts_after: dict[
        str,
        int,
    ] = {}

    transition_events: list[
        dict
    ] = []

    market_results: list[
        dict
    ] = []

    storage_results: list[
        dict
    ] = []

    for market in markets:
        store_path = (
            candle_store_directory
            / f"{market}.csv"
        )

        previous_candles = (
            read_candle_store(
                store_path,
                expected_symbol=market,
            )
        )

        candle_counts_before[
            market
        ] = len(
            previous_candles
        )

        storage_result = (
            persist_prospective_candles(
                store_path,
                market_candles[
                    market
                ],
                expected_symbol=market,
                first_eligible_market_date=(
                    first_eligible_market_date
                ),
            )
        )

        stored_candles = (
            read_candle_store(
                store_path,
                expected_symbol=market,
            )
        )

        candle_counts_after[
            market
        ] = len(
            stored_candles
        )

        try:
            (
                updated_state,
                market_result,
            ) = process_new_market_candles(
                updated_state,
                market=market,
                candles=stored_candles,
                previous_candle_count=len(
                    previous_candles
                ),
                policy_fingerprint=(
                    policy_fingerprint
                ),
            )
        except DailyTransitionError as error:
            raise TransitionCoordinatorError(
                str(error)
            ) from error

        storage_results.append(
            storage_result
        )

        market_results.append(
            market_result
        )

        transition_events.extend(
            market_result[
                "events"
            ]
        )

    verify_runtime_state(
        updated_state
    )

    journal = build_transition_journal(
        session_date=session_date,
        policy_fingerprint=(
            policy_fingerprint
        ),
        occurred_at_utc=(
            occurred_at_utc
            .astimezone(UTC)
        ),
        transition_events=(
            transition_events
        ),
        target_state=updated_state,
        candle_counts_before=(
            candle_counts_before
        ),
        candle_counts_after=(
            candle_counts_after
        ),
        completion_payload=(
            {
                **completion_payload,
                "positions_opened": sum(
                    result[
                        "positions_opened"
                    ]
                    for result in (
                        market_results
                    )
                ),
                "position_marks": sum(
                    result[
                        "position_marks"
                    ]
                    for result in (
                        market_results
                    )
                ),
                "positions_closed": sum(
                    result[
                        "positions_closed"
                    ]
                    for result in (
                        market_results
                    )
                ),
                "pending_entries": len(
                    updated_state[
                        "pending_entries"
                    ]
                ),
                "open_positions": len(
                    updated_state[
                        "open_positions"
                    ]
                ),
                "candidate_balance": (
                    updated_state[
                        "candidate_balance"
                    ]
                ),
                "shadow_balance": (
                    updated_state[
                        "shadow_balance"
                    ]
                ),
                "broker_orders_sent": 0,
            }
            if completion_payload
            is not None
            else None
        ),
    )

    write_transition_journal(
        journal_path,
        journal,
    )

    return {
        **transition_summary(
            journal=journal,
            status="PREPARED",
            journal_removed=False,
            ledger_events_appended=0,
            state_written=False,
        ),
        "storage_results": (
            storage_results
        ),
        "market_results": (
            market_results
        ),
        "runtime_state_changed": (
            updated_state
            != original_state
        ),
    }


def commit_prepared_transition(
    *,
    journal_path: Path,
    ledger_path: Path,
    state_path: Path,
    candle_store_directory: Path,
) -> dict:
    """
    Commit or recover a prepared transition.

    Recovery is idempotent at every durable journal stage:
    PREPARED, LEDGER_APPENDED and STATE_COMMITTED.
    """
    journal = read_transition_journal(
        journal_path
    )

    if journal is None:
        return {
            "status": "NO_PENDING_TRANSITION",
            "journal_removed": False,
            "ledger_events_appended": 0,
            "state_written": False,
            "broker_orders_submitted": 0,
        }

    verify_journal_candle_counts(
        journal=journal,
        candle_store_directory=(
            candle_store_directory
        ),
    )

    session_date = date.fromisoformat(
        journal[
            "session_date"
        ]
    )

    occurred_at_utc = (
        parse_utc_datetime(
            journal[
                "occurred_at_utc"
            ]
        )
    )

    ledger_events_appended = 0
    state_written = False

    if journal["stage"] == PREPARED:
        before_count = len(
            verify_ledger(
                ledger_path
            )
        )

        append_transition_events(
            ledger_path=ledger_path,
            session_date=session_date,
            transition_events=journal[
                "transition_events"
            ],
            occurred_at_utc=(
                occurred_at_utc
            ),
        )

        after_count = len(
            verify_ledger(
                ledger_path
            )
        )

        ledger_events_appended = (
            after_count
            - before_count
        )

        journal = (
            advance_transition_journal(
                journal,
                next_stage=(
                    LEDGER_APPENDED
                ),
            )
        )

        write_transition_journal(
            journal_path,
            journal,
        )

    if journal[
        "stage"
    ] == LEDGER_APPENDED:
        verify_journal_ledger_events(
            journal=journal,
            ledger_path=ledger_path,
        )

        current_state = (
            read_runtime_state(
                state_path
            )
        )

        target_state = journal[
            "target_state"
        ]

        if current_state != target_state:
            write_runtime_state(
                state_path,
                target_state,
            )

            state_written = True

        journal = (
            advance_transition_journal(
                journal,
                next_stage=(
                    STATE_COMMITTED
                ),
            )
        )

        write_transition_journal(
            journal_path,
            journal,
        )

    if journal[
        "stage"
    ] != STATE_COMMITTED:
        raise TransitionJournalError(
            "Transition did not reach the committed stage."
        )

    verify_journal_ledger_events(
        journal=journal,
        ledger_path=ledger_path,
    )

    committed_state = (
        read_runtime_state(
            state_path
        )
    )

    if committed_state != journal[
        "target_state"
    ]:
        raise TransitionCoordinatorError(
            "Runtime state does not match the committed "
            "transition journal."
        )

    completion_payload = journal[
        "completion_payload"
    ]

    if completion_payload is not None:
        append_event_once(
            ledger_path,
            "SESSION_COMPLETED",
            completion_payload,
            event_id=(
                deterministic_event_id(
                    session_date,
                    "SESSION_COMPLETED",
                )
            ),
            occurred_at_utc=(
                utc_isoformat(
                    occurred_at_utc
                )
            ),
        )

        completed_event_id = (
            deterministic_event_id(
                session_date,
                "SESSION_COMPLETED",
            )
        )

        if not any(
            event["event_id"]
            == completed_event_id
            for event in verify_ledger(
                ledger_path
            )
        ):
            raise TransitionCoordinatorError(
                "SESSION_COMPLETED could not be "
                "verified."
            )

    completed_journal = deepcopy(
        journal
    )

    remove_transition_journal(
        journal_path
    )

    return transition_summary(
        journal=completed_journal,
        status="COMMITTED",
        journal_removed=True,
        ledger_events_appended=(
            ledger_events_appended
        ),
        state_written=state_written,
    )


def run_recoverable_transition(
    *,
    journal_path: Path,
    ledger_path: Path,
    state_path: Path,
    candle_store_directory: Path,
    session_date: date,
    market_candles: dict[
        str,
        list[Candle],
    ],
    markets: list[str],
    first_eligible_market_date: date,
    policy_fingerprint: str,
    occurred_at_utc: datetime,
    initial_state: dict | None = None,
    completion_payload: dict | None = None,
) -> dict:
    """
    Recover an unfinished transition or prepare and commit a new one.
    """
    existing = read_transition_journal(
        journal_path
    )

    recovered_existing = (
        existing is not None
    )

    if existing is None:
        prepare_transition(
            journal_path=journal_path,
            state_path=state_path,
            candle_store_directory=(
                candle_store_directory
            ),
            session_date=session_date,
            market_candles=(
                market_candles
            ),
            markets=markets,
            first_eligible_market_date=(
                first_eligible_market_date
            ),
            policy_fingerprint=(
                policy_fingerprint
            ),
            occurred_at_utc=(
                occurred_at_utc
            ),
            initial_state=(
                initial_state
            ),
            completion_payload=(
                completion_payload
            ),
        )

    committed = (
        commit_prepared_transition(
            journal_path=journal_path,
            ledger_path=ledger_path,
            state_path=state_path,
            candle_store_directory=(
                candle_store_directory
            ),
        )
    )

    return {
        **committed,
        "recovered_existing_journal": (
            recovered_existing
        ),
    }
