import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


STATE_VERSION = "1.0"


class RuntimeStateError(RuntimeError):
    """Raised when prospective runtime state is invalid."""


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


def empty_runtime_state() -> dict:
    return {
        "state_version": STATE_VERSION,
        "candidate_balance": 10000.0,
        "shadow_balance": 10000.0,
        "candidate_peak_equity": 10000.0,
        "shadow_peak_equity": 10000.0,
        "pending_entries": {},
        "open_positions": {},
        "processed_candle_timestamps": {},
        "last_completed_session_date": None,
        "last_updated_at_utc": None,
        "broker_orders_sent": 0,
    }


def verify_runtime_state(
    state: dict,
) -> dict:
    if not isinstance(state, dict):
        raise RuntimeStateError(
            "Runtime state must be a dictionary."
        )

    state = deepcopy(
        state
    )

    # Runtime-state version 1.0 files created before processed
    # candle checkpoints remain readable. The missing field is
    # normalised to an empty mapping and written on the next
    # successful state commit.
    state.setdefault(
        "processed_candle_timestamps",
        {},
    )

    required_fields = {
        "state_version",
        "candidate_balance",
        "shadow_balance",
        "candidate_peak_equity",
        "shadow_peak_equity",
        "pending_entries",
        "open_positions",
        "processed_candle_timestamps",
        "last_completed_session_date",
        "last_updated_at_utc",
        "broker_orders_sent",
    }

    missing = (
        required_fields - state.keys()
    )

    if missing:
        raise RuntimeStateError(
            "Runtime state is missing fields: "
            + ", ".join(sorted(missing))
            + "."
        )

    if state["state_version"] != (
        STATE_VERSION
    ):
        raise RuntimeStateError(
            "Unsupported runtime-state version."
        )

    for field in (
        "candidate_balance",
        "shadow_balance",
        "candidate_peak_equity",
        "shadow_peak_equity",
    ):
        value = state[field]

        if not isinstance(
            value,
            int | float,
        ):
            raise RuntimeStateError(
                f"{field} must be numeric."
            )

        if value <= 0:
            raise RuntimeStateError(
                f"{field} must be greater than zero."
            )

    if not isinstance(
        state["pending_entries"],
        dict,
    ):
        raise RuntimeStateError(
            "pending_entries must be a dictionary."
        )

    if not isinstance(
        state["open_positions"],
        dict,
    ):
        raise RuntimeStateError(
            "open_positions must be a dictionary."
        )

    processed = state[
        "processed_candle_timestamps"
    ]

    if not isinstance(
        processed,
        dict,
    ):
        raise RuntimeStateError(
            "processed_candle_timestamps must be "
            "a dictionary."
        )

    for market, timestamp in (
        processed.items()
    ):
        if (
            not isinstance(market, str)
            or not market.strip()
        ):
            raise RuntimeStateError(
                "Processed-candle market keys must "
                "be non-empty strings."
            )

        if not isinstance(
            timestamp,
            str,
        ):
            raise RuntimeStateError(
                "Processed-candle timestamps must "
                "be strings."
            )

        try:
            parsed_timestamp = (
                datetime.fromisoformat(
                    timestamp.replace(
                        "Z",
                        "+00:00",
                    )
                )
            )
        except ValueError as error:
            raise RuntimeStateError(
                "Processed-candle timestamp is not "
                "valid ISO-8601."
            ) from error

        if parsed_timestamp.tzinfo is None:
            raise RuntimeStateError(
                "Processed-candle timestamp must "
                "be timezone-aware."
            )

        if utc_isoformat(
            parsed_timestamp
        ) != timestamp:
            raise RuntimeStateError(
                "Processed-candle timestamp must use "
                "canonical UTC format."
            )

    if state["broker_orders_sent"] != 0:
        raise RuntimeStateError(
            "Prospective simulation state records "
            "broker orders."
        )

    for market, pending in (
        state["pending_entries"].items()
    ):
        if not isinstance(market, str):
            raise RuntimeStateError(
                "Pending-entry market keys must be "
                "strings."
            )

        required_pending_fields = {
            "market",
            "signal_candle_timestamp",
            "direction",
            "candidate_risk_percent",
            "shadow_risk_percent",
            "directional_close_location",
            "policy_fingerprint",
            "created_session_date",
        }

        missing_pending = (
            required_pending_fields
            - pending.keys()
        )

        if missing_pending:
            raise RuntimeStateError(
                f"Pending entry for {market} is "
                "missing fields: "
                + ", ".join(
                    sorted(missing_pending)
                )
                + "."
            )

        if pending["market"] != market:
            raise RuntimeStateError(
                "Pending-entry market does not match "
                "its dictionary key."
            )

        if pending["direction"] not in {
            "BUY",
            "SELL",
        }:
            raise RuntimeStateError(
                f"Invalid pending-entry direction "
                f"for {market}."
            )

        candidate_risk = float(
            pending[
                "candidate_risk_percent"
            ]
        )

        shadow_risk = float(
            pending[
                "shadow_risk_percent"
            ]
        )

        if candidate_risk not in {
            0.25,
            0.5,
        }:
            raise RuntimeStateError(
                "Candidate pending-entry risk must "
                "be 0.25 or 0.5 percent."
            )

        if shadow_risk != 0.5:
            raise RuntimeStateError(
                "Shadow pending-entry risk must be "
                "0.5 percent."
            )

        close_location = float(
            pending[
                "directional_close_location"
            ]
        )

        if not 0 <= close_location <= 1:
            raise RuntimeStateError(
                "Directional close location must be "
                "between zero and one."
            )

    overlap = (
        set(state["pending_entries"])
        & set(state["open_positions"])
    )

    if overlap:
        raise RuntimeStateError(
            "A market cannot have both a pending "
            "entry and an open position."
        )

    return state


def read_runtime_state(
    state_path: Path,
) -> dict:
    if not state_path.exists():
        return empty_runtime_state()

    try:
        state = json.loads(
            state_path.read_text(
                encoding="utf-8"
            )
        )
    except json.JSONDecodeError as error:
        raise RuntimeStateError(
            "Runtime state is not valid JSON."
        ) from error

    return verify_runtime_state(
        state
    )


def write_runtime_state(
    state_path: Path,
    state: dict,
) -> None:
    verified = verify_runtime_state(
        deepcopy(state)
    )

    state_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = (
        state_path.parent
        / f".{state_path.name}.tmp"
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
        state_path,
    )

    directory_descriptor = os.open(
        state_path.parent,
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


def build_pending_entry(
    *,
    market: str,
    signal_candle_timestamp: datetime,
    direction: str,
    candidate_risk_percent: float,
    shadow_risk_percent: float,
    directional_close_location: float,
    policy_fingerprint: str,
    created_session_date: str,
) -> dict:
    pending = {
        "market": market,
        "signal_candle_timestamp": (
            utc_isoformat(
                signal_candle_timestamp
            )
        ),
        "direction": direction,
        "candidate_risk_percent": float(
            candidate_risk_percent
        ),
        "shadow_risk_percent": float(
            shadow_risk_percent
        ),
        "directional_close_location": float(
            directional_close_location
        ),
        "policy_fingerprint": (
            policy_fingerprint
        ),
        "created_session_date": (
            created_session_date
        ),
    }

    test_state = (
        empty_runtime_state()
    )

    test_state["pending_entries"][
        market
    ] = pending

    verify_runtime_state(
        test_state
    )

    return pending


def add_pending_entry(
    state: dict,
    pending_entry: dict,
) -> dict:
    updated = deepcopy(
        verify_runtime_state(
            state
        )
    )

    market = pending_entry[
        "market"
    ]

    if market in updated[
        "open_positions"
    ]:
        raise RuntimeStateError(
            f"{market} already has an open "
            "position."
        )

    existing = updated[
        "pending_entries"
    ].get(market)

    if existing is not None:
        if existing != pending_entry:
            raise RuntimeStateError(
                f"{market} already has a different "
                "pending entry."
            )

        return updated

    updated["pending_entries"][
        market
    ] = deepcopy(
        pending_entry
    )

    verify_runtime_state(
        updated
    )

    return updated


def remove_pending_entry(
    state: dict,
    market: str,
) -> tuple[
    dict,
    dict | None,
]:
    updated = deepcopy(
        verify_runtime_state(
            state
        )
    )

    removed = updated[
        "pending_entries"
    ].pop(
        market,
        None,
    )

    verify_runtime_state(
        updated
    )

    return updated, removed


def mark_state_updated(
    state: dict,
    *,
    updated_at_utc: datetime,
    completed_session_date: str | None = None,
) -> dict:
    updated = deepcopy(
        verify_runtime_state(
            state
        )
    )

    updated[
        "last_updated_at_utc"
    ] = utc_isoformat(
        updated_at_utc
    )

    if completed_session_date is not None:
        updated[
            "last_completed_session_date"
        ] = completed_session_date

    verify_runtime_state(
        updated
    )

    return updated


def mark_candle_processed(
    state: dict,
    *,
    market: str,
    candle_timestamp: datetime,
) -> dict:
    """
    Record the latest durably processed candle for one market.

    Checkpoints may only move forwards. Repeating the same
    timestamp is idempotent.
    """
    updated = deepcopy(
        verify_runtime_state(
            state
        )
    )

    if (
        not isinstance(market, str)
        or not market.strip()
    ):
        raise RuntimeStateError(
            "Processed-candle market must be a "
            "non-empty string."
        )

    canonical_timestamp = (
        utc_isoformat(
            candle_timestamp
        )
    )

    existing = updated[
        "processed_candle_timestamps"
    ].get(market)

    if existing is not None:
        existing_datetime = (
            datetime.fromisoformat(
                existing.replace(
                    "Z",
                    "+00:00",
                )
            )
        )

        if (
            candle_timestamp
            .astimezone(UTC)
            < existing_datetime
            .astimezone(UTC)
        ):
            raise RuntimeStateError(
                "Processed-candle checkpoint cannot "
                "move backwards."
            )

        if existing == canonical_timestamp:
            return updated

    updated[
        "processed_candle_timestamps"
    ][market] = canonical_timestamp

    return verify_runtime_state(
        updated
    )
