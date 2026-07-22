"""Hash-chained, content-safe audit records for failed canary rehearsals."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.broker.canary_gateway import CanaryFailureContext

GENESIS_HASH = "0" * 64


class CanaryFailureAuditError(RuntimeError):
    """Raised when the failed-rehearsal audit chain is invalid."""


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
            raise CanaryFailureAuditError(
                f"Invalid canary failure audit JSON at line {line_number}."
            ) from error
        if not isinstance(record, dict):
            raise CanaryFailureAuditError(
                f"Invalid canary failure audit record at line {line_number}."
            )
        if record.get("schema_version") != 1 or record.get("sequence") != line_number:
            raise CanaryFailureAuditError(
                f"Canary failure audit sequence mismatch at line {line_number}."
            )
        if record.get("previous_hash") != previous:
            raise CanaryFailureAuditError(
                f"Canary failure audit chain mismatch at line {line_number}."
            )
        rehearsal_id = record.get("rehearsal_id")
        if not isinstance(rehearsal_id, str) or not rehearsal_id:
            raise CanaryFailureAuditError(f"Invalid rehearsal ID at line {line_number}.")
        if rehearsal_id in seen_ids:
            raise CanaryFailureAuditError("Duplicate failed canary rehearsal ID detected.")
        payload = dict(record)
        record_hash = payload.pop("record_hash", None)
        if not isinstance(record_hash, str) or _hash(payload) != record_hash:
            raise CanaryFailureAuditError(
                f"Canary failure audit hash mismatch at line {line_number}."
            )
        if record.get("live_orders_submitted") != 0:
            raise CanaryFailureAuditError(
                f"Canary failure audit safety invariant failed at line {line_number}."
            )
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


def read_canary_failure_audit(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    descriptor = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        return _parse(_read(descriptor))
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def append_canary_failure_audit(
    path: Path,
    context: CanaryFailureContext,
    *,
    failed_at_utc: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    resolved_time = failed_at_utc or datetime.now(UTC)
    if resolved_time.tzinfo is None:
        raise CanaryFailureAuditError("Canary failure time must be timezone-aware.")
    context_payload = asdict(context)
    if context_payload["live_orders_submitted"] != 0:
        raise CanaryFailureAuditError("A live-order failure cannot enter this audit chain.")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        records = _parse(_read(descriptor))
        existing = next(
            (record for record in records if record["rehearsal_id"] == context.rehearsal_id),
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
                    "failed_at_utc",
                    "previous_hash",
                    "record_hash",
                }
            }
            if comparable != context_payload:
                raise CanaryFailureAuditError(
                    "Failed canary rehearsal ID was reused for a different result."
                )
            return existing, False
        payload = {
            "schema_version": 1,
            "sequence": len(records) + 1,
            "failed_at_utc": resolved_time.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            **context_payload,
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
            raise CanaryFailureAuditError(
                "Appended canary failure audit record could not be verified."
            )
        return payload, True
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
