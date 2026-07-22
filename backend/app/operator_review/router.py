"""Operator review API separated from trading and analytics evidence."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.analytics.models import AnalyticsErrorResponse
from app.operator_review.models import (
    AnnotationAppendResponse,
    AnnotationListResponse,
    AnnotationRequest,
)
from app.operator_review.service import (
    OperatorReviewError,
    create_operator_annotation,
    list_operator_annotations,
)

router = APIRouter(prefix="/operator-review", tags=["Operator Review"])


def _conflict(error: OperatorReviewError) -> HTTPException:
    return HTTPException(
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
    )


@router.get(
    "/annotations",
    response_model=AnnotationListResponse,
    responses={409: {"model": AnalyticsErrorResponse}},
)
def get_annotations() -> dict[str, Any]:
    """Return the verified append-only operator annotation chain."""
    try:
        return list_operator_annotations()
    except OperatorReviewError as error:
        raise _conflict(error) from error


@router.post(
    "/annotations",
    response_model=AnnotationAppendResponse,
    responses={409: {"model": AnalyticsErrorResponse}},
)
def post_annotation(request: AnnotationRequest) -> dict[str, Any]:
    """Append one immutable evidence-linked operator annotation."""
    try:
        return create_operator_annotation(request)
    except OperatorReviewError as error:
        raise _conflict(error) from error
