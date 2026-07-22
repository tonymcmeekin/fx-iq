"""Read-only broker and canary safety API."""

from fastapi import APIRouter

from app.broker.api_models import CanaryReadinessResponse
from app.broker.canary_reporting import build_canary_readiness_report

router = APIRouter(prefix="/broker", tags=["Broker Safety"])


@router.get("/canary-readiness", response_model=CanaryReadinessResponse)
def get_canary_readiness() -> dict[str, object]:
    """Verify practice rehearsal evidence without broker network access."""
    return build_canary_readiness_report()
