"""Read-only analytics API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.analytics.attribution_reporting import (
    AttributionReportError,
    perform_report,
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
