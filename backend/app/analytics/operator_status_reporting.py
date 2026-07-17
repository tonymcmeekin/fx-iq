"""Shared read-only prospective paper operator-status service."""

from __future__ import annotations

from typing import Any

from scripts.report_prospective_paper_operator_status import (
    build_operator_status,
)


class OperatorStatusReportError(RuntimeError):
    """Raised when the operator-status report cannot be produced."""


def perform_report() -> dict[str, Any]:
    """
    Build the verified prospective paper operator-status report.

    The report is read-only, accepts no caller-supplied runtime paths,
    submits no broker orders, and cannot permit live trading.
    """
    try:
        report = build_operator_status()
    except (OSError, RuntimeError, ValueError) as error:
        raise OperatorStatusReportError(str(error)) from error

    report["safe_for_live_trading"] = False
    report["protocol_live_trading_permitted"] = False
    report["network_calls_made"] = 0
    report["files_changed"] = 0
    report["ledger_writes_performed"] = 0
    report["broker_orders_submitted"] = 0

    return report
