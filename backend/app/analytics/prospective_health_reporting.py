"""Shared read-only prospective paper health reporting service."""

from __future__ import annotations

from typing import Any

from scripts.check_prospective_paper_health import (
    PaperHealthError,
    perform_health_check,
)


class ProspectiveHealthReportError(RuntimeError):
    """Raised when the prospective paper runtime cannot be verified."""


def perform_report() -> dict[str, Any]:
    """
    Return the verified prospective paper runtime health report.

    This operation performs no network calls, changes no files,
    and submits no broker orders.
    """
    try:
        report = perform_health_check()
    except (PaperHealthError, OSError) as error:
        raise ProspectiveHealthReportError(str(error)) from error

    return {
        **report,
        "report_network_calls_made": 0,
        "report_files_changed": 0,
        "report_ledger_writes_performed": 0,
        "report_broker_orders_submitted": 0,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
    }
