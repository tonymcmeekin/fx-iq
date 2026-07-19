from dataclasses import FrozenInstanceError

import pytest

from app.broker.reconciliation import (
    BrokerReconciliationReport,
)
from app.paper_trading.runtime_state import (
    empty_runtime_state,
)
from app.safety import (
    PreflightCheck,
    PreflightReport,
    run_preflight,
)


def _reconciliation(
    **overrides: object,
) -> BrokerReconciliationReport:
    values: dict[str, object] = {
        "internal_open_markets": (),
        "broker_open_markets": (),
        "missing_at_broker": (),
        "unexpected_at_broker": (),
        "is_reconciled": True,
        "network_calls_made": 1,
        "broker_orders_submitted": 0,
        "paper_trading_only": True,
        "live_trading_allowed": False,
    }
    values.update(overrides)

    return BrokerReconciliationReport(**values)


def _check_by_name(
    report: PreflightReport,
    name: str,
) -> PreflightCheck:
    return next(check for check in report.checks if check.name == name)


def test_preflight_passes_when_all_checks_pass() -> None:
    report = run_preflight(
        runtime_state=empty_runtime_state(),
        reconciliation=_reconciliation(),
    )

    assert report.passed is True
    assert report.failed_checks == ()
    assert len(report.checks) == 6


def test_preflight_fails_when_positions_do_not_reconcile() -> None:
    report = run_preflight(
        runtime_state=empty_runtime_state(),
        reconciliation=_reconciliation(
            is_reconciled=False,
            missing_at_broker=("EUR_USD",),
        ),
    )

    check = _check_by_name(
        report,
        "position_reconciliation",
    )

    assert report.passed is False
    assert check.passed is False


def test_preflight_fails_when_live_trading_is_enabled() -> None:
    report = run_preflight(
        runtime_state=empty_runtime_state(),
        reconciliation=_reconciliation(
            live_trading_allowed=True,
        ),
    )

    check = _check_by_name(
        report,
        "live_trading_disabled",
    )

    assert report.passed is False
    assert check.passed is False
    assert check.message == "Live trading is enabled."


def test_preflight_fails_when_paper_mode_is_disabled() -> None:
    report = run_preflight(
        runtime_state=empty_runtime_state(),
        reconciliation=_reconciliation(
            paper_trading_only=False,
        ),
    )

    assert report.passed is False
    assert (
        _check_by_name(
            report,
            "paper_trading_only",
        ).passed
        is False
    )


def test_preflight_fails_when_broker_order_count_is_nonzero() -> None:
    report = run_preflight(
        runtime_state=empty_runtime_state(),
        reconciliation=_reconciliation(
            broker_orders_submitted=1,
        ),
    )

    assert report.passed is False
    assert (
        _check_by_name(
            report,
            "zero_broker_orders",
        ).passed
        is False
    )


def test_preflight_rejects_negative_network_call_count() -> None:
    report = run_preflight(
        runtime_state=empty_runtime_state(),
        reconciliation=_reconciliation(
            network_calls_made=-1,
        ),
    )

    assert report.passed is False
    assert (
        _check_by_name(
            report,
            "network_call_count",
        ).passed
        is False
    )


def test_preflight_reports_invalid_runtime_state() -> None:
    report = run_preflight(
        runtime_state={},
        reconciliation=_reconciliation(),
    )

    check = _check_by_name(
        report,
        "runtime_state",
    )

    assert report.passed is False
    assert check.passed is False
    assert "verification failed" in check.message.lower()


def test_failed_checks_returns_only_failed_entries() -> None:
    report = run_preflight(
        runtime_state=empty_runtime_state(),
        reconciliation=_reconciliation(
            is_reconciled=False,
            paper_trading_only=False,
        ),
    )

    assert tuple(check.name for check in report.failed_checks) == (
        "position_reconciliation",
        "paper_trading_only",
    )


def test_preflight_can_report_multiple_failures() -> None:
    report = run_preflight(
        runtime_state={},
        reconciliation=_reconciliation(
            is_reconciled=False,
            paper_trading_only=False,
            live_trading_allowed=True,
            broker_orders_submitted=2,
            network_calls_made=-1,
        ),
    )

    assert report.passed is False
    assert len(report.failed_checks) == 6


def test_preflight_models_are_immutable() -> None:
    check = PreflightCheck(
        name="example",
        passed=True,
        message="Passed.",
    )
    report = PreflightReport(
        passed=True,
        checks=(check,),
    )

    with pytest.raises(FrozenInstanceError):
        check.passed = False  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        report.passed = False  # type: ignore[misc]
