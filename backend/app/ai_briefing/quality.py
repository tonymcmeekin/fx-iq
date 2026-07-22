"""Deterministic fail-closed checks for generated evidence briefings."""

from __future__ import annotations

import hashlib
import re

from app.ai_briefing.models import (
    BriefingDraft,
    BriefingQualityGate,
    SanitizedEvidenceSnapshot,
)

PROHIBITED_TRADING_PATTERNS = (
    r"\b(?:buy|sell)\s+(?:now|immediately)\b",
    r"\bplace\s+(?:an?|the)\s+(?:broker\s+)?order\b",
    r"\bsubmit\s+(?:an?|the)\s+(?:broker\s+)?order\b",
    r"\b(?:increase|raise|double)\s+(?:the\s+)?risk\b",
    r"\blive\s+trading\s+is\s+safe\b",
    r"\bauthori[sz]e\s+live\s+trading\b",
)
SENSITIVE_IDENTIFIER_PATTERNS = (
    r"\b\d{3}-\d{3}-\d{8}-\d{3}\b",
    r"\bsk-[A-Za-z0-9_-]{12,}\b",
)
SPARSE_ACKNOWLEDGEMENT_MARKERS = (
    "insufficient",
    "withheld",
    "cannot support",
    "more completed outcomes",
    "required completed outcomes",
    "not enough evidence",
)


def briefing_fingerprint(briefing: BriefingDraft) -> str:
    """Fingerprint rejected content without retaining the content itself."""
    return hashlib.sha256(briefing.model_dump_json().encode("utf-8")).hexdigest()


def validate_briefing_quality(
    briefing: BriefingDraft,
    snapshot: SanitizedEvidenceSnapshot,
) -> BriefingQualityGate:
    """Validate grounding and safety without another model or network call."""
    allowed_ids = {item.evidence_id for item in snapshot.evidence_items}
    cited_ids = {citation.evidence_id for citation in briefing.citations}
    citation_types = {
        item.evidence_type for item in snapshot.evidence_items if item.evidence_id in cited_ids
    }
    citations_valid = bool(cited_ids) and cited_ids <= allowed_ids
    core_evidence_cited = {
        "COCKPIT",
        "PORTFOLIO",
        "OUTCOMES",
    } <= citation_types

    text = briefing.model_dump_json().lower()
    outcome_item = next(
        item for item in snapshot.evidence_items if item.evidence_type == "OUTCOMES"
    )
    sparse = not bool(outcome_item.facts.get("performance_metrics_available"))
    sparse_acknowledged = not sparse or any(
        marker in text for marker in SPARSE_ACKNOWLEDGEMENT_MARKERS
    )
    prohibited_absent = not any(
        re.search(pattern, text, flags=re.IGNORECASE) for pattern in PROHIBITED_TRADING_PATTERNS
    )
    sensitive_absent = not any(
        re.search(pattern, text) for pattern in SENSITIVE_IDENTIFIER_PATTERNS
    )

    checks = {
        "citations_valid": citations_valid,
        "core_evidence_cited": core_evidence_cited,
        "sparse_evidence_acknowledged": sparse_acknowledged,
        "prohibited_trading_language_absent": prohibited_absent,
        "sensitive_identifier_patterns_absent": sensitive_absent,
    }
    failures = [name for name, passed in checks.items() if not passed]
    return BriefingQualityGate(
        status="PASS" if not failures else "FAIL",
        failures=failures,
        **checks,
    )
