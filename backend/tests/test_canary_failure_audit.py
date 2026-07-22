import json
from datetime import UTC, datetime

import pytest

from app.broker.canary_failure_audit import (
    CanaryFailureAuditError,
    append_canary_failure_audit,
    read_canary_failure_audit,
)
from app.broker.canary_gateway import CanaryFailureContext


def context(rehearsal_id="failed-canary-001"):
    return CanaryFailureContext(
        rehearsal_id=rehearsal_id,
        account_fingerprint="a" * 64,
        stage="FINAL_RECONCILIATION",
        failure_type="CanaryGatewayError",
        failure_message="Practice trade closure could not be confirmed.",
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
    )


def test_failure_audit_is_hash_chained_and_idempotent(tmp_path):
    path = tmp_path / "failures.jsonl"
    first, created = append_canary_failure_audit(
        path, context(), failed_at_utc=datetime(2026, 7, 22, 12, tzinfo=UTC)
    )
    repeated, repeated_created = append_canary_failure_audit(path, context())
    assert created is True
    assert repeated_created is False
    assert repeated == first
    assert len(read_canary_failure_audit(path)) == 1


def test_failure_audit_detects_tampering(tmp_path):
    path = tmp_path / "failures.jsonl"
    append_canary_failure_audit(path, context())
    payload = json.loads(path.read_text())
    payload["operator_action_required"] = False
    path.write_text(json.dumps(payload) + "\n")
    with pytest.raises(CanaryFailureAuditError, match="hash mismatch"):
        read_canary_failure_audit(path)


def test_failure_audit_rejects_live_order_record(tmp_path):
    unsafe = context().__class__(**{**context().__dict__, "live_orders_submitted": 1})
    with pytest.raises(CanaryFailureAuditError, match="live-order"):
        append_canary_failure_audit(tmp_path / "failures.jsonl", unsafe)
