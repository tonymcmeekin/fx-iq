from datetime import UTC, date, datetime
from pathlib import Path

from app.paper_trading.ledger import (
    LedgerIntegrityError,
    verify_ledger,
)
from app.paper_trading.session import (
    append_event_once,
    deterministic_event_id,
    utc_isoformat,
)

POSITION_EVENT_TYPES = {
    "PAPER_POSITION_OPENED",
    "PAPER_POSITION_MARKED",
    "PAPER_POSITION_CLOSED",
}


class TransitionLedgerError(RuntimeError):
    """Raised when transition ledger events are invalid."""


def parse_event_timestamp(
    value: str,
) -> datetime:
    if not isinstance(value, str):
        raise TransitionLedgerError(
            "Transition event timestamp must be a string."
        )

    try:
        parsed = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )
    except ValueError as error:
        raise TransitionLedgerError(
            "Transition event timestamp is invalid."
        ) from error

    if parsed.tzinfo is None:
        raise TransitionLedgerError(
            "Transition event timestamp must be "
            "timezone-aware."
        )

    return parsed.astimezone(
        UTC
    )


def validate_transition_event(
    event: dict,
) -> dict:
    if not isinstance(event, dict):
        raise TransitionLedgerError(
            "Transition event must be a dictionary."
        )

    required_fields = {
        "event_type",
        "market",
        "candle_timestamp",
        "payload",
    }

    missing = (
        required_fields - event.keys()
    )

    if missing:
        raise TransitionLedgerError(
            "Transition event is missing fields: "
            + ", ".join(sorted(missing))
            + "."
        )

    event_type = event[
        "event_type"
    ]

    if event_type not in (
        POSITION_EVENT_TYPES
    ):
        raise TransitionLedgerError(
            "Unsupported transition event type: "
            f"{event_type}."
        )

    market = event[
        "market"
    ]

    if (
        not isinstance(market, str)
        or not market.strip()
    ):
        raise TransitionLedgerError(
            "Transition event market is required."
        )

    if not isinstance(
        event["payload"],
        dict,
    ):
        raise TransitionLedgerError(
            "Transition event payload must be a dictionary."
        )

    payload_market = event[
        "payload"
    ].get(
        "market"
    )

    if (
        payload_market is not None
        and payload_market != market
    ):
        raise TransitionLedgerError(
            "Transition event market does not match "
            "its payload."
        )

    timestamp = parse_event_timestamp(
        event[
            "candle_timestamp"
        ]
    )

    return {
        "event_type": event_type,
        "market": market,
        "candle_timestamp": (
            utc_isoformat(
                timestamp
            )
        ),
        "payload": event[
            "payload"
        ],
    }


def transition_event_id(
    *,
    session_date: date,
    event: dict,
) -> str:
    validated = (
        validate_transition_event(
            event
        )
    )

    timestamp = parse_event_timestamp(
        validated[
            "candle_timestamp"
        ]
    )

    return deterministic_event_id(
        session_date,
        validated[
            "event_type"
        ],
        market=validated[
            "market"
        ],
        candle_timestamp=timestamp,
    )


def append_transition_events(
    *,
    ledger_path: Path,
    session_date: date,
    transition_events: list[dict],
    occurred_at_utc: datetime,
) -> list[dict]:
    """
    Append transition events using deterministic identities.

    Replaying the same transition is safe. A deterministic identity
    that already exists with different content is rejected by the
    underlying append_event_once integrity check.
    """
    if occurred_at_utc.tzinfo is None:
        raise ValueError(
            "Occurred-at time must be timezone-aware."
        )

    occurred_at = utc_isoformat(
        occurred_at_utc
    )

    validated_events = [
        validate_transition_event(
            event
        )
        for event in transition_events
    ]

    event_ids = [
        transition_event_id(
            session_date=session_date,
            event=event,
        )
        for event in validated_events
    ]

    if len(event_ids) != len(
        set(event_ids)
    ):
        raise TransitionLedgerError(
            "Transition contains duplicate deterministic "
            "event identities."
        )

    appended_events = []

    for event, event_id in zip(
        validated_events,
        event_ids,
        strict=True,
    ):
        appended = append_event_once(
            ledger_path,
            event[
                "event_type"
            ],
            event[
                "payload"
            ],
            event_id=event_id,
            occurred_at_utc=occurred_at,
        )

        appended_events.append(
            appended
        )

    verified_events = verify_ledger(
        ledger_path
    )

    verified_by_id = {
        event["event_id"]: event
        for event in verified_events
    }

    for event_id, appended in zip(
        event_ids,
        appended_events,
        strict=True,
    ):
        if (
            event_id not in verified_by_id
            or verified_by_id[
                event_id
            ] != appended
        ):
            raise LedgerIntegrityError(
                "Transition ledger event could not "
                "be verified."
            )

    return appended_events
