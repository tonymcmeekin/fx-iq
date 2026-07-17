"""Read-only analytics API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.analytics.attribution_reporting import (
    AttributionReportError,
    perform_report,
)
from app.analytics.overview_reporting import (
    AnalyticsOverviewError,
)
from app.analytics.overview_reporting import (
    perform_report as perform_overview_report,
)
from app.analytics.prospective_health_reporting import (
    ProspectiveHealthReportError,
)
from app.analytics.prospective_health_reporting import (
    perform_report as perform_prospective_health_report,
)

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
)


@router.get("/strategy-attribution")
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


@router.get("/prospective-paper-health")
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


@router.get("/overview")
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
