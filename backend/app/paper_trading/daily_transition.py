from copy import deepcopy
from datetime import date
from pathlib import Path

from app.market_data.models import Candle
from app.paper_trading.candle_store import (
    persist_prospective_candles,
    read_candle_store,
)
from app.paper_trading.execution import (
    fill_pending_entry,
)
from app.paper_trading.position_lifecycle import (
    evaluate_open_position,
)
from app.paper_trading.runtime_state import (
    read_runtime_state,
    verify_runtime_state,
    write_runtime_state,
)


class DailyTransitionError(RuntimeError):
    """Raised when an offline paper transition is invalid."""


def process_new_market_candles(
    state: dict,
    *,
    market: str,
    candles: list[Candle],
    previous_candle_count: int,
    policy_fingerprint: str,
) -> tuple[dict, dict]:
    """
    Process only candles added since the previous persisted store.

    A pending entry is filled at the first complete candle after its
    signal. The position is then evaluated on that same candle so
    same-candle stop/target behaviour remains conservative.
    """
    updated_state = deepcopy(
        verify_runtime_state(
            state
        )
    )

    if previous_candle_count < 0:
        raise DailyTransitionError(
            "Previous candle count cannot be negative."
        )

    if previous_candle_count > len(
        candles
    ):
        raise DailyTransitionError(
            "Previous candle count exceeds stored candles."
        )

    for candle in candles:
        if candle.symbol != market:
            raise DailyTransitionError(
                "Transition candle market does not match "
                "the requested market."
            )

        if candle.timeframe != "D":
            raise DailyTransitionError(
                "Transition candles must use daily "
                "granularity."
            )

        if candle.timestamp.tzinfo is None:
            raise DailyTransitionError(
                "Transition candle timestamps must be "
                "timezone-aware."
            )

    timestamps = [
        candle.timestamp
        for candle in candles
    ]

    if timestamps != sorted(
        timestamps
    ):
        raise DailyTransitionError(
            "Transition candles must be chronological."
        )

    if len(timestamps) != len(
        set(timestamps)
    ):
        raise DailyTransitionError(
            "Transition candles contain duplicate "
            "timestamps."
        )

    new_candles = candles[
        previous_candle_count:
    ]

    events: list[dict] = []
    fill_results: list[dict] = []
    lifecycle_results: list[dict] = []

    for absolute_index, candle in enumerate(
        new_candles,
        start=previous_candle_count,
    ):
        available_candles = candles[
            : absolute_index + 1
        ]

        if market in updated_state[
            "pending_entries"
        ]:
            updated_state, fill_result = (
                fill_pending_entry(
                    updated_state,
                    market=market,
                    candles=available_candles,
                    policy_fingerprint=(
                        policy_fingerprint
                    ),
                )
            )

            fill_results.append(
                fill_result
            )

            if fill_result[
                "status"
            ] == "FILLED":
                events.append(
                    {
                        "event_type": (
                            "PAPER_POSITION_OPENED"
                        ),
                        "market": market,
                        "candle_timestamp": (
                            fill_result[
                                "entry_timestamp"
                            ]
                        ),
                        "payload": (
                            fill_result
                        ),
                    }
                )

        if market not in updated_state[
            "open_positions"
        ]:
            continue

        updated_state, lifecycle_result = (
            evaluate_open_position(
                updated_state,
                market=market,
                candle=candle,
            )
        )

        lifecycle_results.append(
            lifecycle_result
        )

        status = lifecycle_result[
            "status"
        ]

        if status == "OPEN":
            events.append(
                {
                    "event_type": (
                        "PAPER_POSITION_MARKED"
                    ),
                    "market": market,
                    "candle_timestamp": (
                        lifecycle_result[
                            "candle_timestamp"
                        ]
                    ),
                    "payload": (
                        lifecycle_result
                    ),
                }
            )

        elif status == "CLOSED":
            events.append(
                {
                    "event_type": (
                        "PAPER_POSITION_CLOSED"
                    ),
                    "market": market,
                    "candle_timestamp": (
                        lifecycle_result[
                            "exit_timestamp"
                        ]
                    ),
                    "payload": (
                        lifecycle_result
                    ),
                }
            )

    verify_runtime_state(
        updated_state
    )

    return updated_state, {
        "market": market,
        "previous_candle_count": (
            previous_candle_count
        ),
        "current_candle_count": len(
            candles
        ),
        "new_candles_processed": len(
            new_candles
        ),
        "fill_results": fill_results,
        "lifecycle_results": (
            lifecycle_results
        ),
        "events": events,
        "positions_opened": sum(
            event["event_type"]
            == "PAPER_POSITION_OPENED"
            for event in events
        ),
        "position_marks": sum(
            event["event_type"]
            == "PAPER_POSITION_MARKED"
            for event in events
        ),
        "positions_closed": sum(
            event["event_type"]
            == "PAPER_POSITION_CLOSED"
            for event in events
        ),
        "broker_orders_submitted": 0,
    }


def run_persisted_daily_transition(
    *,
    state_path: Path,
    candle_store_directory: Path,
    market_candles: dict[
        str,
        list[Candle],
    ],
    markets: list[str],
    first_eligible_market_date: date,
    policy_fingerprint: str,
) -> dict:
    """
    Persist candles and apply one offline state transition.

    Runtime state is written only after every market transition has
    completed successfully. No broker-order function is available.
    """
    if list(
        market_candles
    ) != markets:
        raise DailyTransitionError(
            "Market candle order must exactly match "
            "the frozen market order."
        )

    if not policy_fingerprint.strip():
        raise DailyTransitionError(
            "Policy fingerprint is required."
        )

    original_state = read_runtime_state(
        state_path
    )

    updated_state = deepcopy(
        original_state
    )

    storage_results: list[dict] = []
    market_results: list[dict] = []
    all_events: list[dict] = []

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

        updated_state, market_result = (
            process_new_market_candles(
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
        )

        storage_results.append(
            storage_result
        )

        market_results.append(
            market_result
        )

        all_events.extend(
            market_result[
                "events"
            ]
        )

    verify_runtime_state(
        updated_state
    )

    state_changed = (
        updated_state != original_state
    )

    if state_changed:
        write_runtime_state(
            state_path,
            updated_state,
        )

    return {
        "status": "COMPLETED",
        "markets": markets,
        "storage_results": (
            storage_results
        ),
        "market_results": (
            market_results
        ),
        "events": all_events,
        "candles_added": sum(
            result["candles_added"]
            for result in storage_results
        ),
        "new_candles_processed": sum(
            result[
                "new_candles_processed"
            ]
            for result in market_results
        ),
        "positions_opened": sum(
            result["positions_opened"]
            for result in market_results
        ),
        "position_marks": sum(
            result["position_marks"]
            for result in market_results
        ),
        "positions_closed": sum(
            result["positions_closed"]
            for result in market_results
        ),
        "pending_entries_total": len(
            updated_state[
                "pending_entries"
            ]
        ),
        "open_positions_total": len(
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
        "runtime_state_updated": (
            state_changed
        ),
        "broker_orders_submitted": 0,
    }
