"""Hash-chained audit receipts for completed practice canary rehearsals."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.broker.canary_gateway import CanaryRehearsalResult

GENESIS_HASH = "0" * 64


class CanaryAuditError(RuntimeError):
    """Raised when the local canary receipt chain is invalid."""


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _parse(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    previous = GENESIS_HASH
    seen_ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise CanaryAuditError(f"Invalid canary audit JSON at line {line_number}.") from error
        if not isinstance(record, dict):
            raise CanaryAuditError(f"Invalid canary audit record at line {line_number}.")
        if record.get("schema_version") != 1 or record.get("sequence") != line_number:
            raise CanaryAuditError(f"Canary audit sequence mismatch at line {line_number}.")
        if record.get("previous_hash") != previous:
            raise CanaryAuditError(f"Canary audit chain mismatch at line {line_number}.")
        rehearsal_id = record.get("rehearsal_id")
        if not isinstance(rehearsal_id, str) or not rehearsal_id:
            raise CanaryAuditError(f"Invalid rehearsal ID at line {line_number}.")
        if rehearsal_id in seen_ids:
            raise CanaryAuditError("Duplicate canary rehearsal ID detected.")
        payload = dict(record)
        record_hash = payload.pop("record_hash", None)
        if not isinstance(record_hash, str) or _hash(payload) != record_hash:
            raise CanaryAuditError(f"Canary audit hash mismatch at line {line_number}.")
        expected_invariants = {
            "status": "PRACTICE_REHEARSAL_COMPLETE",
            "environment": "practice",
            "units": 1,
            "practice_entry_orders_submitted": 1,
            "practice_close_orders_submitted": 1,
            "live_orders_submitted": 0,
            "position_verified_open": True,
            "position_verified_closed": True,
            "live_canary_build_enabled": False,
        }
        if any(record.get(key) != value for key, value in expected_invariants.items()):
            raise CanaryAuditError(f"Canary audit safety invariant failed at line {line_number}.")
        records.append(record)
        seen_ids.add(rehearsal_id)
        previous = record_hash
    return records


def _read(descriptor: int) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks = []
    while chunk := os.read(descriptor, 65536):
        chunks.append(chunk)
    return b"".join(chunks).decode()


def read_canary_audit(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    descriptor = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        return _parse(_read(descriptor))
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def append_canary_audit(
    path: Path,
    result: CanaryRehearsalResult,
    *,
    completed_at_utc: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    resolved_time = completed_at_utc or datetime.now(UTC)
    if resolved_time.tzinfo is None:
        raise CanaryAuditError("Canary audit time must be timezone-aware.")
    result_payload = asdict(result)
    if result_payload["live_orders_submitted"] != 0:
        raise CanaryAuditError("A live-order result cannot enter the practice audit chain.")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        records = _parse(_read(descriptor))
        existing = next(
            (record for record in records if record["rehearsal_id"] == result.rehearsal_id),
            None,
        )
        if existing:
            comparable = {
                key: value
                for key, value in existing.items()
                if key
                not in {
                    "schema_version",
                    "sequence",
                    "completed_at_utc",
                    "previous_hash",
                    "record_hash",
                }
            }
            if comparable != result_payload:
                raise CanaryAuditError(
                    "Canary rehearsal ID was reused for a different completed result."
                )
            return existing, False
        payload = {
            "schema_version": 1,
            "sequence": len(records) + 1,
            "completed_at_utc": resolved_time.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            **result_payload,
            "previous_hash": records[-1]["record_hash"] if records else GENESIS_HASH,
        }
        payload["record_hash"] = _hash(payload)
        encoded = (_canonical(payload) + "\n").encode()
        os.lseek(descriptor, 0, os.SEEK_END)
        written = 0
        while written < len(encoded):
            written += os.write(descriptor, encoded[written:])
        os.fsync(descriptor)
        if _parse(_read(descriptor))[-1] != payload:
            raise CanaryAuditError("Appended canary audit record could not be verified.")
        return payload, True
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
