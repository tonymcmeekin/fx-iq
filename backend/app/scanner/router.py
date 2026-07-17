import os
from typing import Literal

from fastapi import APIRouter, HTTPException, status

from app.market_data.providers.oanda_read_only import (
    OandaReadOnlyMarketDataProvider,
)
from app.scanner.engine import (
    build_provider_scan_requests,
    scan_opportunities,
    scan_sample_opportunities,
)
from app.scanner.models import ScannerResult
from app.scanner.universe import DEFAULT_MARKET_UNIVERSE

ScannerSource = Literal["synthetic", "oanda"]

router = APIRouter(
    prefix="/scanner",
    tags=["scanner"],
)


@router.get(
    "/opportunities",
    response_model=ScannerResult,
)
def get_scanner_opportunities(
    source: ScannerSource = "synthetic",
) -> ScannerResult:
    """
    Return ranked read-only scanner opportunities.

    Synthetic data remains the deterministic default. OANDA access is
    explicit and restricted to completed midpoint candles obtained from
    the practice environment.
    """
    if source == "synthetic":
        return scan_sample_opportunities()

    api_token = os.getenv("OANDA_API_TOKEN", "").strip()

    if not api_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "MARKET_DATA_UNAVAILABLE",
                "source": "oanda",
                "reason": "OANDA_API_TOKEN is not configured.",
                "paper_trading_only": True,
                "live_trading_allowed": False,
                "broker_orders_submitted": 0,
                "ledger_writes_performed": 0,
            },
        )

    provider = OandaReadOnlyMarketDataProvider(
        api_token=api_token,
    )

    try:
        requests = build_provider_scan_requests(
            provider=provider,
            universe=DEFAULT_MARKET_UNIVERSE,
            candle_count=100,
        )

        return scan_opportunities(
            requests=requests,
            network_calls_made=provider.network_calls_made,
        )
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "MARKET_DATA_UNAVAILABLE",
                "source": "oanda",
                "reason": str(error),
                "paper_trading_only": True,
                "live_trading_allowed": False,
                "broker_orders_submitted": 0,
                "ledger_writes_performed": 0,
            },
        ) from error
