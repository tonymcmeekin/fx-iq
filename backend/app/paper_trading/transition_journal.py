import hashlib
import json
import os
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path

from app.paper_trading.runtime_state import (
    verify_runtime_state,
)
from app.paper_trading.transition_ledger import (
    validate_transition_event,
)


JOURNAL_VERSION = "1.0"

PREPARED = "PREPARED"
LEDGER_APPENDED = "LEDGER_APPENDED"
STATE_COMMITTED = "STATE_COMMITTED"

JOURNAL_STAGES = (
    PREPARED,
    LEDGER_APPENDED,
    STATE_COMMITTED,
)


class TransitionJournalError(RuntimeError):
    """Raised when a transition journal is invalid."""


def canonical_json(
    value: object,
) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
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


def parse_utc_datetime(
    value: str,
) -> datetime:
    if not isinstance(value, str):
        raise TransitionJournalError(
            "Journal datetime must be a string."
        )

    try:
        parsed = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )
    except ValueError as error:
        raise TransitionJournalError(
            "Journal datetime is invalid."
        ) from error

    if parsed.tzinfo is None:
        raise TransitionJournalError(
            "Journal datetime must be timezone-aware."
        )

    return parsed.astimezone(
        UTC
    )


def calculate_journal_checksum(
    journal_without_checksum: dict,
) -> str:
    return hashlib.sha256(
        canonical_json(
            journal_without_checksum
        ).encode("utf-8")
    ).hexdigest()


def build_transition_journal(
    *,
    session_date: date,
    policy_fingerprint: str,
    occurred_at_utc: datetime,
    transition_events: list[dict],
    target_state: dict,
    candle_counts_before: dict[str, int],
    candle_counts_after: dict[str, int],
    completion_payload: dict | None = None,
) -> dict:
    if not policy_fingerprint.strip():
        raise TransitionJournalError(
            "Policy fingerprint is required."
        )

    if occurred_at_utc.tzinfo is None:
        raise ValueError(
            "Occurred-at time must be timezone-aware."
        )

    validated_events = [
        validate_transition_event(
            event
        )
        for event in transition_events
    ]

    if (
        completion_payload is not None
        and not isinstance(
            completion_payload,
            dict,
        )
    ):
        raise TransitionJournalError(
            "Completion payload must be a dictionary."
        )

    verified_state = deepcopy(
        verify_runtime_state(
            target_state
        )
    )

    if not isinstance(
        candle_counts_before,
        dict,
    ) or not isinstance(
        candle_counts_after,
        dict,
    ):
        raise TransitionJournalError(
            "Candle counts must be dictionaries."
        )

    before_markets = list(
        candle_counts_before
    )

    after_markets = list(
        candle_counts_after
    )

    if before_markets != after_markets:
        raise TransitionJournalError(
            "Before and after candle-count markets "
            "must match in order."
        )

    for market in before_markets:
        before_count = candle_counts_before[
            market
        ]

        after_count = candle_counts_after[
            market
        ]

        if (
            not isinstance(before_count, int)
            or isinstance(before_count, bool)
            or before_count < 0
        ):
            raise TransitionJournalError(
                f"Invalid before candle count for "
                f"{market}."
            )

        if (
            not isinstance(after_count, int)
            or isinstance(after_count, bool)
            or after_count < before_count
        ):
            raise TransitionJournalError(
                f"Invalid after candle count for "
                f"{market}."
            )

    journal_without_checksum = {
        "journal_version": (
            JOURNAL_VERSION
        ),
        "stage": PREPARED,
        "session_date": (
            session_date.isoformat()
        ),
        "policy_fingerprint": (
            policy_fingerprint
        ),
        "occurred_at_utc": (
            utc_isoformat(
                occurred_at_utc
            )
        ),
        "transition_events": (
            validated_events
        ),
        "target_state": (
            verified_state
        ),
        "candle_counts_before": (
            deepcopy(
                candle_counts_before
            )
        ),
        "candle_counts_after": (
            deepcopy(
                candle_counts_after
            )
        ),
        "completion_payload": (
            deepcopy(
                completion_payload
            )
            if completion_payload
            is not None
            else None
        ),
        "broker_orders_submitted": 0,
    }

    return {
        **journal_without_checksum,
        "checksum": (
            calculate_journal_checksum(
                journal_without_checksum
            )
        ),
    }


def verify_transition_journal(
    journal: dict,
) -> dict:
    if not isinstance(journal, dict):
        raise TransitionJournalError(
            "Transition journal must be a dictionary."
        )

    required_fields = {
        "journal_version",
        "stage",
        "session_date",
        "policy_fingerprint",
        "occurred_at_utc",
        "transition_events",
        "target_state",
        "candle_counts_before",
        "candle_counts_after",
        "completion_payload",
        "broker_orders_submitted",
        "checksum",
    }

    missing = (
        required_fields - journal.keys()
    )

    if missing:
        raise TransitionJournalError(
            "Transition journal is missing fields: "
            + ", ".join(sorted(missing))
            + "."
        )

    if journal[
        "journal_version"
    ] != JOURNAL_VERSION:
        raise TransitionJournalError(
            "Unsupported transition-journal version."
        )

    if journal["stage"] not in (
        JOURNAL_STAGES
    ):
        raise TransitionJournalError(
            "Unsupported transition-journal stage."
        )

    try:
        parsed_session_date = (
            date.fromisoformat(
                journal[
                    "session_date"
                ]
            )
        )
    except (
        TypeError,
        ValueError,
    ) as error:
        raise TransitionJournalError(
            "Journal session date is invalid."
        ) from error

    parse_utc_datetime(
        journal[
            "occurred_at_utc"
        ]
    )

    policy_fingerprint = journal[
        "policy_fingerprint"
    ]

    if (
        not isinstance(
            policy_fingerprint,
            str,
        )
        or not policy_fingerprint.strip()
    ):
        raise TransitionJournalError(
            "Journal policy fingerprint is invalid."
        )

    if not isinstance(
        journal[
            "transition_events"
        ],
        list,
    ):
        raise TransitionJournalError(
            "Journal transition events must be a list."
        )

    validated_events = [
        validate_transition_event(
            event
        )
        for event in journal[
            "transition_events"
        ]
    ]

    verified_state = deepcopy(
        verify_runtime_state(
            journal[
                "target_state"
            ]
        )
    )

    completion_payload = journal[
        "completion_payload"
    ]

    if (
        completion_payload is not None
        and not isinstance(
            completion_payload,
            dict,
        )
    ):
        raise TransitionJournalError(
            "Journal completion payload must be "
            "a dictionary."
        )

    before = journal[
        "candle_counts_before"
    ]

    after = journal[
        "candle_counts_after"
    ]

    if (
        not isinstance(before, dict)
        or not isinstance(after, dict)
    ):
        raise TransitionJournalError(
            "Journal candle counts must be dictionaries."
        )

    if list(before) != list(after):
        raise TransitionJournalError(
            "Journal candle-count markets do not match."
        )

    for market in before:
        before_count = before[
            market
        ]

        after_count = after[
            market
        ]

        if (
            not isinstance(before_count, int)
            or isinstance(before_count, bool)
            or before_count < 0
        ):
            raise TransitionJournalError(
                f"Invalid journal before count for "
                f"{market}."
            )

        if (
            not isinstance(after_count, int)
            or isinstance(after_count, bool)
            or after_count < before_count
        ):
            raise TransitionJournalError(
                f"Invalid journal after count for "
                f"{market}."
            )

    if journal[
        "broker_orders_submitted"
    ] != 0:
        raise TransitionJournalError(
            "Transition journal records broker orders."
        )

    journal_without_checksum = {
        key: value
        for key, value in journal.items()
        if key != "checksum"
    }

    expected_checksum = (
        calculate_journal_checksum(
            journal_without_checksum
        )
    )

    if journal[
        "checksum"
    ] != expected_checksum:
        raise TransitionJournalError(
            "Transition-journal checksum mismatch."
        )

    return {
        **deepcopy(journal),
        "session_date": (
            parsed_session_date.isoformat()
        ),
        "transition_events": (
            validated_events
        ),
        "target_state": (
            verified_state
        ),
        "completion_payload": (
            deepcopy(
                completion_payload
            )
            if completion_payload
            is not None
            else None
        ),
    }


def read_transition_journal(
    journal_path: Path,
) -> dict | None:
    if not journal_path.exists():
        return None

    try:
        journal = json.loads(
            journal_path.read_text(
                encoding="utf-8"
            )
        )
    except json.JSONDecodeError as error:
        raise TransitionJournalError(
            "Transition journal is not valid JSON."
        ) from error
    except UnicodeDecodeError as error:
        raise TransitionJournalError(
            "Transition journal is not valid UTF-8."
        ) from error

    return verify_transition_journal(
        journal
    )


def write_transition_journal(
    journal_path: Path,
    journal: dict,
) -> None:
    verified = (
        verify_transition_journal(
            deepcopy(journal)
        )
    )

    journal_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = (
        journal_path.parent
        / f".{journal_path.name}.tmp"
    )

    encoded = (
        json.dumps(
            verified,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")

    file_descriptor = os.open(
        temporary_path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_TRUNC,
        0o600,
    )

    try:
        os.write(
            file_descriptor,
            encoded,
        )
        os.fsync(
            file_descriptor
        )
    finally:
        os.close(
            file_descriptor
        )

    os.replace(
        temporary_path,
        journal_path,
    )

    directory_descriptor = os.open(
        journal_path.parent,
        os.O_RDONLY,
    )

    try:
        os.fsync(
            directory_descriptor
        )
    finally:
        os.close(
            directory_descriptor
        )

    written = read_transition_journal(
        journal_path
    )

    if written != verified:
        raise TransitionJournalError(
            "Written transition journal could not "
            "be verified."
        )


def advance_transition_journal(
    journal: dict,
    *,
    next_stage: str,
) -> dict:
    verified = (
        verify_transition_journal(
            deepcopy(journal)
        )
    )

    if next_stage not in (
        JOURNAL_STAGES
    ):
        raise TransitionJournalError(
            "Unsupported next journal stage."
        )

    current_index = (
        JOURNAL_STAGES.index(
            verified["stage"]
        )
    )

    next_index = (
        JOURNAL_STAGES.index(
            next_stage
        )
    )

    if next_index < current_index:
        raise TransitionJournalError(
            "Transition journal cannot move backwards."
        )

    if next_index > (
        current_index + 1
    ):
        raise TransitionJournalError(
            "Transition journal cannot skip stages."
        )

    if next_index == current_index:
        return verified

    advanced_without_checksum = {
        key: value
        for key, value in verified.items()
        if key != "checksum"
    }

    advanced_without_checksum[
        "stage"
    ] = next_stage

    return {
        **advanced_without_checksum,
        "checksum": (
            calculate_journal_checksum(
                advanced_without_checksum
            )
        ),
    }


def remove_transition_journal(
    journal_path: Path,
) -> None:
    if not journal_path.exists():
        return

    read_transition_journal(
        journal_path
    )

    journal_path.unlink()

    directory_descriptor = os.open(
        journal_path.parent,
        os.O_RDONLY,
    )

    try:
        os.fsync(
            directory_descriptor
        )
    finally:
        os.close(
            directory_descriptor
        )
