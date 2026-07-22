from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from app.intelligence.observation_store import (
    ObservationStoreError,
    append_observation,
    read_observations,
)
from app.market_data.models import Candle
from app.paper_trading.collector import (
    collect_complete_daily_candles,
)
from app.paper_trading.policy import (
    load_json,
    verify_frozen_policy,
)
from app.paper_trading.runtime_state import (
    add_pending_entry,
    build_pending_entry,
    mark_state_updated,
    read_runtime_state,
    verify_runtime_state,
)
from app.paper_trading.session import (
    directional_close_location,
    run_daily_evaluation,
    session_is_completed,
)
from app.paper_trading.transition_coordinator import (
    commit_prepared_transition,
    run_recoverable_transition,
)
from app.paper_trading.transition_journal import (
    read_transition_journal,
)

DEFAULT_PROTOCOL_PATH = Path(
    "research_protocols/"
    "prospective_paper_trading_protocol.json"
)

DEFAULT_LEDGER_PATH = Path(
    "paper_ledger/events.jsonl"
)

DEFAULT_STATE_PATH = Path(
    "paper_ledger/state.json"
)

DEFAULT_JOURNAL_PATH = Path(
    "paper_ledger/transition.json"
)

DEFAULT_CANDLE_STORE_DIRECTORY = Path(
    "data/prospective_paper"
)

DEFAULT_OBSERVATION_STORE_PATH = Path(
    "paper_ledger/intelligence_observations.jsonl"
)

CollectorFunction = Callable[
    ...,
    list[Candle],
]


def observation_staging_path(
    store_path: Path,
    session_date: date,
) -> Path:
    return store_path.with_name(
        f".{store_path.stem}."
        f"{session_date.isoformat()}.pending.jsonl"
    )


def publish_staged_observations(
    *,
    staging_path: Path,
    store_path: Path,
    session_date: date,
) -> dict[str, int]:
    observations = read_observations(
        staging_path
    )

    if any(
        observation.session_date
        != session_date
        for observation in observations
    ):
        raise ObservationStoreError(
            "Staged observation belongs to a "
            "different session date."
        )

    published = 0
    duplicates = 0

    for observation in observations:
        try:
            append_observation(
                store_path,
                observation,
            )
            published += 1
        except ObservationStoreError as error:
            if "duplicate" not in str(error).lower():
                raise
            duplicates += 1

    staging_path.unlink(
        missing_ok=True
    )

    return {
        "observations_published": published,
        "observation_publish_duplicates": duplicates,
    }


def run_controlled_daily_session(
    *,
    api_token: str,
    session_date: date,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    candle_store_directory: Path = (
        DEFAULT_CANDLE_STORE_DIRECTORY
    ),
    observation_store_path: Path | None = (
        DEFAULT_OBSERVATION_STORE_PATH
    ),
    protocol_path: Path = DEFAULT_PROTOCOL_PATH,
    protocol: dict | None = None,
    environment: str = "practice",
    candle_count: int = 100,
    collector: CollectorFunction = (
        collect_complete_daily_candles
    ),
    policy_verifier: Callable[
        [],
        str,
    ] = verify_frozen_policy,
    preflight_runner: Callable[
        ...,
        object,
    ] | None = None,
    preflight_context: dict | None = None,
    session_time_utc: datetime | None = None,
    software_commit: str = "UNKNOWN",
) -> dict:
    """
    Run one recoverable simulation-only paper session.

    Any unfinished journal is recovered before market collection.
    SESSION_COMPLETED is appended only after transition events and
    runtime state have become durable.
    """
    if environment != "practice":
        raise RuntimeError(
            "Controlled paper sessions are restricted "
            "to the OANDA practice environment."
        )

    if not api_token.strip():
        raise ValueError(
            "OANDA API token is required."
        )

    if candle_count < 21 or candle_count > 5000:
        raise ValueError(
            "Candle count must be between 21 and 5000."
        )

    resolved_protocol = (
        protocol
        if protocol is not None
        else load_json(
            protocol_path
        )
    )

    if resolved_protocol["mode"] != (
        "SIMULATION_ONLY"
    ):
        raise RuntimeError(
            "The prospective protocol is not "
            "simulation-only."
        )

    if resolved_protocol[
        "live_order_submission_permitted"
    ]:
        raise RuntimeError(
            "The prospective protocol permits "
            "live orders."
        )

    resolved_session_time = (
        session_time_utc
        if session_time_utc is not None
        else datetime.now(UTC)
    )

    if resolved_session_time.tzinfo is None:
        raise ValueError(
            "Session time must be timezone-aware."
        )

    resolved_session_time = (
        resolved_session_time.astimezone(
            UTC
        )
    )

    policy_fingerprint = (
        policy_verifier()
    )

    existing_journal = (
        read_transition_journal(
            journal_path
        )
    )

    recovered_existing_journal = (
        existing_journal is not None
    )

    if existing_journal is not None:
        journal_policy = existing_journal[
            "policy_fingerprint"
        ]

        if journal_policy != (
            policy_fingerprint
        ):
            raise RuntimeError(
                "Unfinished transition journal uses "
                "a different policy fingerprint."
            )

        commit_prepared_transition(
            journal_path=journal_path,
            ledger_path=ledger_path,
            state_path=state_path,
            candle_store_directory=(
                candle_store_directory
            ),
        )

    if session_is_completed(
        ledger_path,
        session_date,
    ):
        publish_summary = {
            "observations_published": 0,
            "observation_publish_duplicates": 0,
        }

        if observation_store_path is not None:
            staging_path = observation_staging_path(
                observation_store_path,
                session_date,
            )

            if staging_path.exists():
                publish_summary = (
                    publish_staged_observations(
                        staging_path=staging_path,
                        store_path=(
                            observation_store_path
                        ),
                        session_date=session_date,
                    )
                )

        state = read_runtime_state(
            state_path
        )

        return {
            "status": "ALREADY_COMPLETED",
            "session_date": (
                session_date.isoformat()
            ),
            "policy_fingerprint": (
                policy_fingerprint
            ),
            "runtime_state_updated": False,
            "recovered_existing_journal": (
                recovered_existing_journal
            ),
            "pending_entries_total": len(
                state[
                    "pending_entries"
                ]
            ),
            "open_positions_total": len(
                state[
                    "open_positions"
                ]
            ),
            "candidate_balance": (
                state[
                    "candidate_balance"
                ]
            ),
            "shadow_balance": (
                state[
                    "shadow_balance"
                ]
            ),
            "broker_orders_sent": 0,
            **publish_summary,
        }

    state = read_runtime_state(
        state_path
    )

    if state["broker_orders_sent"] != 0:
        raise RuntimeError(
            "Runtime state records broker orders."
        )

    if preflight_runner is not None:
        preflight_report = preflight_runner(
            **(preflight_context or {})
        )

        if not getattr(
            preflight_report,
            "passed",
            False,
        ):
            failed_checks = getattr(
                preflight_report,
                "failed_checks",
                (),
            )

            failure_details = "; ".join(
                f"{check.name}: {check.message}"
                for check in failed_checks
            )

            message = (
                "Paper session aborted: "
                "preflight failed."
            )

            if failure_details:
                message = (
                    f"{message} {failure_details}"
                )

            raise RuntimeError(message)

    market_candles: dict[
        str,
        list[Candle],
    ] = {}

    markets = resolved_protocol[
        "markets"
    ]

    for market in markets:
        candles = collector(
            api_token=api_token,
            instrument=market,
            environment="practice",
            count=candle_count,
        )

        if not candles:
            raise ValueError(
                f"No complete candles collected for "
                f"{market}."
            )

        market_candles[
            market
        ] = candles

    staging_path = (
        observation_staging_path(
            observation_store_path,
            session_date,
        )
        if observation_store_path is not None
        else None
    )

    evaluation = run_daily_evaluation(
        ledger_path=ledger_path,
        session_date=session_date,
        market_candles=market_candles,
        protocol=resolved_protocol,
        policy_verifier=(
            lambda: policy_fingerprint
        ),
        session_time_utc=(
            resolved_session_time
        ),
        software_commit=(
            software_commit
        ),
        observation_store_path=(
            staging_path
        ),
        append_completion_event=False,
    )

    if evaluation["status"] != (
        "EVALUATED"
    ):
        raise RuntimeError(
            "Session evaluation did not reach "
            "the expected pre-commit state."
        )

    staged_state = state

    for market_summary in (
        evaluation["markets"]
    ):
        if not market_summary[
            "pending_entry"
        ]:
            continue

        market = market_summary[
            "market"
        ]

        if (
            market in staged_state[
                "pending_entries"
            ]
            or market in staged_state[
                "open_positions"
            ]
        ):
            continue

        latest_candle = (
            market_candles[
                market
            ][-1]
        )

        pending_entry = (
            build_pending_entry(
                market=market,
                signal_candle_timestamp=(
                    latest_candle.timestamp
                ),
                direction=(
                    market_summary[
                        "direction"
                    ]
                ),
                candidate_risk_percent=(
                    market_summary[
                        "candidate_risk_percent"
                    ]
                ),
                shadow_risk_percent=(
                    market_summary[
                        "shadow_risk_percent"
                    ]
                ),
                directional_close_location=(
                    directional_close_location(
                        latest_candle,
                        market_summary[
                            "direction"
                        ],
                    )
                ),
                policy_fingerprint=(
                    policy_fingerprint
                ),
                created_session_date=(
                    session_date.isoformat()
                ),
            )
        )

        staged_state = add_pending_entry(
            staged_state,
            pending_entry,
        )

    staged_state = mark_state_updated(
        staged_state,
        updated_at_utc=(
            resolved_session_time
        ),
        completed_session_date=(
            session_date.isoformat()
        ),
    )

    verify_runtime_state(
        staged_state
    )

    first_eligible_market_date = (
        date.fromisoformat(
            resolved_protocol[
                "prospective_period"
            ][
                "first_eligible_market_date"
            ]
        )
    )

    transition = (
        run_recoverable_transition(
            journal_path=journal_path,
            ledger_path=ledger_path,
            state_path=state_path,
            candle_store_directory=(
                candle_store_directory
            ),
            session_date=session_date,
            market_candles=market_candles,
            markets=markets,
            first_eligible_market_date=(
                first_eligible_market_date
            ),
            policy_fingerprint=(
                policy_fingerprint
            ),
            occurred_at_utc=(
                resolved_session_time
            ),
            initial_state=(
                staged_state
            ),
            completion_payload=(
                evaluation[
                    "completion_payload"
                ]
            ),
        )
    )

    committed_state = (
        read_runtime_state(
            state_path
        )
    )

    if not session_is_completed(
        ledger_path,
        session_date,
    ):
        raise RuntimeError(
            "Controlled session did not append its "
            "final completion event."
        )

    publish_summary = {
        "observations_published": 0,
        "observation_publish_duplicates": 0,
    }

    if (
        observation_store_path is not None
        and staging_path is not None
    ):
        publish_summary = (
            publish_staged_observations(
                staging_path=staging_path,
                store_path=observation_store_path,
                session_date=session_date,
            )
        )

    return {
        **evaluation,
        **transition,
        "status": "COMPLETED",
        "runtime_state_updated": (
            committed_state != state
        ),
        "recovered_existing_journal": (
            recovered_existing_journal
            or transition[
                "recovered_existing_journal"
            ]
        ),
        "pending_entries_total": len(
            committed_state[
                "pending_entries"
            ]
        ),
        "open_positions_total": len(
            committed_state[
                "open_positions"
            ]
        ),
        "candidate_balance": (
            committed_state[
                "candidate_balance"
            ]
        ),
        "shadow_balance": (
            committed_state[
                "shadow_balance"
            ]
        ),
        "broker_orders_sent": 0,
        **publish_summary,
    }
