"""Append-only audit journal for prospective paper daily operations."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

JOURNAL_SCHEMA_VERSION = 1

VALID_STATUSES = {
    "COMPLETED",
    "REPORT_ONLY",
    "ALREADY_COMPLETED",
    "FAILED",
}

VALID_OPERATION_MODES = {
    "REPORT_ONLY",
    "PROSPECTIVE_PAPER_SESSION",
}

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class DailyOperationJournalError(RuntimeError):
    """Raised when a daily-operation journal record is invalid or unsafe."""


def canonical_record_bytes(
    record: dict[str, Any],
) -> bytes:
    """Return deterministic bytes for record hashing."""
    payload = dict(record)
    payload.pop("record_hash", None)

    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise DailyOperationJournalError(
            "Daily-operation record is not safely serializable."
        ) from error


def calculate_record_hash(
    record: dict[str, Any],
) -> str:
    """Calculate the SHA-256 hash excluding record_hash."""
    return hashlib.sha256(
        canonical_record_bytes(record),
    ).hexdigest()


def _require_non_empty_string(
    record: dict[str, Any],
    field: str,
) -> str:
    value = record.get(field)

    if not isinstance(value, str) or not value.strip():
        raise DailyOperationJournalError(
            f"Daily-operation field {field!r} must be a non-empty string."
        )

    return value


def _parse_aware_datetime(
    value: Any,
    *,
    field: str,
) -> datetime:
    if not isinstance(value, str):
        raise DailyOperationJournalError(
            f"Daily-operation field {field!r} must be an ISO-8601 string."
        )

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise DailyOperationJournalError(
            f"Daily-operation field {field!r} is not a valid ISO-8601 timestamp."
        ) from error

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DailyOperationJournalError(f"Daily-operation field {field!r} must be timezone-aware.")

    return parsed


def validate_daily_operation_record(
    record: dict[str, Any],
    *,
    require_hash: bool,
) -> None:
    """Validate one stable daily-operation journal record."""
    if not isinstance(record, dict):
        raise DailyOperationJournalError("Daily-operation journal record must be a JSON object.")

    if record.get("schema_version") != JOURNAL_SCHEMA_VERSION:
        raise DailyOperationJournalError("Unsupported daily-operation journal schema version.")

    _require_non_empty_string(
        record,
        "operation_id",
    )

    started_at = _parse_aware_datetime(
        record.get("started_at_utc"),
        field="started_at_utc",
    )
    completed_at = _parse_aware_datetime(
        record.get("completed_at_utc"),
        field="completed_at_utc",
    )

    if completed_at < started_at:
        raise DailyOperationJournalError("Daily-operation completion time precedes its start time.")

    status = record.get("status")

    if status not in VALID_STATUSES:
        raise DailyOperationJournalError(f"Unsupported daily-operation status: {status!r}.")

    operation_mode = record.get("operation_mode")

    if operation_mode not in VALID_OPERATION_MODES:
        raise DailyOperationJournalError(f"Unsupported daily-operation mode: {operation_mode!r}.")

    target_session_date = record.get("target_session_date")

    if target_session_date is not None:
        if not isinstance(target_session_date, str):
            raise DailyOperationJournalError(
                "Daily-operation target_session_date must be a string or null."
            )

        try:
            parsed_date = date.fromisoformat(target_session_date)
        except ValueError as error:
            raise DailyOperationJournalError(
                "Daily-operation target_session_date must use YYYY-MM-DD format."
            ) from error

        if parsed_date.isoformat() != target_session_date:
            raise DailyOperationJournalError(
                "Daily-operation target_session_date must use YYYY-MM-DD format."
            )

    for field in {
        "session_executed",
        "session_already_completed",
    }:
        if not isinstance(record.get(field), bool):
            raise DailyOperationJournalError(f"Daily-operation field {field!r} must be boolean.")

    receipt_path = record.get("session_receipt_path")

    if receipt_path is not None and (not isinstance(receipt_path, str) or not receipt_path.strip()):
        raise DailyOperationJournalError(
            "Daily-operation session_receipt_path must be a non-empty string or null."
        )

    broker_orders_sent = record.get("broker_orders_sent")

    if (
        isinstance(broker_orders_sent, bool)
        or not isinstance(broker_orders_sent, int)
        or broker_orders_sent != 0
    ):
        raise DailyOperationJournalError("Daily-operation record must contain zero broker orders.")

    if record.get("safe_for_live_trading") is not False:
        raise DailyOperationJournalError(
            "Daily-operation record must explicitly prohibit live trading."
        )

    if record.get("protocol_live_trading_permitted") is not False:
        raise DailyOperationJournalError(
            "Daily-operation record must explicitly prohibit protocol live trading."
        )

    _require_non_empty_string(
        record,
        "git_commit",
    )
    _require_non_empty_string(
        record,
        "hostname",
    )

    pid = record.get("pid")

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise DailyOperationJournalError("Daily-operation pid must be a positive integer.")

    nullable_strings = {
        "runtime_health",
        "operator_status",
        "evidence_gate_status",
    }

    for field in nullable_strings:
        value = record.get(field)

        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise DailyOperationJournalError(
                f"Daily-operation field {field!r} must be a non-empty string or null."
            )

    completed_sessions = record.get("completed_sessions")

    if completed_sessions is not None and (
        isinstance(completed_sessions, bool)
        or not isinstance(completed_sessions, int)
        or completed_sessions < 0
    ):
        raise DailyOperationJournalError(
            "Daily-operation completed_sessions must be a non-negative integer or null."
        )

    for field in {
        "candidate_balance",
        "shadow_balance",
    }:
        value = record.get(field)

        if value is not None and (isinstance(value, bool) or not isinstance(value, int | float)):
            raise DailyOperationJournalError(
                f"Daily-operation field {field!r} must be numeric or null."
            )

    failure_type = record.get("failure_type")
    failure_message = record.get("failure_message")

    if status == "FAILED":
        if not isinstance(failure_type, str) or not failure_type.strip():
            raise DailyOperationJournalError("Failed daily-operation record requires failure_type.")

        if not isinstance(failure_message, str) or not failure_message.strip():
            raise DailyOperationJournalError(
                "Failed daily-operation record requires failure_message."
            )
    elif failure_type is not None or failure_message is not None:
        raise DailyOperationJournalError(
            "Non-failed daily-operation records cannot contain failure details."
        )

    if status == "REPORT_ONLY":
        if operation_mode != "REPORT_ONLY":
            raise DailyOperationJournalError(
                "REPORT_ONLY status requires REPORT_ONLY operation mode."
            )

        if record["session_executed"]:
            raise DailyOperationJournalError("Report-only operations cannot execute a session.")

    if status == "ALREADY_COMPLETED":
        if record["session_already_completed"] is not True:
            raise DailyOperationJournalError(
                "ALREADY_COMPLETED status requires session_already_completed=true."
            )

        if record["session_executed"]:
            raise DailyOperationJournalError(
                "An already-completed operation cannot execute another session."
            )

    if status == "COMPLETED" and record["session_executed"] is not True:
        raise DailyOperationJournalError("COMPLETED status requires session_executed=true.")

    if require_hash:
        record_hash = record.get("record_hash")

        if not isinstance(record_hash, str) or SHA256_PATTERN.fullmatch(record_hash) is None:
            raise DailyOperationJournalError(
                "Daily-operation record contains an invalid SHA-256 hash."
            )

        if record_hash != calculate_record_hash(record):
            raise DailyOperationJournalError("Daily-operation record hash verification failed.")


def build_daily_operation_record(
    *,
    operation_id: str,
    started_at_utc: datetime,
    completed_at_utc: datetime,
    status: str,
    operation_mode: str,
    target_session_date: str | None,
    session_executed: bool,
    session_already_completed: bool,
    session_receipt_path: str | None,
    runtime_health: str | None,
    operator_status: str | None,
    evidence_gate_status: str | None,
    completed_sessions: int | None,
    candidate_balance: int | float | None,
    shadow_balance: int | float | None,
    broker_orders_sent: int,
    safe_for_live_trading: bool,
    protocol_live_trading_permitted: bool,
    git_commit: str,
    hostname: str,
    pid: int,
    failure_type: str | None = None,
    failure_message: str | None = None,
) -> dict[str, Any]:
    """Build and cryptographically seal one operation record."""
    if started_at_utc.tzinfo is None or started_at_utc.utcoffset() is None:
        raise DailyOperationJournalError("Daily-operation start time must be timezone-aware.")

    if completed_at_utc.tzinfo is None or completed_at_utc.utcoffset() is None:
        raise DailyOperationJournalError("Daily-operation completion time must be timezone-aware.")

    record: dict[str, Any] = {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "operation_id": operation_id,
        "started_at_utc": started_at_utc.isoformat(),
        "completed_at_utc": completed_at_utc.isoformat(),
        "status": status,
        "operation_mode": operation_mode,
        "target_session_date": target_session_date,
        "session_executed": session_executed,
        "session_already_completed": session_already_completed,
        "session_receipt_path": session_receipt_path,
        "runtime_health": runtime_health,
        "operator_status": operator_status,
        "evidence_gate_status": evidence_gate_status,
        "completed_sessions": completed_sessions,
        "candidate_balance": candidate_balance,
        "shadow_balance": shadow_balance,
        "broker_orders_sent": broker_orders_sent,
        "safe_for_live_trading": safe_for_live_trading,
        "protocol_live_trading_permitted": protocol_live_trading_permitted,
        "git_commit": git_commit,
        "hostname": hostname,
        "pid": pid,
        "failure_type": failure_type,
        "failure_message": failure_message,
    }

    validate_daily_operation_record(
        record,
        require_hash=False,
    )

    record["record_hash"] = calculate_record_hash(
        record,
    )

    validate_daily_operation_record(
        record,
        require_hash=True,
    )

    return record


def append_daily_operation_record(
    journal_path: Path,
    record: dict[str, Any],
) -> None:
    """Append one validated JSONL record and durably flush it."""
    validate_daily_operation_record(
        record,
        require_hash=True,
    )

    journal_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        encoded = (
            json.dumps(
                record,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise DailyOperationJournalError(
            "Daily-operation record could not be encoded safely."
        ) from error

    descriptor = -1

    try:
        descriptor = os.open(
            journal_path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )

        fcntl.flock(
            descriptor,
            fcntl.LOCK_EX,
        )

        written = 0

        while written < len(encoded):
            count = os.write(
                descriptor,
                encoded[written:],
            )

            if count <= 0:
                raise DailyOperationJournalError("Daily-operation journal append made no progress.")

            written += count

        os.fsync(
            descriptor,
        )
    except DailyOperationJournalError:
        raise
    except OSError as error:
        raise DailyOperationJournalError(
            "Daily-operation journal could not be appended safely."
        ) from error
    finally:
        if descriptor >= 0:
            try:
                fcntl.flock(
                    descriptor,
                    fcntl.LOCK_UN,
                )
            finally:
                os.close(
                    descriptor,
                )


def read_daily_operation_records(
    journal_path: Path,
) -> list[dict[str, Any]]:
    """Read and verify every record in an operation journal."""
    if not journal_path.exists():
        return []

    try:
        lines = journal_path.read_text(
            encoding="utf-8",
        ).splitlines()
    except UnicodeDecodeError as error:
        raise DailyOperationJournalError("Daily-operation journal is not valid UTF-8.") from error
    except OSError as error:
        raise DailyOperationJournalError("Daily-operation journal could not be read.") from error

    records: list[dict[str, Any]] = []

    for line_number, line in enumerate(
        lines,
        start=1,
    ):
        if not line.strip():
            raise DailyOperationJournalError(
                f"Daily-operation journal line {line_number} is empty."
            )

        try:
            record = json.loads(
                line,
            )
        except json.JSONDecodeError as error:
            raise DailyOperationJournalError(
                f"Daily-operation journal line {line_number} is not valid JSON."
            ) from error

        if not isinstance(record, dict):
            raise DailyOperationJournalError(
                f"Daily-operation journal line {line_number} is not a JSON object."
            )

        validate_daily_operation_record(
            record,
            require_hash=True,
        )
        records.append(
            record,
        )

    return records
