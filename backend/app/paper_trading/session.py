import hashlib
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from app.intelligence.observation_store import (
    ObservationStoreError,
    append_observation,
)
from app.intelligence.observations import (
    PortfolioContext,
    build_trade_observation,
)
from app.market_data.models import Candle
from app.paper_trading.ledger import (
    LedgerIntegrityError,
    append_event,
    verify_ledger,
)
from app.paper_trading.policy import (
    BASE_RISK_PERCENT,
    calculate_validated_close_location_risk,
    load_json,
    verify_frozen_policy,
)
from app.strategies.atr_breakout import (
    generate_atr_breakout_signal,
)

DEFAULT_PROTOCOL_PATH = Path(
    "research_protocols/"
    "prospective_paper_trading_protocol.json"
)


def utc_isoformat(
    value: datetime,
) -> str:
    if value.tzinfo is None:
        raise ValueError(
            "Datetime must be timezone-aware."
        )

    return (
        value.astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def deterministic_event_id(
    session_date: date,
    event_type: str,
    *,
    market: str | None = None,
    candle_timestamp: datetime | None = None,
) -> str:
    components = [
        session_date.isoformat(),
        event_type,
        market or "",
        (
            utc_isoformat(candle_timestamp)
            if candle_timestamp
            else ""
        ),
    ]

    identity = "|".join(
        components
    )

    digest = hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()

    return f"paper-{digest}"


def directional_close_location(
    candle: Candle,
    direction: str,
) -> float:
    candle_range = (
        candle.high - candle.low
    )

    if candle_range == 0:
        return 0.5

    if direction == "BUY":
        value = (
            candle.close - candle.low
        ) / candle_range

    elif direction == "SELL":
        value = (
            candle.high - candle.close
        ) / candle_range

    else:
        raise ValueError(
            "Direction must be BUY or SELL."
        )

    return float(value)


def validate_market_candles(
    market: str,
    candles: list[Candle],
    *,
    session_time_utc: datetime,
    first_eligible_market_date: date,
) -> None:
    if not candles:
        raise ValueError(
            f"No candles supplied for {market}."
        )

    timestamps = [
        candle.timestamp.astimezone(UTC)
        for candle in candles
    ]

    if timestamps != sorted(timestamps):
        raise ValueError(
            f"Candles are not chronological for {market}."
        )

    if len(timestamps) != len(
        set(timestamps)
    ):
        raise ValueError(
            f"Duplicate candle timestamps for {market}."
        )

    for candle in candles:
        if candle.symbol != market:
            raise ValueError(
                f"Candle symbol mismatch for {market}: "
                f"{candle.symbol}."
            )

        if candle.timeframe != "D":
            raise ValueError(
                f"Candle timeframe must be D for {market}."
            )

        if candle.timestamp.tzinfo is None:
            raise ValueError(
                f"Candle timestamp is timezone-naive "
                f"for {market}."
            )

        if candle.timestamp.astimezone(
            UTC
        ) > session_time_utc:
            raise ValueError(
                f"Future candle supplied for {market}."
            )

    latest_candle_date = (
        candles[-1]
        .timestamp
        .astimezone(UTC)
        .date()
    )

    if latest_candle_date < (
        first_eligible_market_date
    ):
        raise ValueError(
            f"Latest candle for {market} predates "
            "the prospective test."
        )


def append_event_once(
    ledger_path: Path,
    event_type: str,
    payload: dict,
    *,
    event_id: str,
    occurred_at_utc: str,
) -> dict:
    events = verify_ledger(
        ledger_path
    )

    matches = [
        event
        for event in events
        if event["event_id"] == event_id
    ]

    if matches:
        existing = matches[0]

        if (
            existing["event_type"]
            != event_type
            or existing["payload"]
            != payload
        ):
            raise LedgerIntegrityError(
                "Deterministic event ID already exists "
                "with different content."
            )

        return existing

    return append_event(
        ledger_path=ledger_path,
        event_type=event_type,
        payload=payload,
        event_id=event_id,
        occurred_at_utc=occurred_at_utc,
    )


def session_is_completed(
    ledger_path: Path,
    session_date: date,
) -> bool:
    expected_event_id = (
        deterministic_event_id(
            session_date,
            "SESSION_COMPLETED",
        )
    )

    return any(
        event["event_id"]
        == expected_event_id
        for event in verify_ledger(
            ledger_path
        )
    )


def run_daily_evaluation(
    ledger_path: Path,
    session_date: date,
    market_candles: dict[
        str,
        list[Candle],
    ],
    *,
    protocol: dict | None = None,
    policy_verifier: Callable[
        [],
        str,
    ] = verify_frozen_policy,
    session_time_utc: datetime | None = None,
    software_commit: str = "UNKNOWN",
    append_completion_event: bool = True,
    observation_store_path: Path | None = None,
) -> dict:
    resolved_protocol = (
        protocol
        if protocol is not None
        else load_json(
            DEFAULT_PROTOCOL_PATH
        )
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

    occurred_at = utc_isoformat(
        resolved_session_time
    )

    if resolved_protocol["mode"] != (
        "SIMULATION_ONLY"
    ):
        raise RuntimeError(
            "Paper session protocol is not "
            "simulation-only."
        )

    if resolved_protocol[
        "live_order_submission_permitted"
    ]:
        raise RuntimeError(
            "Paper session protocol permits "
            "live orders."
        )

    first_eligible_date = (
        date.fromisoformat(
            resolved_protocol[
                "prospective_period"
            ][
                "first_eligible_market_date"
            ]
        )
    )

    if session_date < first_eligible_date:
        raise ValueError(
            "Session date predates the prospective "
            "paper-test start date."
        )

    if session_date > (
        resolved_session_time.date()
    ):
        raise ValueError(
            "Session date cannot be in the future."
        )

    required_markets = (
        resolved_protocol["markets"]
    )

    supplied_markets = list(
        market_candles
    )

    if supplied_markets != required_markets:
        raise ValueError(
            "Supplied market order must exactly match "
            "the frozen protocol market order."
        )

    policy_fingerprint = (
        policy_verifier()
    )

    if session_is_completed(
        ledger_path,
        session_date,
    ):
        events = verify_ledger(
            ledger_path
        )

        return {
            "status": "ALREADY_COMPLETED",
            "session_date": (
                session_date.isoformat()
            ),
            "events_total": len(events),
            "policy_fingerprint": (
                policy_fingerprint
            ),
        }

    start_payload = {
        "session_date": (
            session_date.isoformat()
        ),
        "mode": "SIMULATION_ONLY",
        "software_commit": software_commit,
        "policy_fingerprint": (
            policy_fingerprint
        ),
        "markets": required_markets,
        "broker_orders_sent": 0,
    }

    append_event_once(
        ledger_path,
        "SESSION_STARTED",
        start_payload,
        event_id=deterministic_event_id(
            session_date,
            "SESSION_STARTED",
        ),
        occurred_at_utc=occurred_at,
    )

    market_summaries = []

    observation_metrics = {
        "observations_attempted": 0,
        "observations_recorded": 0,
        "observation_duplicates": 0,
        "observation_failures": 0,
        "observation_errors": [],
    }

    try:
        for market in required_markets:
            candles = market_candles[
                market
            ]

            validate_market_candles(
                market,
                candles,
                session_time_utc=(
                    resolved_session_time
                ),
                first_eligible_market_date=(
                    first_eligible_date
                ),
            )

            latest = candles[-1]

            market_data_payload = {
                "session_date": (
                    session_date.isoformat()
                ),
                "market": market,
                "timeframe": "D",
                "price_component": "midpoint",
                "complete_candles_only": True,
                "candles_available": len(
                    candles
                ),
                "latest_candle_timestamp": (
                    utc_isoformat(
                        latest.timestamp
                    )
                ),
                "latest_candle": {
                    "open": latest.open,
                    "high": latest.high,
                    "low": latest.low,
                    "close": latest.close,
                    "volume": latest.volume,
                },
            }

            append_event_once(
                ledger_path,
                "MARKET_DATA_COLLECTED",
                market_data_payload,
                event_id=(
                    deterministic_event_id(
                        session_date,
                        "MARKET_DATA_COLLECTED",
                        market=market,
                        candle_timestamp=(
                            latest.timestamp
                        ),
                    )
                ),
                occurred_at_utc=occurred_at,
            )

            signal = (
                generate_atr_breakout_signal(
                    candles
                )
            )

            signal_payload = {
                "session_date": (
                    session_date.isoformat()
                ),
                "market": market,
                "candle_timestamp": (
                    utc_isoformat(
                        latest.timestamp
                    )
                ),
                "strategy_name": (
                    "atr_breakout"
                ),
                "direction": (
                    signal.direction
                ),
                "confidence": (
                    signal.confidence
                ),
                "reason": signal.reason,
                "candidate_and_shadow_signal_equal": (
                    True
                ),
            }

            append_event_once(
                ledger_path,
                "SIGNAL_EVALUATED",
                signal_payload,
                event_id=(
                    deterministic_event_id(
                        session_date,
                        "SIGNAL_EVALUATED",
                        market=market,
                        candle_timestamp=(
                            latest.timestamp
                        ),
                    )
                ),
                occurred_at_utc=occurred_at,
            )

            summary = {
                "market": market,
                "candle_timestamp": (
                    utc_isoformat(
                        latest.timestamp
                    )
                ),
                "strategy_name": (
                    signal.strategy_name
                ),
                "direction": (
                    signal.direction
                ),
                "confidence": (
                    signal.confidence
                ),
                "reason": signal.reason,
                "candidate_risk_percent": (
                    None
                ),
                "shadow_risk_percent": (
                    None
                ),
                "pending_entry": False,
            }

            if signal.direction in {
                "BUY",
                "SELL",
            }:
                close_location = (
                    directional_close_location(
                        latest,
                        signal.direction,
                    )
                )

                risk_decision = (
                    calculate_validated_close_location_risk(
                        close_location,
                        base_risk_percent=(
                            BASE_RISK_PERCENT
                        ),
                    )
                )

                risk_payload = {
                    "session_date": (
                        session_date.isoformat()
                    ),
                    "market": market,
                    "candle_timestamp": (
                        utc_isoformat(
                            latest.timestamp
                        )
                    ),
                    "direction": (
                        signal.direction
                    ),
                    "directional_close_location": (
                        risk_decision
                        .directional_close_location
                    ),
                    "threshold": (
                        risk_decision.threshold
                    ),
                    "candidate_risk_percent": (
                        risk_decision
                        .adjusted_risk_percent
                    ),
                    "shadow_risk_percent": (
                        BASE_RISK_PERCENT
                    ),
                    "risk_reduced": (
                        risk_decision
                        .risk_reduced
                    ),
                    "reason": (
                        risk_decision.reason
                    ),
                    "entry_status": (
                        "PENDING_NEXT_COMPLETE_CANDLE"
                    ),
                    "broker_order_submitted": (
                        False
                    ),
                }

                append_event_once(
                    ledger_path,
                    "RISK_DECIDED",
                    risk_payload,
                    event_id=(
                        deterministic_event_id(
                            session_date,
                            "RISK_DECIDED",
                            market=market,
                            candle_timestamp=(
                                latest.timestamp
                            ),
                        )
                    ),
                    occurred_at_utc=(
                        occurred_at
                    ),
                )

                summary[
                    "candidate_risk_percent"
                ] = (
                    risk_decision
                    .adjusted_risk_percent
                )

                summary[
                    "shadow_risk_percent"
                ] = BASE_RISK_PERCENT

                summary[
                    "pending_entry"
                ] = True

            market_summaries.append(
                summary
            )

            if observation_store_path is not None:
                observation_metrics[
                    "observations_attempted"
                ] += 1

                try:
                    pending_entries_total = sum(
                        bool(
                            item[
                                "pending_entry"
                            ]
                        )
                        for item
                        in market_summaries
                    )

                    portfolio_risk_percent = sum(
                        float(
                            item[
                                "candidate_risk_percent"
                            ]
                            or 0.0
                        )
                        for item
                        in market_summaries
                        if item[
                            "pending_entry"
                        ]
                    )

                    observation = (
                        build_trade_observation(
                            session_date=(
                                session_date
                            ),
                            recorded_at_utc=(
                                occurred_at
                            ),
                            candles=candles,
                            signal=signal,
                            trade_accepted=bool(
                                summary[
                                    "pending_entry"
                                ]
                            ),
                            decision_reason=str(
                                summary[
                                    "reason"
                                ]
                            ),
                            portfolio_context=(
                                PortfolioContext(
                                    pending_entries_total=(
                                        pending_entries_total
                                    ),
                                    open_positions_total=0,
                                    correlated_positions=0,
                                    portfolio_risk_percent=(
                                        portfolio_risk_percent
                                    ),
                                )
                            ),
                        )
                    )

                    append_observation(
                        observation_store_path,
                        observation,
                    )

                    observation_metrics[
                        "observations_recorded"
                    ] += 1

                except ObservationStoreError as error:
                    message = str(error)

                    if "duplicate" in message.lower():
                        observation_metrics[
                            "observation_duplicates"
                        ] += 1
                    else:
                        observation_metrics[
                            "observation_failures"
                        ] += 1
                        observation_metrics[
                            "observation_errors"
                        ].append(
                            {
                                "market": market,
                                "error_type": (
                                    type(error).__name__
                                ),
                                "error_message": (
                                    message
                                ),
                            }
                        )

                except Exception as error:
                    observation_metrics[
                        "observation_failures"
                    ] += 1
                    observation_metrics[
                        "observation_errors"
                    ].append(
                        {
                            "market": market,
                            "error_type": (
                                type(error).__name__
                            ),
                            "error_message": (
                                str(error)
                            ),
                        }
                    )

        actionable_signals = sum(
            summary["direction"]
            in {"BUY", "SELL"}
            for summary in market_summaries
        )

        completion_payload = {
            "session_date": (
                session_date.isoformat()
            ),
            "status": "SUCCESS",
            "markets_processed": len(
                market_summaries
            ),
            "actionable_signals": (
                actionable_signals
            ),
            "pending_entries": (
                actionable_signals
            ),
            "positions_opened": 0,
            "positions_closed": 0,
            "broker_orders_sent": 0,
            "market_summaries": (
                market_summaries
            ),
            **observation_metrics,
        }

        if append_completion_event:
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
                occurred_at_utc=occurred_at,
            )

    except Exception as error:
        failure_payload = {
            "session_date": (
                session_date.isoformat()
            ),
            "status": "FAILED",
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
            "broker_orders_sent": 0,
        }

        failure_event_id = (
            deterministic_event_id(
                session_date,
                "SESSION_FAILED",
            )
        )

        try:
            append_event_once(
                ledger_path,
                "SESSION_FAILED",
                failure_payload,
                event_id=failure_event_id,
                occurred_at_utc=(
                    occurred_at
                ),
            )
        except LedgerIntegrityError:
            pass

        raise

    events = verify_ledger(
        ledger_path
    )

    return {
        "status": (
            "COMPLETED"
            if append_completion_event
            else "EVALUATED"
        ),
        "session_date": (
            session_date.isoformat()
        ),
        "events_total": len(events),
        "policy_fingerprint": (
            policy_fingerprint
        ),
        "markets": market_summaries,
        "completion_payload": (
            completion_payload
        ),
        "completion_event_appended": (
            append_completion_event
        ),
        **observation_metrics,
    }
