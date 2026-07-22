"""Orchestrate sanitized briefings without exposing trading capabilities."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.ai_briefing.evidence import build_sanitized_snapshot, snapshot_fingerprint
from app.ai_briefing.models import BriefingGenerateRequest, BriefingSafety
from app.ai_briefing.prompt import PROMPT_FINGERPRINT
from app.ai_briefing.providers import (
    BriefingProviderError,
    DeterministicEvidenceProvider,
    EvidenceBriefingProvider,
    OpenAIResponsesProvider,
)
from app.ai_briefing.store import append_insight, read_insights
from app.analytics.evidence_cockpit_reporting import build_evidence_cockpit
from app.analytics.operator_alert_reporting import build_operator_alert_report
from app.analytics.outcome_explorer_reporting import build_outcome_explorer_report
from app.analytics.portfolio_intelligence_reporting import build_portfolio_intelligence_report
from app.operator_review.service import (
    DEFAULT_ANNOTATION_PATH,
    list_operator_annotations,
)

BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]
DEFAULT_INSIGHT_PATH = BACKEND_DIRECTORY / "paper_ledger" / "ai_evidence_insights.jsonl"


class EvidenceBriefingError(RuntimeError):
    pass


def hosted_provider_available() -> bool:
    return build_provider_readiness_report()["status"] == "READY"


def build_provider_readiness_report(
    *, environment: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Report configuration presence without returning any secret value."""
    values = os.environ if environment is None else environment
    hosted_requested = values.get("AI_BRIEFING_HOSTED_ENABLED", "").lower() == "true"
    api_key_configured = bool(values.get("OPENAI_API_KEY"))
    configured_model = values.get("AI_BRIEFING_OPENAI_MODEL") or None
    blocking_reasons = []
    if not hosted_requested:
        blocking_reasons.append("Hosted generation has not been explicitly enabled.")
    if not api_key_configured:
        blocking_reasons.append("The OpenAI API key is not configured.")
    if configured_model is None:
        blocking_reasons.append("The hosted briefing model is not configured.")
    status = (
        "READY" if not blocking_reasons else "DISABLED" if not hosted_requested else "INCOMPLETE"
    )
    return {
        "schema_version": 1,
        "status": status,
        "offline_provider_ready": True,
        "hosted_provider_requested": hosted_requested,
        "api_key_configured": api_key_configured,
        "model_configured": configured_model is not None,
        "configured_model": configured_model,
        "endpoint": "https://api.openai.com/v1/responses",
        "request_storage_enabled": False,
        "sanitized_input_only": True,
        "explicit_generation_required": True,
        "required_settings": [
            "AI_BRIEFING_HOSTED_ENABLED=true",
            "AI_BRIEFING_OPENAI_MODEL=<model-id>",
            "OPENAI_API_KEY=<secret>",
        ],
        "blocking_reasons": blocking_reasons,
        "safety": BriefingSafety().model_dump(mode="json"),
    }


def _reports() -> tuple[dict[str, Any], ...]:
    cockpit = build_evidence_cockpit()
    return (
        cockpit,
        build_operator_alert_report(cockpit_report=cockpit),
        build_portfolio_intelligence_report(),
        build_outcome_explorer_report(),
        list_operator_annotations(),
    )


def _snapshot(
    reports: tuple[dict[str, Any], ...] | None,
    now_utc: datetime,
):
    cockpit, alerts, portfolio, outcomes, annotations = reports or _reports()
    return build_sanitized_snapshot(
        cockpit=cockpit,
        alerts=alerts,
        portfolio=portfolio,
        outcomes=outcomes,
        annotations=annotations,
        now_utc=now_utc,
    )


def _validate_citations(provider: EvidenceBriefingProvider, briefing, snapshot) -> None:
    allowed = {item.evidence_id for item in snapshot.evidence_items}
    cited = {citation.evidence_id for citation in briefing.citations}
    if not cited <= allowed:
        raise EvidenceBriefingError(
            f"{provider.mode} provider cited evidence outside the sanitized snapshot."
        )


def _provider(mode: str) -> EvidenceBriefingProvider:
    if mode == "OFFLINE":
        return DeterministicEvidenceProvider()
    if not hosted_provider_available():
        raise EvidenceBriefingError(
            "Hosted AI briefings are disabled or missing explicit model/key configuration."
        )
    return OpenAIResponsesProvider(
        api_key=os.environ["OPENAI_API_KEY"],
        model=os.environ["AI_BRIEFING_OPENAI_MODEL"],
    )


def build_evidence_briefing(
    *,
    reports: tuple[dict[str, Any], ...] | None = None,
    provider: EvidenceBriefingProvider | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Return a non-persistent offline briefing for dashboard display."""
    resolved_now = now_utc or datetime.now(UTC)
    if resolved_now.tzinfo is None:
        raise EvidenceBriefingError("Briefing time must be timezone-aware.")
    selected = provider or DeterministicEvidenceProvider()
    try:
        snapshot = _snapshot(reports, resolved_now)
        briefing = selected.generate(snapshot)
        _validate_citations(selected, briefing, snapshot)
    except (OSError, RuntimeError, ValueError) as error:
        if isinstance(error, EvidenceBriefingError):
            raise
        raise EvidenceBriefingError(str(error)) from error
    return {
        "schema_version": 1,
        "status": "READY",
        "generated_at_utc": resolved_now.astimezone(UTC),
        "provider_mode": selected.mode,
        "model": selected.model,
        "prompt_fingerprint": PROMPT_FINGERPRINT,
        "input_fingerprint": snapshot_fingerprint(snapshot),
        "hosted_provider_available": hosted_provider_available(),
        "briefing": briefing.model_dump(mode="json"),
        "safety": BriefingSafety(
            network_calls_made=selected.network_calls_made,
        ).model_dump(mode="json"),
    }


def generate_and_store_insight(
    request: BriefingGenerateRequest,
    *,
    insight_path: Path = DEFAULT_INSIGHT_PATH,
    reports: tuple[dict[str, Any], ...] | None = None,
    provider: EvidenceBriefingProvider | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Explicitly generate and append one isolated, idempotent insight."""
    resolved_now = now_utc or datetime.now(UTC)
    selected = provider or _provider(request.provider_mode)
    if selected.mode != request.provider_mode:
        raise EvidenceBriefingError("Requested provider mode does not match the selected provider.")
    try:
        response = build_evidence_briefing(
            reports=reports,
            provider=selected,
            now_utc=resolved_now,
        )
        record, created = append_insight(
            insight_path,
            idempotency_key=request.idempotency_key,
            created_at_utc=resolved_now,
            provider_mode=selected.mode,
            model=selected.model,
            prompt_fingerprint=response["prompt_fingerprint"],
            input_fingerprint=response["input_fingerprint"],
            briefing=response["briefing"],
        )
    except (OSError, RuntimeError, ValueError, BriefingProviderError) as error:
        if isinstance(error, EvidenceBriefingError):
            raise
        raise EvidenceBriefingError(str(error)) from error
    return {
        "status": "CREATED" if created else "EXISTING",
        "created": created,
        "insight": record.model_dump(mode="json"),
        "safety": BriefingSafety(
            network_calls_made=selected.network_calls_made,
            files_changed=1 if created else 0,
        ).model_dump(mode="json"),
    }


def list_insights(*, insight_path: Path = DEFAULT_INSIGHT_PATH) -> dict[str, Any]:
    try:
        insights = read_insights(insight_path)
    except (OSError, RuntimeError, ValueError) as error:
        raise EvidenceBriefingError(str(error)) from error
    return {
        "status": "HEALTHY",
        "insight_count": len(insights),
        "insights": [insight.model_dump(mode="json") for insight in insights],
        "safety": BriefingSafety().model_dump(mode="json"),
    }


def build_ai_governance_report(
    *,
    insight_path: Path = DEFAULT_INSIGHT_PATH,
    annotation_path: Path = DEFAULT_ANNOTATION_PATH,
) -> dict[str, Any]:
    """Verify AI insights against immutable human-review annotations."""
    try:
        insights = read_insights(insight_path)
        annotations = list_operator_annotations(annotation_path=annotation_path)["annotations"]
    except (OSError, RuntimeError, ValueError) as error:
        raise EvidenceBriefingError(str(error)) from error

    insight_ids = {insight.insight_id for insight in insights}
    review_subject_ids = {
        str(annotation["subject_id"])
        for annotation in annotations
        if annotation["subject_type"] == "AI_INSIGHT"
        and annotation["category"] in {"REVIEW", "FOLLOW_UP"}
    }
    orphaned = sorted(review_subject_ids - insight_ids)
    reviewed = insight_ids & review_subject_ids
    unreviewed = sorted(insight_ids - reviewed)
    status = "INTEGRITY_ERROR" if orphaned else "REVIEW_REQUIRED" if unreviewed else "HEALTHY"
    return {
        "schema_version": 1,
        "status": status,
        "insight_count": len(insights),
        "reviewed_insight_count": len(reviewed),
        "unreviewed_insight_count": len(unreviewed),
        "hosted_insight_count": sum(insight.provider_mode == "OPENAI" for insight in insights),
        "orphaned_review_count": len(orphaned),
        "unreviewed_insight_ids": unreviewed,
        "orphaned_review_subject_ids": orphaned,
        "model_fingerprints": sorted(
            {f"{insight.provider_mode}:{insight.model}" for insight in insights}
        ),
        "prompt_fingerprints": sorted({insight.prompt_fingerprint for insight in insights}),
        "review_rule": (
            "A saved insight is reviewed only when a verified REVIEW or "
            "FOLLOW_UP annotation references its exact insight ID."
        ),
        "safety": BriefingSafety().model_dump(mode="json"),
    }
