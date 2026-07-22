"""Hash-chained storage isolated from trading and evidence ledgers."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.ai_briefing.models import (
    BriefingDraft,
    BriefingQualityGate,
    BriefingRejectionRecord,
    InsightRecord,
)

GENESIS_HASH = "0" * 64


class InsightStoreError(RuntimeError):
    pass


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def idempotency_fingerprint(idempotency_key: str) -> str:
    """Return the non-reversible key fingerprint used across both audit chains."""
    return _hash({"idempotency_key": idempotency_key})


@contextmanager
def idempotency_guard(insight_path: Path):
    """Serialize generation so concurrent retries cannot both reach a provider."""
    insight_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(insight_path.parent, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _parse(text: str) -> list[InsightRecord]:
    if not text:
        return []
    records = []
    previous = GENESIS_HASH
    seen_ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        try:
            record = InsightRecord.model_validate_json(line)
        except ValueError as error:
            raise InsightStoreError(f"Invalid AI insight at line {line_number}.") from error
        if record.sequence != line_number or record.previous_hash != previous:
            raise InsightStoreError(f"AI insight chain mismatch at line {line_number}.")
        if record.insight_id in seen_ids:
            raise InsightStoreError("Duplicate AI insight ID detected.")
        if record.insight_id != _hash({"idempotency_key": record.idempotency_key}):
            raise InsightStoreError(f"AI insight ID mismatch at line {line_number}.")
        payload = record.model_dump(mode="json")
        record_hash = payload.pop("record_hash")
        if _hash(payload) != record_hash:
            raise InsightStoreError(f"AI insight hash mismatch at line {line_number}.")
        records.append(record)
        seen_ids.add(record.insight_id)
        previous = record.record_hash
    return records


def _parse_rejections(text: str) -> list[BriefingRejectionRecord]:
    if not text:
        return []
    records = []
    previous = GENESIS_HASH
    seen_ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        try:
            record = BriefingRejectionRecord.model_validate_json(line)
        except ValueError as error:
            raise InsightStoreError(
                f"Invalid AI rejection audit record at line {line_number}."
            ) from error
        if record.sequence != line_number or record.previous_hash != previous:
            raise InsightStoreError(f"AI rejection audit chain mismatch at line {line_number}.")
        if record.rejection_id in seen_ids:
            raise InsightStoreError("Duplicate AI rejection audit ID detected.")
        expected_id = _hash(
            {
                "record_type": "AI_BRIEFING_REJECTION",
                "idempotency_fingerprint": record.idempotency_fingerprint,
            }
        )
        if record.rejection_id != expected_id:
            raise InsightStoreError(f"AI rejection audit ID mismatch at line {line_number}.")
        payload = record.model_dump(mode="json")
        record_hash = payload.pop("record_hash")
        if _hash(payload) != record_hash:
            raise InsightStoreError(f"AI rejection audit hash mismatch at line {line_number}.")
        records.append(record)
        seen_ids.add(record.rejection_id)
        previous = record.record_hash
    return records


def _read(descriptor: int) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks = []
    while chunk := os.read(descriptor, 65536):
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")


def read_insights(path: Path) -> list[InsightRecord]:
    if not path.exists():
        return []
    descriptor = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        return _parse(_read(descriptor))
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def read_rejections(path: Path) -> list[BriefingRejectionRecord]:
    if not path.exists():
        return []
    descriptor = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        return _parse_rejections(_read(descriptor))
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def append_insight(
    path: Path,
    *,
    idempotency_key: str,
    created_at_utc: datetime,
    provider_mode: str,
    model: str,
    prompt_fingerprint: str,
    input_fingerprint: str,
    briefing: BriefingDraft | dict[str, Any],
    quality_gate: BriefingQualityGate | dict[str, Any],
) -> tuple[InsightRecord, bool]:
    if created_at_utc.tzinfo is None:
        raise InsightStoreError("AI insight time must be timezone-aware.")
    briefing = BriefingDraft.model_validate(briefing)
    quality_gate = BriefingQualityGate.model_validate(quality_gate)
    insight_id = idempotency_fingerprint(idempotency_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        records = _parse(_read(descriptor))
        existing = next((row for row in records if row.insight_id == insight_id), None)
        if existing:
            if (
                existing.input_fingerprint != input_fingerprint
                or existing.provider_mode != provider_mode
                or existing.model != model
                or existing.prompt_fingerprint != prompt_fingerprint
            ):
                raise InsightStoreError("Idempotency key was reused for different AI evidence.")
            return existing, False
        payload = {
            "schema_version": 1,
            "sequence": len(records) + 1,
            "insight_id": insight_id,
            "idempotency_key": idempotency_key,
            "created_at_utc": created_at_utc.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "provider_mode": provider_mode,
            "model": model,
            "prompt_fingerprint": prompt_fingerprint,
            "input_fingerprint": input_fingerprint,
            "briefing": briefing.model_dump(mode="json"),
            "quality_gate": quality_gate.model_dump(mode="json"),
            "previous_hash": records[-1].record_hash if records else GENESIS_HASH,
        }
        payload["record_hash"] = _hash(payload)
        record = InsightRecord.model_validate(payload)
        encoded = (_canonical(record.model_dump(mode="json")) + "\n").encode("utf-8")
        os.lseek(descriptor, 0, os.SEEK_END)
        written = 0
        while written < len(encoded):
            written += os.write(descriptor, encoded[written:])
        os.fsync(descriptor)
        if _parse(_read(descriptor))[-1] != record:
            raise InsightStoreError("Appended AI insight could not be verified.")
        return record, True
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def append_rejection(
    path: Path,
    *,
    idempotency_key: str,
    created_at_utc: datetime,
    provider_mode: str,
    model: str,
    prompt_fingerprint: str,
    input_fingerprint: str,
    output_fingerprint: str,
    failed_checks: list[str],
    network_calls_made: int,
) -> tuple[BriefingRejectionRecord, bool]:
    """Append only safe metadata; rejected model text is never accepted here."""
    if created_at_utc.tzinfo is None:
        raise InsightStoreError("AI rejection audit time must be timezone-aware.")
    if not failed_checks:
        raise InsightStoreError("AI rejection audit requires at least one failed check.")
    key_fingerprint = idempotency_fingerprint(idempotency_key)
    rejection_id = _hash(
        {
            "record_type": "AI_BRIEFING_REJECTION",
            "idempotency_fingerprint": key_fingerprint,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        records = _parse_rejections(_read(descriptor))
        existing = next((row for row in records if row.rejection_id == rejection_id), None)
        if existing:
            if (
                existing.input_fingerprint != input_fingerprint
                or existing.output_fingerprint != output_fingerprint
                or existing.provider_mode != provider_mode
                or existing.model != model
                or existing.prompt_fingerprint != prompt_fingerprint
                or existing.failed_checks != failed_checks
                or existing.network_calls_made != network_calls_made
            ):
                raise InsightStoreError("Idempotency key was reused for a different AI rejection.")
            return existing, False
        payload = {
            "schema_version": 1,
            "sequence": len(records) + 1,
            "rejection_id": rejection_id,
            "idempotency_fingerprint": key_fingerprint,
            "created_at_utc": created_at_utc.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "provider_mode": provider_mode,
            "model": model,
            "prompt_fingerprint": prompt_fingerprint,
            "input_fingerprint": input_fingerprint,
            "output_fingerprint": output_fingerprint,
            "failed_checks": failed_checks,
            "network_calls_made": network_calls_made,
            "previous_hash": records[-1].record_hash if records else GENESIS_HASH,
        }
        payload["record_hash"] = _hash(payload)
        record = BriefingRejectionRecord.model_validate(payload)
        encoded = (_canonical(record.model_dump(mode="json")) + "\n").encode("utf-8")
        os.lseek(descriptor, 0, os.SEEK_END)
        written = 0
        while written < len(encoded):
            written += os.write(descriptor, encoded[written:])
        os.fsync(descriptor)
        if _parse_rejections(_read(descriptor))[-1] != record:
            raise InsightStoreError("Appended AI rejection audit could not be verified.")
        return record, True
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
