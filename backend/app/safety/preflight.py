from __future__ import annotations

from typing import Any

from app.broker.reconciliation import (
    BrokerReconciliationReport,
)
from app.paper_trading.runtime_state import (
    RuntimeStateError,
    verify_runtime_state,
)
from app.safety.models import (
    PreflightCheck,
    PreflightReport,
)


def _check(
    *,
    name: str,
    passed: bool,
    success_message: str,
    failure_message: str,
) -> PreflightCheck:
    return PreflightCheck(
        name=name,
        passed=passed,
        message=(success_message if passed else failure_message),
    )


def _runtime_state_check(
    runtime_state: dict[str, Any],
) -> PreflightCheck:
    try:
        verify_runtime_state(runtime_state)
    except (RuntimeStateError, ValueError, TypeError) as error:
        return PreflightCheck(
            name="runtime_state",
            passed=False,
            message=(f"Runtime state verification failed: {error}"),
        )

    return PreflightCheck(
        name="runtime_state",
        passed=True,
        message="Runtime state verification passed.",
    )


def run_preflight(
    *,
    runtime_state: dict[str, Any],
    reconciliation: BrokerReconciliationReport,
) -> PreflightReport:
    checks = (
        _runtime_state_check(runtime_state),
        _check(
            name="position_reconciliation",
            passed=reconciliation.is_reconciled,
            success_message=("Internal and broker positions reconcile."),
            failure_message=("Internal and broker positions do not reconcile."),
        ),
        _check(
            name="paper_trading_only",
            passed=reconciliation.paper_trading_only,
            success_message=("Paper-trading-only mode is enforced."),
            failure_message=("Paper-trading-only mode is not enforced."),
        ),
        _check(
            name="live_trading_disabled",
            passed=(not reconciliation.live_trading_allowed),
            success_message="Live trading is disabled.",
            failure_message="Live trading is enabled.",
        ),
        _check(
            name="zero_broker_orders",
            passed=(reconciliation.broker_orders_submitted == 0),
            success_message=("No broker orders have been submitted."),
            failure_message=("Broker order submission count is not zero."),
        ),
        _check(
            name="network_call_count",
            passed=(reconciliation.network_calls_made >= 0),
            success_message=("Network call count is valid."),
            failure_message=("Network call count cannot be negative."),
        ),
    )

    return PreflightReport(
        passed=all(check.passed for check in checks),
        checks=checks,
    )
