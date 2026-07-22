"""Guarded AI evidence briefing API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.ai_briefing.models import (
    AiGovernanceResponse,
    BriefingGenerateRequest,
    EvidenceBriefingResponse,
    InsightAppendResponse,
    InsightListResponse,
    ProviderReadinessResponse,
)
from app.ai_briefing.service import (
    EvidenceBriefingError,
    build_ai_governance_report,
    build_evidence_briefing,
    build_provider_readiness_report,
    generate_and_store_insight,
    list_insights,
)

router = APIRouter(prefix="/ai", tags=["AI Evidence Analyst"])


def _conflict(error: EvidenceBriefingError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "status": "ERROR",
            "error": str(error),
            "broker_orders_submitted": 0,
            "safe_for_live_trading": False,
            "protocol_live_trading_permitted": False,
        },
    )


@router.get("/evidence-briefing", response_model=EvidenceBriefingResponse)
def get_evidence_briefing() -> dict[str, Any]:
    """Return an offline, read-only briefing without storing it."""
    try:
        return build_evidence_briefing()
    except EvidenceBriefingError as error:
        raise _conflict(error) from error


@router.post("/evidence-briefing", response_model=InsightAppendResponse)
def post_evidence_briefing(request: BriefingGenerateRequest) -> dict[str, Any]:
    """Explicitly generate and hash-chain one isolated insight."""
    try:
        return generate_and_store_insight(request)
    except EvidenceBriefingError as error:
        raise _conflict(error) from error


@router.get("/evidence-insights", response_model=InsightListResponse)
def get_evidence_insights() -> dict[str, Any]:
    """Return the verified AI insight audit chain."""
    try:
        return list_insights()
    except EvidenceBriefingError as error:
        raise _conflict(error) from error


@router.get("/governance", response_model=AiGovernanceResponse)
def get_ai_governance() -> dict[str, Any]:
    """Return verified review coverage across AI and annotation chains."""
    try:
        return build_ai_governance_report()
    except EvidenceBriefingError as error:
        raise _conflict(error) from error


@router.get("/provider-readiness", response_model=ProviderReadinessResponse)
def get_provider_readiness() -> dict[str, Any]:
    """Return a secret-free local preflight without contacting a provider."""
    return build_provider_readiness_report()
