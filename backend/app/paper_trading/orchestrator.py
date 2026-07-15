from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

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
    write_runtime_state,
)
from app.paper_trading.session import (
    run_daily_evaluation,
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

CollectorFunction = Callable[
    ...,
    list[Candle],
]


def run_controlled_daily_session(
    *,
    api_token: str,
    session_date: date,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
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
    session_time_utc: datetime | None = None,
    software_commit: str = "UNKNOWN",
) -> dict:
    """
    Run one simulation-only prospective paper session.

    The collector is dependency-injected so tests can operate
    entirely offline. This function never submits broker orders.
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

    state = read_runtime_state(
        state_path
    )

    if state["broker_orders_sent"] != 0:
        raise RuntimeError(
            "Runtime state records broker orders."
        )

    market_candles: dict[
        str,
        list[Candle],
    ] = {}

    for market in resolved_protocol[
        "markets"
    ]:
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

    session_result = (
        run_daily_evaluation(
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
        )
    )

    if session_result["status"] == (
        "ALREADY_COMPLETED"
    ):
        return {
            **session_result,
            "runtime_state_updated": False,
            "broker_orders_sent": 0,
        }

    updated_state = state

    for market_summary in (
        session_result["markets"]
    ):
        if not market_summary[
            "pending_entry"
        ]:
            continue

        market = market_summary[
            "market"
        ]

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
                    (
                        latest_candle.close
                        - latest_candle.low
                    )
                    / (
                        latest_candle.high
                        - latest_candle.low
                    )
                    if (
                        market_summary[
                            "direction"
                        ]
                        == "BUY"
                        and latest_candle.high
                        != latest_candle.low
                    )
                    else (
                        (
                            latest_candle.high
                            - latest_candle.close
                        )
                        / (
                            latest_candle.high
                            - latest_candle.low
                        )
                        if (
                            market_summary[
                                "direction"
                            ]
                            == "SELL"
                            and latest_candle.high
                            != latest_candle.low
                        )
                        else 0.5
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

        updated_state = (
            add_pending_entry(
                updated_state,
                pending_entry,
            )
        )

    updated_state = (
        mark_state_updated(
            updated_state,
            updated_at_utc=(
                resolved_session_time
            ),
            completed_session_date=(
                session_date.isoformat()
            ),
        )
    )

    write_runtime_state(
        state_path,
        updated_state,
    )

    return {
        **session_result,
        "runtime_state_updated": True,
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
        "broker_orders_sent": (
            updated_state[
                "broker_orders_sent"
            ]
        ),
    }
