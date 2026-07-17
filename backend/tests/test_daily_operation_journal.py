"""Tests for the append-only daily-operation journal."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.paper_trading.daily_operation_journal import (
    DailyOperationJournalError,
    append_daily_operation_record,
    build_daily_operation_record,
    read_daily_operation_records,
)


def valid_record(
    *,
    operation_id: str = "operation-1",
    status: str = "REPORT_ONLY",
    operation_mode: str = "REPORT_ONLY",
    session_executed: bool = False,
    session_already_completed: bool = False,
    failure_type: str | None = None,
    failure_message: str | None = None,
) -> dict:
    return build_daily_operation_record(
        operation_id=operation_id,
        started_at_utc=datetime(
            2026,
            7,
            17,
            8,
            0,
            tzinfo=UTC,
        ),
        completed_at_utc=datetime(
            2026,
            7,
            17,
            8,
            1,
            tzinfo=UTC,
        ),
        status=status,
        operation_mode=operation_mode,
        target_session_date=None,
        session_executed=session_executed,
        session_already_completed=session_already_completed,
        session_receipt_path=None,
        runtime_health="HEALTHY",
        operator_status="OBSERVING",
        evidence_gate_status="NOT_READY",
        completed_sessions=1,
        candidate_balance=10000.0,
        shadow_balance=10000.0,
        broker_orders_sent=0,
        safe_for_live_trading=False,
        protocol_live_trading_permitted=False,
        git_commit="01d7489",
        hostname="test-host",
        pid=1234,
        failure_type=failure_type,
        failure_message=failure_message,
    )


def test_builds_valid_record():
    record = valid_record()

    assert record["schema_version"] == 1
    assert record["status"] == "REPORT_ONLY"
    assert len(record["record_hash"]) == 64


def test_invalid_status_is_rejected():
    with pytest.raises(
        DailyOperationJournalError,
        match="status",
    ):
        valid_record(
            status="UNKNOWN",
        )


def test_broker_orders_are_rejected():
    with pytest.raises(
        DailyOperationJournalError,
        match="zero broker orders",
    ):
        build_daily_operation_record(
            operation_id="operation-1",
            started_at_utc=datetime.now(UTC),
            completed_at_utc=datetime.now(UTC),
            status="REPORT_ONLY",
            operation_mode="REPORT_ONLY",
            target_session_date=None,
            session_executed=False,
            session_already_completed=False,
            session_receipt_path=None,
            runtime_health="HEALTHY",
            operator_status="OBSERVING",
            evidence_gate_status="NOT_READY",
            completed_sessions=1,
            candidate_balance=10000.0,
            shadow_balance=10000.0,
            broker_orders_sent=1,
            safe_for_live_trading=False,
            protocol_live_trading_permitted=False,
            git_commit="01d7489",
            hostname="test-host",
            pid=1234,
        )


def test_appends_two_records(
    tmp_path: Path,
):
    journal_path = tmp_path / "daily_operations.jsonl"

    append_daily_operation_record(
        journal_path,
        valid_record(
            operation_id="operation-1",
        ),
    )
    append_daily_operation_record(
        journal_path,
        valid_record(
            operation_id="operation-2",
        ),
    )

    assert (
        len(
            journal_path.read_text(
                encoding="utf-8",
            ).splitlines()
        )
        == 2
    )


def test_reads_back_records(
    tmp_path: Path,
):
    journal_path = tmp_path / "daily_operations.jsonl"

    append_daily_operation_record(
        journal_path,
        valid_record(
            operation_id="operation-1",
        ),
    )
    append_daily_operation_record(
        journal_path,
        valid_record(
            operation_id="operation-2",
        ),
    )

    records = read_daily_operation_records(
        journal_path,
    )

    assert [record["operation_id"] for record in records] == [
        "operation-1",
        "operation-2",
    ]


def test_malformed_jsonl_is_rejected(
    tmp_path: Path,
):
    journal_path = tmp_path / "daily_operations.jsonl"
    journal_path.write_text(
        "not-json\n",
        encoding="utf-8",
    )

    with pytest.raises(
        DailyOperationJournalError,
        match="not valid JSON",
    ):
        read_daily_operation_records(
            journal_path,
        )


def test_tampered_record_hash_is_rejected(
    tmp_path: Path,
):
    journal_path = tmp_path / "daily_operations.jsonl"
    record = valid_record()
    record["candidate_balance"] = 999999.0

    journal_path.write_text(
        json.dumps(record) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        DailyOperationJournalError,
        match="hash verification failed",
    ):
        read_daily_operation_records(
            journal_path,
        )


def test_failure_record_is_accepted():
    record = valid_record(
        status="FAILED",
        failure_type="DailyOperationError",
        failure_message="Runtime health check failed.",
    )

    assert record["status"] == "FAILED"
    assert record["failure_type"] == "DailyOperationError"


def test_naive_datetime_is_rejected():
    with pytest.raises(
        DailyOperationJournalError,
        match="timezone-aware",
    ):
        build_daily_operation_record(
            operation_id="operation-1",
            started_at_utc=datetime(
                2026,
                7,
                17,
                8,
                0,
            ),
            completed_at_utc=datetime.now(UTC),
            status="REPORT_ONLY",
            operation_mode="REPORT_ONLY",
            target_session_date=None,
            session_executed=False,
            session_already_completed=False,
            session_receipt_path=None,
            runtime_health="HEALTHY",
            operator_status="OBSERVING",
            evidence_gate_status="NOT_READY",
            completed_sessions=1,
            candidate_balance=10000.0,
            shadow_balance=10000.0,
            broker_orders_sent=0,
            safe_for_live_trading=False,
            protocol_live_trading_permitted=False,
            git_commit="01d7489",
            hostname="test-host",
            pid=1234,
        )
