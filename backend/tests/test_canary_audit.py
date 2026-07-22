import json
from datetime import UTC, datetime

import pytest

from app.broker.canary_audit import (
    CanaryAuditError,
    append_canary_audit,
    read_canary_audit,
)
from app.broker.canary_gateway import CanaryRehearsalResult


def result(rehearsal_id="canary-audit-001"):
    return CanaryRehearsalResult(
        status="PRACTICE_REHEARSAL_COMPLETE",
        environment="practice",
        rehearsal_id=rehearsal_id,
        account_fingerprint="a" * 64,
        instrument="EUR_USD",
        direction="BUY",
        units=1,
        entry_transaction_id="1",
        trade_id="2",
        close_transaction_id="3",
        network_calls_made=7,
        practice_entry_orders_submitted=1,
        practice_close_orders_submitted=1,
        live_orders_submitted=0,
        position_verified_open=True,
        position_verified_closed=True,
        live_canary_build_enabled=False,
    )


def test_canary_audit_is_hash_chained_and_idempotent(tmp_path):
    path = tmp_path / "canary.jsonl"
    first, created = append_canary_audit(
        path, result(), completed_at_utc=datetime(2026, 7, 22, 12, tzinfo=UTC)
    )
    repeated, repeated_created = append_canary_audit(
        path, result(), completed_at_utc=datetime(2026, 7, 22, 13, tzinfo=UTC)
    )
    assert created is True
    assert repeated_created is False
    assert repeated == first
    assert len(read_canary_audit(path)) == 1
    assert first["live_orders_submitted"] == 0


def test_canary_audit_detects_tampering(tmp_path):
    path = tmp_path / "canary.jsonl"
    append_canary_audit(path, result())
    payload = json.loads(path.read_text())
    payload["units"] = 2
    path.write_text(json.dumps(payload) + "\n")
    with pytest.raises(CanaryAuditError, match="hash mismatch"):
        read_canary_audit(path)


def test_canary_audit_rejects_live_order_result(tmp_path):
    unsafe = result().__class__(**{**result().__dict__, "live_orders_submitted": 1})
    with pytest.raises(CanaryAuditError, match="live-order"):
        append_canary_audit(tmp_path / "canary.jsonl", unsafe)
