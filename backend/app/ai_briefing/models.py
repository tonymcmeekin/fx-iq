"""Strict contracts for sanitized AI evidence briefings."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BriefingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceItem(BriefingModel):
    evidence_id: str = Field(min_length=3, max_length=256)
    evidence_type: Literal["COCKPIT", "ALERT", "PORTFOLIO", "OUTCOMES", "ANNOTATION"]
    facts: dict[str, Any]


class SanitizedEvidenceSnapshot(BriefingModel):
    schema_version: int = 1
    generated_at_utc: datetime
    evidence_items: list[EvidenceItem]
    excluded_fields: list[str]


class EvidenceCitation(BriefingModel):
    evidence_id: str
    label: str = Field(min_length=1, max_length=160)


class BriefingDraft(BriefingModel):
    headline: str = Field(min_length=1, max_length=240)
    what_changed: list[str] = Field(max_length=8)
    why_waiting: list[str] = Field(max_length=8)
    missing_evidence: list[str] = Field(max_length=8)
    risks_to_review: list[str] = Field(max_length=8)
    next_review_questions: list[str] = Field(max_length=8)
    citations: list[EvidenceCitation] = Field(min_length=1, max_length=20)

    @field_validator(
        "what_changed",
        "why_waiting",
        "missing_evidence",
        "risks_to_review",
        "next_review_questions",
    )
    @classmethod
    def reject_blank_list_items(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("Briefing list items cannot be blank.")
        return [item.strip() for item in value]


class BriefingSafety(BriefingModel):
    input_sanitized: Literal[True] = True
    credentials_included: Literal[False] = False
    annotation_text_included: Literal[False] = False
    raw_market_data_included: Literal[False] = False
    trading_action_permitted: Literal[False] = False
    network_calls_made: int = Field(default=0, ge=0)
    files_changed: int = Field(default=0, ge=0)
    ledger_writes_performed: int = Field(default=0, ge=0)
    broker_orders_submitted: int = Field(default=0, ge=0)
    safe_for_live_trading: Literal[False] = False
    protocol_live_trading_permitted: Literal[False] = False


class BriefingQualityGate(BriefingModel):
    status: Literal["PASS", "FAIL"]
    citations_valid: bool
    core_evidence_cited: bool
    sparse_evidence_acknowledged: bool
    prohibited_trading_language_absent: bool
    sensitive_identifier_patterns_absent: bool
    failures: list[str]


class EvidenceBriefingResponse(BriefingModel):
    schema_version: int = 1
    status: Literal["READY"] = "READY"
    generated_at_utc: datetime
    provider_mode: Literal["OFFLINE", "OPENAI"]
    model: str
    prompt_fingerprint: str = Field(min_length=64, max_length=64)
    input_fingerprint: str = Field(min_length=64, max_length=64)
    hosted_provider_available: bool
    briefing: BriefingDraft
    quality_gate: BriefingQualityGate
    safety: BriefingSafety


class BriefingGenerateRequest(BriefingModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    provider_mode: Literal["OFFLINE", "OPENAI"] = "OFFLINE"
    external_transmission_confirmed: bool = False

    @field_validator("idempotency_key")
    @classmethod
    def reject_blank_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Idempotency key cannot be blank.")
        return value.strip()

    @model_validator(mode="after")
    def require_hosted_transmission_confirmation(self):
        if self.provider_mode == "OPENAI" and not self.external_transmission_confirmed:
            raise ValueError(
                "Hosted generation requires explicit external transmission confirmation."
            )
        return self


class InsightRecord(BriefingModel):
    schema_version: int = 1
    sequence: int = Field(ge=1)
    insight_id: str = Field(min_length=64, max_length=64)
    idempotency_key: str
    created_at_utc: datetime
    provider_mode: Literal["OFFLINE", "OPENAI"]
    model: str
    prompt_fingerprint: str
    input_fingerprint: str
    briefing: BriefingDraft
    quality_gate: BriefingQualityGate
    previous_hash: str = Field(min_length=64, max_length=64)
    record_hash: str = Field(min_length=64, max_length=64)


class InsightAppendResponse(BriefingModel):
    status: Literal["CREATED", "EXISTING"]
    created: bool
    insight: InsightRecord
    safety: BriefingSafety


class InsightListResponse(BriefingModel):
    status: Literal["HEALTHY"] = "HEALTHY"
    insight_count: int = Field(ge=0)
    insights: list[InsightRecord]
    safety: BriefingSafety


class AiGovernanceResponse(BriefingModel):
    """Cross-chain review coverage for saved AI insights."""

    schema_version: int = 1
    status: Literal["HEALTHY", "REVIEW_REQUIRED", "INTEGRITY_ERROR"]
    insight_count: int = Field(ge=0)
    reviewed_insight_count: int = Field(ge=0)
    unreviewed_insight_count: int = Field(ge=0)
    hosted_insight_count: int = Field(ge=0)
    orphaned_review_count: int = Field(ge=0)
    unreviewed_insight_ids: list[str]
    orphaned_review_subject_ids: list[str]
    model_fingerprints: list[str]
    prompt_fingerprints: list[str]
    review_rule: str
    safety: BriefingSafety


class ProviderReadinessResponse(BriefingModel):
    """Secret-free local preflight for the optional hosted provider."""

    schema_version: int = 1
    status: Literal["READY", "DISABLED", "INCOMPLETE"]
    offline_provider_ready: Literal[True] = True
    hosted_provider_requested: bool
    api_key_configured: bool
    model_configured: bool
    configured_model: str | None
    endpoint: Literal["https://api.openai.com/v1/responses"] = "https://api.openai.com/v1/responses"
    request_storage_enabled: Literal[False] = False
    sanitized_input_only: Literal[True] = True
    explicit_generation_required: Literal[True] = True
    required_settings: list[str]
    blocking_reasons: list[str]
    safety: BriefingSafety
