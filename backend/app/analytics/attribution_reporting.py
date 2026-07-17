"""Shared read-only strategy attribution reporting service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.analytics.ledger_attribution import (
    LedgerAttributionError,
    build_ledger_attribution_report,
)
from app.paper_trading.ledger import LedgerIntegrityError

LEDGER_PATH = Path("paper_ledger/events.jsonl")


class AttributionReportError(RuntimeError):
    """Raised when a verified attribution report cannot be generated."""


def perform_report() -> dict[str, Any]:
    """
    Build a report from the configured immutable paper ledger.

    This service performs no ledger writes and submits no broker orders.
    """
    try:
        return build_ledger_attribution_report(
            LEDGER_PATH,
        )
    except LedgerIntegrityError as error:
        raise AttributionReportError(f"Ledger integrity check failed: {error}") from error
    except LedgerAttributionError as error:
        raise AttributionReportError(f"Ledger attribution failed: {error}") from error
