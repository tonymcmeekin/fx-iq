"""Hash-chained append-only storage for operator annotations."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.operator_review.models import OperatorAnnotation

GENESIS_HASH = "0" * 64


class AnnotationStoreError(RuntimeError):
    """Raised when annotation storage fails integrity verification."""


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _calculate_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _annotation_id(idempotency_key: str) -> str:
    return _calculate_hash({"idempotency_key": idempotency_key})


def _parse_annotations(text: str) -> list[OperatorAnnotation]:
    if not text:
        return []
    records = []
    previous_hash = GENESIS_HASH
    seen_ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise AnnotationStoreError(
                f"Blank annotation line at {line_number}."
            )
        try:
            payload = json.loads(line)
            annotation = OperatorAnnotation.model_validate(payload)
        except (json.JSONDecodeError, ValueError) as error:
            raise AnnotationStoreError(
                f"Invalid annotation at line {line_number}."
            ) from error
        if annotation.sequence != line_number:
            raise AnnotationStoreError(
                f"Annotation sequence mismatch at line {line_number}."
            )
        if annotation.annotation_id in seen_ids:
            raise AnnotationStoreError("Duplicate annotation ID detected.")
        if annotation.annotation_id != _annotation_id(
            annotation.idempotency_key
        ):
            raise AnnotationStoreError("Annotation ID verification failed.")
        if annotation.created_at_utc.tzinfo is None:
            raise AnnotationStoreError(
                "Annotation creation timestamp must be timezone-aware."
            )
        if annotation.previous_hash != previous_hash:
            raise AnnotationStoreError(
                f"Annotation previous hash mismatch at line {line_number}."
            )
        without_hash = annotation.model_dump(mode="json")
        record_hash = without_hash.pop("record_hash")
        if record_hash != _calculate_hash(without_hash):
            raise AnnotationStoreError(
                f"Annotation record hash mismatch at line {line_number}."
            )
        records.append(annotation)
        seen_ids.add(annotation.annotation_id)
        previous_hash = annotation.record_hash
    return records


def _read_descriptor(descriptor: int) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks = []
    while True:
        chunk = os.read(descriptor, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    try:
        return b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as error:
        raise AnnotationStoreError(
            "Annotation store is not valid UTF-8."
        ) from error


def read_annotations(store_path: Path) -> list[OperatorAnnotation]:
    """Read and verify the complete annotation hash chain."""
    if not store_path.exists():
        return []
    descriptor = os.open(store_path, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        return _parse_annotations(_read_descriptor(descriptor))
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def append_annotation(
    store_path: Path,
    *,
    idempotency_key: str,
    created_at_utc: datetime,
    subject_type: str,
    subject_id: str,
    subject_session_date: date | None,
    category: str,
    note: str,
    software_commit: str,
    policy_fingerprint: str,
) -> tuple[OperatorAnnotation, bool]:
    """Append once under an exclusive lock, returning existing on retry."""
    if created_at_utc.tzinfo is None:
        raise AnnotationStoreError(
            "Annotation creation timestamp must be timezone-aware."
        )
    store_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(store_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        existing = _parse_annotations(_read_descriptor(descriptor))
        annotation_id = _annotation_id(idempotency_key)
        duplicate = next(
            (
                annotation
                for annotation in existing
                if annotation.annotation_id == annotation_id
            ),
            None,
        )
        if duplicate is not None:
            expected = {
                "subject_type": subject_type,
                "subject_id": subject_id,
                "category": category,
                "note": note,
            }
            actual = {
                key: getattr(duplicate, key)
                for key in expected
            }
            if actual != expected:
                raise AnnotationStoreError(
                    "Idempotency key was reused for different annotation content."
                )
            return duplicate, False

        payload: dict[str, Any] = {
            "schema_version": 1,
            "sequence": len(existing) + 1,
            "annotation_id": annotation_id,
            "idempotency_key": idempotency_key,
            "created_at_utc": (
                created_at_utc.astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z")
            ),
            "subject_type": subject_type,
            "subject_id": subject_id,
            "subject_session_date": (
                None
                if subject_session_date is None
                else subject_session_date.isoformat()
            ),
            "category": category,
            "note": note,
            "software_commit": software_commit,
            "policy_fingerprint": policy_fingerprint,
            "previous_hash": (
                existing[-1].record_hash if existing else GENESIS_HASH
            ),
        }
        payload["record_hash"] = _calculate_hash(payload)
        annotation = OperatorAnnotation.model_validate(payload)
        encoded = (_canonical_json(annotation.model_dump(mode="json")) + "\n").encode(
            "utf-8"
        )
        os.lseek(descriptor, 0, os.SEEK_END)
        written = 0
        while written < len(encoded):
            written += os.write(descriptor, encoded[written:])
        os.fsync(descriptor)
        verified = _parse_annotations(_read_descriptor(descriptor))
        if verified[-1] != annotation:
            raise AnnotationStoreError(
                "Appended annotation could not be verified."
            )
        return annotation, True
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
