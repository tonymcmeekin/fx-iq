from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.broker import router
from app.broker.canary_audit import append_canary_audit
from app.broker.canary_failure_audit import append_canary_failure_audit
from app.broker.canary_gateway import CanaryFailureContext, CanaryRehearsalResult
from app.broker.canary_reporting import (
    MINIMUM_PRACTICE_REHEARSALS,
    build_canary_readiness_report,
)
from app.main import app


def result(index: int) -> CanaryRehearsalResult:
    return CanaryRehearsalResult(
        status="PRACTICE_REHEARSAL_COMPLETE",
        environment="practice",
        rehearsal_id=f"readiness-rehearsal-{index:03d}",
        account_fingerprint="a" * 64,
        instrument="EUR_GBP",
        direction="BUY",
        units=1,
        entry_transaction_id=f"entry-{index}",
        trade_id=f"trade-{index}",
        close_transaction_id=f"close-{index}",
        network_calls_made=8,
        practice_entry_orders_submitted=1,
        practice_close_orders_submitted=1,
        live_orders_submitted=0,
        position_verified_open=True,
        position_verified_closed=True,
        live_canary_build_enabled=False,
    )


def test_empty_canary_readiness_is_locked_and_read_only(tmp_path):
    report = build_canary_readiness_report(
        audit_path=tmp_path / "missing.jsonl",
        failure_audit_path=tmp_path / "missing-failures.jsonl",
    )
    assert report["status"] == "NO_EVIDENCE"
    assert report["rehearsal_count"] == 0
    assert report["live_execution_locked"] is True
    assert report["live_canary_build_enabled"] is False
    assert report["live_trading_allowed"] is False
    assert report["network_calls_made"] == 0
    assert report["files_changed"] == 0


def test_canary_readiness_tracks_rehearsal_target_without_unlocking_live(tmp_path):
    path = tmp_path / "canary.jsonl"
    start = datetime(2026, 7, 22, 12, tzinfo=UTC)
    for index in range(MINIMUM_PRACTICE_REHEARSALS):
        append_canary_audit(
            path,
            result(index),
            completed_at_utc=start + timedelta(days=index),
        )

    report = build_canary_readiness_report(
        audit_path=path,
        failure_audit_path=tmp_path / "missing-failures.jsonl",
    )
    assert report["status"] == "REHEARSAL_TARGET_MET"
    assert report["operational_rehearsal_target_met"] is True
    assert report["all_positions_verified_closed"] is True
    assert report["practice_entry_orders_submitted"] == MINIMUM_PRACTICE_REHEARSALS
    assert report["practice_close_orders_submitted"] == MINIMUM_PRACTICE_REHEARSALS
    assert report["live_orders_submitted"] == 0
    assert report["live_execution_locked"] is True
    assert report["live_trading_allowed"] is False


def test_canary_readiness_reports_integrity_failure_without_network(tmp_path):
    path = tmp_path / "canary.jsonl"
    path.write_text("not-json\n")
    report = build_canary_readiness_report(
        audit_path=path,
        failure_audit_path=tmp_path / "missing-failures.jsonl",
    )
    assert report["status"] == "INTEGRITY_ERROR"
    assert report["blocking_issues"]
    assert report["network_calls_made"] == 0
    assert report["live_execution_locked"] is True


def test_canary_readiness_endpoint_has_strict_safety_contract(monkeypatch):
    report = build_canary_readiness_report(
        audit_path=Path(__file__).parent / "missing.jsonl",
        failure_audit_path=Path(__file__).parent / "missing-failures.jsonl",
    )
    monkeypatch.setattr(router, "build_canary_readiness_report", lambda: report)
    response = TestClient(app).get("/broker/canary-readiness")
    assert response.status_code == 200
    assert response.json()["live_orders_submitted"] == 0
    assert response.json()["live_execution_locked"] is True
    schema = app.openapi()["paths"]["/broker/canary-readiness"]
    assert schema["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/CanaryReadinessResponse")


def test_failure_requires_action_and_resets_qualifying_rehearsals(tmp_path):
    success_path = tmp_path / "canary.jsonl"
    failure_path = tmp_path / "failures.jsonl"
    append_canary_audit(
        success_path,
        result(1),
        completed_at_utc=datetime(2026, 7, 21, 12, tzinfo=UTC),
    )
    append_canary_failure_audit(
        failure_path,
        CanaryFailureContext(
            rehearsal_id="failed-readiness-001",
            account_fingerprint="a" * 64,
            stage="FINAL_RECONCILIATION",
            failure_type="CanaryGatewayError",
            failure_message="Closure could not be confirmed.",
            network_calls_made=7,
            entry_request_attempted=True,
            entry_order_confirmed=True,
            close_request_attempted=True,
            close_order_confirmed=True,
            emergency_close_attempted=False,
            emergency_close_confirmed=False,
            final_reconciliation_confirmed=False,
            operator_action_required=True,
            live_orders_submitted=0,
        ),
        failed_at_utc=datetime(2026, 7, 22, 12, tzinfo=UTC),
    )
    report = build_canary_readiness_report(
        audit_path=success_path,
        failure_audit_path=failure_path,
    )
    assert report["status"] == "ACTION_REQUIRED"
    assert report["rehearsal_count"] == 1
    assert report["qualifying_rehearsal_count"] == 0
    assert report["gslo_rehearsal_count"] == 1
    assert report["failed_rehearsal_count"] == 1
    assert report["unresolved_failure_count"] == 1
    assert report["operational_rehearsal_target_met"] is False
    assert report["live_execution_locked"] is True
