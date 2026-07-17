from fastapi import APIRouter

from app.scanner.engine import scan_sample_opportunities
from app.scanner.models import ScannerResult

router = APIRouter(
    prefix="/scanner",
    tags=["scanner"],
)


@router.get(
    "/opportunities",
    response_model=ScannerResult,
)
def get_scanner_opportunities() -> ScannerResult:
    """
    Return deterministic, ranked sample opportunities.

    This endpoint is read-only and performs no broker, network,
    execution, or ledger activity.
    """
    return scan_sample_opportunities()
