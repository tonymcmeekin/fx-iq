"""Read-only analytics API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.analytics.attribution_reporting import (
    AttributionReportError,
    perform_report,
)
from app.analytics.evidence_cockpit_reporting import (
    EvidenceCockpitError,
    build_evidence_cockpit,
)
from app.analytics.models import (
    AnalyticsErrorResponse,
    AnalyticsOverviewResponse,
    AnalyticsReadinessExplanationResponse,
    AnalyticsReadinessResponse,
    EvidenceCockpitResponse,
    OperatorAlertReportResponse,
    OperatorStatusResponse,
    OutcomeExplorerResponse,
    PortfolioIntelligenceResponse,
    ProspectivePaperHealthResponse,
    StrategyAttributionResponse,
)
from app.analytics.operator_alert_reporting import (
    OperatorAlertReportError,
    build_operator_alert_report,
)
from app.analytics.operator_status_reporting import (
    OperatorStatusReportError,
)
from app.analytics.operator_status_reporting import (
    perform_report as perform_operator_status_report,
)
from app.analytics.outcome_explorer_reporting import (
    OutcomeExplorerError,
    build_outcome_explorer_report,
)
from app.analytics.overview_reporting import (
    AnalyticsOverviewError,
)
from app.analytics.overview_reporting import (
    perform_report as perform_overview_report,
)
from app.analytics.portfolio_intelligence_reporting import (
    PortfolioIntelligenceError,
    build_portfolio_intelligence_report,
)
from app.analytics.prospective_health_reporting import (
    ProspectiveHealthReportError,
)
from app.analytics.prospective_health_reporting import (
    perform_report as perform_prospective_health_report,
)
from app.analytics.readiness_explanation_reporting import (
    ReadinessExplanationError,
    build_readiness_explanation,
)
from app.analytics.readiness_reporting import (
    ReadinessReportError,
    build_readiness_report,
)

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
)


@router.get(
    "/alerts",
    response_model=OperatorAlertReportResponse,
    responses={409: {"model": AnalyticsErrorResponse}},
)
def get_operator_alerts() -> dict[str, Any]:
    """Return active notification-only alerts from verified evidence."""
    try:
        return build_operator_alert_report()
    except OperatorAlertReportError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "ERROR",
                "error": str(error),
                "network_calls_made": 0,
                "files_changed": 0,
                "ledger_writes_performed": 0,
                "broker_orders_submitted": 0,
                "safe_for_live_trading": False,
                "protocol_live_trading_permitted": False,
            },
        ) from error


@router.get(
    "/portfolio-intelligence",
    response_model=PortfolioIntelligenceResponse,
    responses={409: {"model": AnalyticsErrorResponse}},
)
def get_portfolio_intelligence() -> dict[str, Any]:
    """Return verified paper exposure and return correlation context."""
    try:
        return build_portfolio_intelligence_report()
    except PortfolioIntelligenceError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "ERROR",
                "error": str(error),
                "network_calls_made": 0,
                "files_changed": 0,
                "ledger_writes_performed": 0,
                "broker_orders_submitted": 0,
                "safe_for_live_trading": False,
                "protocol_live_trading_permitted": False,
            },
        ) from error


@router.get(
    "/outcome-explorer",
    response_model=OutcomeExplorerResponse,
    responses={409: {"model": AnalyticsErrorResponse}},
)
def get_outcome_explorer() -> dict[str, Any]:
    """Return sparse-safe outcome analysis from verified observations."""
    try:
        return build_outcome_explorer_report()
    except OutcomeExplorerError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "ERROR",
                "error": str(error),
                "network_calls_made": 0,
                "files_changed": 0,
                "ledger_writes_performed": 0,
                "broker_orders_submitted": 0,
                "safe_for_live_trading": False,
                "protocol_live_trading_permitted": False,
            },
        ) from error


@router.get(
    "/evidence-cockpit",
    response_model=EvidenceCockpitResponse,
    responses={409: {"model": AnalyticsErrorResponse}},
)
def get_evidence_cockpit() -> dict[str, Any]:
    """Return the canonical non-mutating paper-evidence cockpit."""
    try:
        return build_evidence_cockpit()
    except EvidenceCockpitError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "ERROR",
                "error": str(error),
                "network_calls_made": 0,
                "files_changed": 0,
                "ledger_writes_performed": 0,
                "broker_orders_submitted": 0,
                "safe_for_live_trading": False,
                "protocol_live_trading_permitted": False,
            },
        ) from error


@router.get(
    "/strategy-attribution",
    response_model=StrategyAttributionResponse,
    responses={409: {"model": AnalyticsErrorResponse}},
)
def get_strategy_attribution() -> dict[str, Any]:
    """
    Return attribution derived from the verified paper ledger.

    No filesystem path is accepted from the caller.
    """
    try:
        return perform_report()
    except AttributionReportError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "ERROR",
                "error": str(error),
                "safe_for_live_trading": False,
                "protocol_live_trading_permitted": False,
                "ledger_writes_performed": 0,
                "broker_orders_submitted": 0,
            },
        ) from error


@router.get(
    "/prospective-paper-health",
    response_model=ProspectivePaperHealthResponse,
    responses={409: {"model": AnalyticsErrorResponse}},
)
def get_prospective_paper_health() -> dict[str, Any]:
    """
    Return the verified prospective paper runtime health report.

    No caller-supplied filesystem paths are accepted.
    """
    try:
        return perform_prospective_health_report()
    except ProspectiveHealthReportError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "UNHEALTHY",
                "error": str(error),
                "network_calls_made": 0,
                "files_changed": 0,
                "ledger_writes_performed": 0,
                "broker_orders_submitted": 0,
                "safe_for_live_trading": False,
                "protocol_live_trading_permitted": False,
            },
        ) from error


@router.get(
    "/overview",
    response_model=AnalyticsOverviewResponse,
    responses={409: {"model": AnalyticsErrorResponse}},
)
def get_analytics_overview() -> dict[str, Any]:
    """
    Return one verified operator-facing analytics overview.

    No caller-supplied filesystem paths are accepted.
    """
    try:
        return perform_overview_report()
    except AnalyticsOverviewError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "ERROR",
                "error": str(error),
                "network_calls_made": 0,
                "files_changed": 0,
                "ledger_writes_performed": 0,
                "broker_orders_submitted": 0,
                "safe_for_live_trading": False,
                "protocol_live_trading_permitted": False,
            },
        ) from error


@router.get(
    "/operator-status",
    response_model=OperatorStatusResponse,
    responses={409: {"model": AnalyticsErrorResponse}},
)
def get_operator_status() -> dict[str, Any]:
    """
    Return the verified prospective paper operator-status report.

    No caller-supplied filesystem paths are accepted.
    """
    try:
        return perform_operator_status_report()
    except OperatorStatusReportError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "ERROR",
                "error": str(error),
                "network_calls_made": 0,
                "files_changed": 0,
                "ledger_writes_performed": 0,
                "broker_orders_submitted": 0,
                "safe_for_live_trading": False,
                "protocol_live_trading_permitted": False,
            },
        ) from error


@router.get(
    "/readiness",
    response_model=AnalyticsReadinessResponse,
    responses={409: {"model": AnalyticsErrorResponse}},
)
def readiness() -> dict[str, Any]:
    """Return protocol-grounded readiness status."""

    try:
        report = build_readiness_report()
    except ReadinessReportError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "ERROR",
                "error": str(error),
                "network_calls_made": 0,
                "files_changed": 0,
                "ledger_writes_performed": 0,
                "broker_orders_submitted": 0,
                "safe_for_live_trading": False,
                "protocol_live_trading_permitted": (False),
            },
        ) from error

    return {
        **report,
        "live_trading_allowed": False,
        "network_calls_made": 0,
        "files_changed": 0,
        "ledger_writes_performed": 0,
        "broker_orders_submitted": 0,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
    }


@router.get(
    "/readiness-explanation",
    response_model=(AnalyticsReadinessExplanationResponse),
    responses={409: {"model": AnalyticsErrorResponse}},
)
def readiness_explanation() -> dict[str, Any]:
    """Return a deterministic readiness briefing."""

    try:
        report = build_readiness_explanation()
    except (
        ReadinessExplanationError,
        ReadinessReportError,
    ) as error:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "ERROR",
                "error": str(error),
                "network_calls_made": 0,
                "files_changed": 0,
                "ledger_writes_performed": 0,
                "broker_orders_submitted": 0,
                "safe_for_live_trading": False,
                "protocol_live_trading_permitted": (False),
            },
        ) from error

    return {
        **report,
        "live_trading_allowed": False,
        "network_calls_made": 0,
        "files_changed": 0,
        "ledger_writes_performed": 0,
        "broker_orders_submitted": 0,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
    }
