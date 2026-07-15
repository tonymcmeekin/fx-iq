import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


GENESIS_HASH = "0" * 64

ALLOWED_EVENT_TYPES = {
    "SESSION_STARTED",
    "MARKET_DATA_COLLECTED",
    "SIGNAL_EVALUATED",
    "RISK_DECIDED",
    "PAPER_POSITION_OPENED",
    "PAPER_POSITION_MARKED",
    "PAPER_POSITION_CLOSED",
    "SESSION_COMPLETED",
    "SESSION_FAILED",
}


class LedgerIntegrityError(RuntimeError):
    """Raised when the append-only ledger fails verification."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def calculate_event_hash(
    event_without_hash: dict,
) -> str:
    return hashlib.sha256(
        canonical_json(
            event_without_hash
        ).encode("utf-8")
    ).hexdigest()


def read_events(
    ledger_path: Path,
) -> list[dict]:
    if not ledger_path.exists():
        return []

    events = []

    with ledger_path.open(
        encoding="utf-8"
    ) as ledger_file:
        for line_number, line in enumerate(
            ledger_file,
            start=1,
        ):
            stripped = line.strip()

            if not stripped:
                raise LedgerIntegrityError(
                    f"Blank ledger line at "
                    f"{line_number}."
                )

            try:
                event = json.loads(
                    stripped
                )
            except json.JSONDecodeError as error:
                raise LedgerIntegrityError(
                    f"Invalid JSON at ledger line "
                    f"{line_number}."
                ) from error

            if not isinstance(event, dict):
                raise LedgerIntegrityError(
                    f"Ledger line {line_number} "
                    "is not a JSON object."
                )

            events.append(event)

    return events


def verify_ledger(
    ledger_path: Path,
) -> list[dict]:
    events = read_events(
        ledger_path
    )

    previous_hash = GENESIS_HASH
    seen_event_ids = set()

    for expected_sequence, event in enumerate(
        events,
        start=1,
    ):
        required_fields = {
            "sequence",
            "event_id",
            "event_type",
            "occurred_at_utc",
            "previous_hash",
            "payload",
            "event_hash",
        }

        missing_fields = (
            required_fields - event.keys()
        )

        if missing_fields:
            missing = ", ".join(
                sorted(missing_fields)
            )

            raise LedgerIntegrityError(
                f"Ledger event {expected_sequence} "
                f"is missing fields: {missing}."
            )

        if event["sequence"] != (
            expected_sequence
        ):
            raise LedgerIntegrityError(
                f"Ledger sequence mismatch at "
                f"event {expected_sequence}."
            )

        event_id = event["event_id"]

        if event_id in seen_event_ids:
            raise LedgerIntegrityError(
                f"Duplicate event ID: {event_id}."
            )

        seen_event_ids.add(
            event_id
        )

        if event["event_type"] not in (
            ALLOWED_EVENT_TYPES
        ):
            raise LedgerIntegrityError(
                f"Unsupported event type: "
                f"{event['event_type']}."
            )

        if event["previous_hash"] != (
            previous_hash
        ):
            raise LedgerIntegrityError(
                f"Previous hash mismatch at "
                f"event {expected_sequence}."
            )

        event_without_hash = {
            key: value
            for key, value in event.items()
            if key != "event_hash"
        }

        calculated_hash = (
            calculate_event_hash(
                event_without_hash
            )
        )

        if event["event_hash"] != (
            calculated_hash
        ):
            raise LedgerIntegrityError(
                f"Event hash mismatch at "
                f"event {expected_sequence}."
            )

        previous_hash = (
            event["event_hash"]
        )

    return events


def append_event(
    ledger_path: Path,
    event_type: str,
    payload: dict,
    *,
    event_id: str | None = None,
    occurred_at_utc: str | None = None,
) -> dict:
    if event_type not in (
        ALLOWED_EVENT_TYPES
    ):
        raise ValueError(
            f"Unsupported event type: {event_type}."
        )

    if not isinstance(payload, dict):
        raise TypeError(
            "Ledger event payload must be a dictionary."
        )

    existing_events = verify_ledger(
        ledger_path
    )

    resolved_event_id = (
        event_id or str(uuid4())
    )

    if any(
        event["event_id"]
        == resolved_event_id
        for event in existing_events
    ):
        raise LedgerIntegrityError(
            f"Duplicate event ID: "
            f"{resolved_event_id}."
        )

    if occurred_at_utc is None:
        resolved_timestamp = (
            datetime.now(UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
    else:
        resolved_timestamp = (
            occurred_at_utc
        )

    previous_hash = (
        existing_events[-1]["event_hash"]
        if existing_events
        else GENESIS_HASH
    )

    event_without_hash = {
        "sequence": len(
            existing_events
        )
        + 1,
        "event_id": resolved_event_id,
        "event_type": event_type,
        "occurred_at_utc": (
            resolved_timestamp
        ),
        "previous_hash": previous_hash,
        "payload": payload,
    }

    event = {
        **event_without_hash,
        "event_hash": calculate_event_hash(
            event_without_hash
        ),
    }

    ledger_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    encoded_event = (
        canonical_json(event)
        + "\n"
    ).encode("utf-8")

    file_descriptor = os.open(
        ledger_path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_APPEND,
        0o600,
    )

    try:
        os.write(
            file_descriptor,
            encoded_event,
        )

        os.fsync(
            file_descriptor
        )
    finally:
        os.close(
            file_descriptor
        )

    verified_events = verify_ledger(
        ledger_path
    )

    if verified_events[-1] != event:
        raise LedgerIntegrityError(
            "Appended ledger event could not "
            "be verified."
        )

    return event
