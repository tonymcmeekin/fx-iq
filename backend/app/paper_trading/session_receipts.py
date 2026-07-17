"""Create and verify immutable prospective paper-session receipts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

RECEIPT_SCHEMA_VERSION = 1
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class SessionReceiptError(RuntimeError):
    """Raised when a session receipt cannot be created or verified."""


def canonical_receipt_bytes(
    receipt: dict[str, Any],
) -> bytes:
    """Return the deterministic byte representation used for hashing."""
    payload = dict(receipt)
    payload.pop("receipt_hash", None)

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def calculate_receipt_hash(
    receipt: dict[str, Any],
) -> str:
    """Calculate the SHA-256 hash of a receipt excluding receipt_hash."""
    return hashlib.sha256(
        canonical_receipt_bytes(receipt),
    ).hexdigest()


def validate_receipt_payload(
    receipt: dict[str, Any],
    *,
    require_hash: bool,
) -> None:
    """Validate the stable session-receipt schema."""
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise SessionReceiptError("Unsupported session receipt schema version.")

    required_strings = {
        "session_date",
        "software_commit",
        "policy_fingerprint",
        "runtime_health",
        "operator_status",
        "evidence_gate_status",
        "receipt_created_at_utc",
    }

    for field in required_strings:
        value = receipt.get(field)

        if not isinstance(value, str) or not value.strip():
            raise SessionReceiptError(
                f"Session receipt field {field!r} must be a non-empty string."
            )

    try:
        parsed_session_date = datetime.fromisoformat(f"{receipt['session_date']}T00:00:00+00:00")
    except ValueError as error:
        raise SessionReceiptError("Session receipt date must use YYYY-MM-DD format.") from error

    if parsed_session_date.date().isoformat() != receipt["session_date"]:
        raise SessionReceiptError("Session receipt date must use YYYY-MM-DD format.")

    try:
        created_at = datetime.fromisoformat(receipt["receipt_created_at_utc"])
    except ValueError as error:
        raise SessionReceiptError("Session receipt creation time is invalid.") from error

    if created_at.tzinfo is None:
        raise SessionReceiptError("Session receipt creation time must be timezone-aware.")

    if receipt["runtime_health"] != "HEALTHY":
        raise SessionReceiptError("A receipt may only be written for a healthy runtime.")

    if receipt.get("safe_for_live_trading") is not False:
        raise SessionReceiptError("Session receipt must explicitly prohibit live trading.")

    if receipt.get("protocol_live_trading_permitted") is not False:
        raise SessionReceiptError("Session receipt must explicitly prohibit protocol live trading.")

    broker_orders_sent = receipt.get("broker_orders_sent")

    if (
        isinstance(broker_orders_sent, bool)
        or not isinstance(broker_orders_sent, int)
        or broker_orders_sent != 0
    ):
        raise SessionReceiptError("Session receipt must record zero broker orders.")

    completed_sessions = receipt.get("completed_sessions")

    if (
        isinstance(completed_sessions, bool)
        or not isinstance(completed_sessions, int)
        or completed_sessions < 1
    ):
        raise SessionReceiptError("Session receipt completed_sessions must be a positive integer.")

    for field in {
        "candidate_balance",
        "shadow_balance",
    }:
        value = receipt.get(field)

        if isinstance(value, bool) or not isinstance(value, int | float):
            raise SessionReceiptError(f"Session receipt field {field!r} must be numeric.")

    if require_hash:
        receipt_hash = receipt.get("receipt_hash")

        if not isinstance(receipt_hash, str) or SHA256_PATTERN.fullmatch(receipt_hash) is None:
            raise SessionReceiptError("Session receipt contains an invalid SHA-256 hash.")


def build_session_receipt(
    *,
    session_date: str,
    software_commit: str,
    policy_fingerprint: str,
    runtime_health: str,
    operator_status: str,
    evidence_gate_status: str,
    candidate_balance: int | float,
    shadow_balance: int | float,
    completed_sessions: int,
    broker_orders_sent: int,
    created_at_utc: datetime,
) -> dict[str, Any]:
    """Build and hash one immutable session receipt."""
    if created_at_utc.tzinfo is None:
        raise SessionReceiptError("Receipt creation time must be timezone-aware.")

    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "session_date": session_date,
        "software_commit": software_commit,
        "policy_fingerprint": policy_fingerprint,
        "runtime_health": runtime_health,
        "operator_status": operator_status,
        "evidence_gate_status": evidence_gate_status,
        "candidate_balance": candidate_balance,
        "shadow_balance": shadow_balance,
        "completed_sessions": completed_sessions,
        "broker_orders_sent": broker_orders_sent,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
        "receipt_created_at_utc": created_at_utc.isoformat(),
    }

    validate_receipt_payload(
        receipt,
        require_hash=False,
    )

    receipt["receipt_hash"] = calculate_receipt_hash(
        receipt,
    )

    validate_receipt_payload(
        receipt,
        require_hash=True,
    )

    return receipt


def write_receipt_atomically(
    receipt_path: Path,
    receipt: dict[str, Any],
) -> None:
    """Write a receipt atomically without allowing overwrite."""
    receipt_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = receipt_path.with_name(f".{receipt_path.name}.{uuid.uuid4().hex}.tmp")

    encoded_receipt = (
        json.dumps(
            receipt,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")

    descriptor = -1

    try:
        descriptor = os.open(
            temporary_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )

        written = 0

        while written < len(encoded_receipt):
            written += os.write(
                descriptor,
                encoded_receipt[written:],
            )

        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1

        try:
            os.link(
                temporary_path,
                receipt_path,
            )
        except FileExistsError as error:
            raise SessionReceiptError(
                f"A session receipt already exists for {receipt['session_date']}."
            ) from error

        directory_descriptor = os.open(
            receipt_path.parent,
            os.O_RDONLY,
        )

        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except SessionReceiptError:
        raise
    except OSError as error:
        raise SessionReceiptError("Session receipt could not be written safely.") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

        temporary_path.unlink(
            missing_ok=True,
        )


def write_session_receipt(
    receipt_directory: Path,
    *,
    session_date: str,
    software_commit: str,
    policy_fingerprint: str,
    runtime_health: str,
    operator_status: str,
    evidence_gate_status: str,
    candidate_balance: int | float,
    shadow_balance: int | float,
    completed_sessions: int,
    broker_orders_sent: int,
    created_at_utc: datetime,
) -> Path:
    """Build and immutably store one receipt for a completed session."""
    receipt = build_session_receipt(
        session_date=session_date,
        software_commit=software_commit,
        policy_fingerprint=policy_fingerprint,
        runtime_health=runtime_health,
        operator_status=operator_status,
        evidence_gate_status=evidence_gate_status,
        candidate_balance=candidate_balance,
        shadow_balance=shadow_balance,
        completed_sessions=completed_sessions,
        broker_orders_sent=broker_orders_sent,
        created_at_utc=created_at_utc,
    )

    receipt_path = receipt_directory / f"{session_date}.json"

    write_receipt_atomically(
        receipt_path,
        receipt,
    )

    return receipt_path


def verify_session_receipt(
    receipt_path: Path,
) -> dict[str, Any]:
    """Load and verify the schema and cryptographic hash of a receipt."""
    try:
        receipt = json.loads(
            receipt_path.read_text(
                encoding="utf-8",
            )
        )
    except FileNotFoundError as error:
        raise SessionReceiptError("Session receipt does not exist.") from error
    except (OSError, json.JSONDecodeError) as error:
        raise SessionReceiptError("Session receipt could not be read as valid JSON.") from error

    if not isinstance(receipt, dict):
        raise SessionReceiptError("Session receipt must contain a JSON object.")

    validate_receipt_payload(
        receipt,
        require_hash=True,
    )

    expected_hash = calculate_receipt_hash(
        receipt,
    )

    if receipt["receipt_hash"] != expected_hash:
        raise SessionReceiptError("Session receipt hash verification failed.")

    return receipt
