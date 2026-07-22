"""Typed contracts for append-only operator annotations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReviewModel(BaseModel):
    """Strict base model for operator-review records and API payloads."""

    model_config = ConfigDict(extra="forbid")


class AnnotationRequest(ReviewModel):
    """Explicit request to append one evidence-linked operator note."""

    idempotency_key: str = Field(min_length=8, max_length=128)
    subject_type: Literal["ALERT", "SESSION", "OBSERVATION", "OUTCOME", "AI_INSIGHT"]
    subject_id: str = Field(min_length=1, max_length=256)
    category: Literal["CONTEXT", "REVIEW", "FOLLOW_UP"]
    note: str = Field(min_length=1, max_length=2000)

    @field_validator("idempotency_key", "subject_id", "note")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value cannot be blank.")
        return value.strip()


class OperatorAnnotation(ReviewModel):
    """One immutable hash-chained operator annotation."""

    schema_version: int = 1
    sequence: int = Field(ge=1)
    annotation_id: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128)
    created_at_utc: datetime
    subject_type: Literal["ALERT", "SESSION", "OBSERVATION", "OUTCOME", "AI_INSIGHT"]
    subject_id: str
    subject_session_date: date | None = None
    category: Literal["CONTEXT", "REVIEW", "FOLLOW_UP"]
    note: str
    software_commit: str
    policy_fingerprint: str
    previous_hash: str = Field(min_length=64, max_length=64)
    record_hash: str = Field(min_length=64, max_length=64)


class ReviewSafetyResponse(ReviewModel):
    """Safety invariants shared by operator-review responses."""

    network_calls_made: int = Field(default=0, ge=0)
    files_changed: int = Field(default=0, ge=0)
    ledger_writes_performed: int = Field(default=0, ge=0)
    broker_orders_submitted: int = Field(default=0, ge=0)
    safe_for_live_trading: Literal[False] = False
    protocol_live_trading_permitted: Literal[False] = False


class AnnotationListResponse(ReviewSafetyResponse):
    """Verified append-only operator annotations."""

    schema_version: int = 1
    status: Literal["HEALTHY"] = "HEALTHY"
    annotation_count: int = Field(default=0, ge=0)
    annotations: list[OperatorAnnotation] = Field(default_factory=list)


class AnnotationAppendResponse(ReviewSafetyResponse):
    """Result of an idempotent annotation append."""

    status: Literal["CREATED", "EXISTING"]
    created: bool
    annotation: OperatorAnnotation
