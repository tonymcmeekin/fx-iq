from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.broker.oanda_read_only import (
    OandaPracticeReadOnlyClient,
    OandaReadOnlyError,
)
from app.broker.reconciliation import (
    reconcile_open_positions,
)
from app.safety.models import (
    PreflightCheck,
    PreflightReport,
)
from app.safety.preflight import run_preflight

ClientFactory = Callable[..., OandaPracticeReadOnlyClient]


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


def _internal_open_markets(
    runtime_state: dict[str, Any],
) -> set[str]:
    open_positions = runtime_state.get("open_positions")

    if not isinstance(
        open_positions,
        dict,
    ):
        return set()

    return set(open_positions)


def build_broker_backed_preflight(
    *,
    token: str,
    account_id: str,
    runtime_state: dict[str, Any],
    minimum_margin_available: float = 0.0,
    client_factory: ClientFactory = (OandaPracticeReadOnlyClient),
) -> PreflightReport:
    """
    Build a broker-backed safety report using OANDA Practice GETs.

    No order submission, cancellation, position closing or other
    broker mutation is available through this component.
    """
    if not isinstance(
        minimum_margin_available,
        (int, float),
    ):
        raise TypeError("Minimum margin available must be numeric.")

    if minimum_margin_available < 0:
        raise ValueError("Minimum margin available cannot be negative.")

    try:
        client = client_factory(
            token=token,
            account_id=account_id,
        )

        snapshot = client.get_account_snapshot()
    except (
        OandaReadOnlyError,
        ValueError,
        TypeError,
    ) as error:
        return PreflightReport(
            passed=False,
            checks=(
                PreflightCheck(
                    name="broker_snapshot",
                    passed=False,
                    message=(f"OANDA Practice account snapshot could not be read: {error}"),
                ),
            ),
        )

    reconciliation = reconcile_open_positions(
        internal_open_markets=(_internal_open_markets(runtime_state)),
        snapshot=snapshot,
    )

    base_report = run_preflight(
        runtime_state=runtime_state,
        reconciliation=reconciliation,
    )

    broker_checks = (
        _check(
            name="broker_snapshot",
            passed=True,
            success_message=("OANDA Practice account snapshot was read successfully."),
            failure_message=("OANDA Practice account snapshot could not be read."),
        ),
        _check(
            name="practice_source",
            passed=(snapshot.source == "OANDA_PRACTICE"),
            success_message=("Broker source is OANDA Practice."),
            failure_message=("Broker source is not OANDA Practice."),
        ),
        _check(
            name="read_only_client",
            passed=snapshot.read_only,
            success_message=("Broker account access is read-only."),
            failure_message=("Broker account access is not read-only."),
        ),
        _check(
            name="account_id_match",
            passed=(snapshot.account_id == account_id),
            success_message=("Broker account ID matches the configured account."),
            failure_message=("Broker account ID does not match the configured account."),
        ),
        _check(
            name="non_negative_margin",
            passed=(snapshot.margin_available >= 0),
            success_message=("Available margin is non-negative."),
            failure_message=("Available margin is negative."),
        ),
        _check(
            name="minimum_margin_available",
            passed=(snapshot.margin_available >= minimum_margin_available),
            success_message=("Available margin meets the configured minimum."),
            failure_message=("Available margin is below the configured minimum."),
        ),
        _check(
            name="zero_pending_broker_orders",
            passed=(snapshot.pending_order_count == 0),
            success_message=("No pending broker orders exist."),
            failure_message=("Unexpected pending broker orders exist."),
        ),
    )

    checks = broker_checks + base_report.checks

    return PreflightReport(
        passed=all(check.passed for check in checks),
        checks=checks,
    )
