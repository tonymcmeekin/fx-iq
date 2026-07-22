from __future__ import annotations

import subprocess

import pytest

from scripts import run_prospective_paper_daily_operation as daily


def healthy_report():
    return {
        "status": "HEALTHY",
        "broker_orders_sent": 0,
    }


def operator_report():
    return {
        "status": "OBSERVING",
        "runtime_health": "HEALTHY",
        "evidence_gate_status": "NOT_READY",
        "completed_sessions": 1,
        "positions_closed": 0,
        "candidate_balance": 10000.0,
        "shadow_balance": 10000.0,
        "safe_to_continue_paper_observation": True,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
        "broker_orders_sent": 0,
    }


def test_report_only_operation(monkeypatch):
    responses = iter(
        [
            healthy_report(),
            healthy_report(),
            operator_report(),
        ]
    )

    monkeypatch.setattr(
        daily,
        "run_json_command",
        lambda command: next(responses),
    )

    result = daily.run_daily_operation(
        report_only=True,
        use_oanda_practice=False,
        session_date=None,
        candle_count=None,
    )

    assert result["daily_operation_status"] == "COMPLETED"
    assert result["operation_mode"] == "REPORT_ONLY"
    assert result["session_executed"] is False
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False


def test_session_requires_explicit_practice_permission():
    with pytest.raises(
        daily.DailyOperationError,
        match="explicit --use-oanda-practice",
    ):
        daily.run_daily_operation(
            report_only=False,
            use_oanda_practice=False,
            session_date=None,
            candle_count=None,
        )


def test_report_only_rejects_practice_flag():
    with pytest.raises(
        daily.DailyOperationError,
        match="cannot be combined",
    ):
        daily.run_daily_operation(
            report_only=True,
            use_oanda_practice=True,
            session_date=None,
            candle_count=None,
        )


def test_session_operation_runs_four_commands(monkeypatch):
    commands = []

    responses = iter(
        [
            healthy_report(),
            {
                "status": "COMPLETED",
                "session_date": "2026-07-18",
            },
            healthy_report(),
            operator_report(),
        ]
    )

    def fake_run(command):
        commands.append(command)
        return next(responses)

    monkeypatch.setattr(
        daily,
        "run_json_command",
        fake_run,
    )

    result = daily.run_daily_operation(
        report_only=False,
        use_oanda_practice=True,
        session_date="2026-07-18",
        candle_count=500,
    )

    assert len(commands) == 4
    assert result["session_executed"] is True
    assert result["session_result"]["status"] == "COMPLETED"
    assert "--use-oanda-practice" in commands[1]
    assert "--session-date" in commands[1]
    assert "--candle-count" in commands[1]


def test_unhealthy_preflight_stops_operation(monkeypatch):
    monkeypatch.setattr(
        daily,
        "run_json_command",
        lambda command: {
            "status": "UNHEALTHY",
            "broker_orders_sent": 0,
        },
    )

    with pytest.raises(
        daily.DailyOperationError,
        match="preflight",
    ):
        daily.run_daily_operation(
            report_only=True,
            use_oanda_practice=False,
            session_date=None,
            candle_count=None,
        )


def test_recovery_can_restore_unhealthy_preflight(
    monkeypatch,
):
    commands = []
    responses = iter(
        [
            {
                "status": "UNHEALTHY",
                "broker_orders_sent": 0,
            },
            {
                "status": "RECOVERED",
                "broker_orders_sent": 0,
            },
            healthy_report(),
            {
                "status": "COMPLETED",
                "session_date": "2026-07-22",
            },
            healthy_report(),
            operator_report(),
        ]
    )

    def fake_run(command):
        commands.append(command)
        return next(responses)

    monkeypatch.setattr(
        daily,
        "run_json_command",
        fake_run,
    )

    result = daily.run_daily_operation(
        report_only=False,
        use_oanda_practice=True,
        session_date="2026-07-22",
        candle_count=100,
        recover_incomplete_session=True,
    )

    assert str(daily.RECOVERY_SCRIPT) in commands[1]
    assert "--apply" in commands[1]
    assert result[
        "incomplete_session_recovery"
    ]["status"] == "RECOVERED"
    assert result["session_executed"] is True


def test_completed_session_reconciles_staged_observations(
    monkeypatch,
):
    commands = []
    completed_health = {
        **healthy_report(),
        "last_completed_session_date": "2026-07-22",
    }
    responses = iter(
        [
            completed_health,
            {
                "status": "ALREADY_COMPLETED",
                "session_date": "2026-07-22",
                "observations_published": 6,
            },
            completed_health,
            operator_report(),
        ]
    )

    def fake_run(command):
        commands.append(command)
        return next(responses)

    monkeypatch.setattr(
        daily,
        "run_json_command",
        fake_run,
    )
    monkeypatch.setattr(
        daily,
        "observation_reconciliation_pending",
        lambda _session_date: True,
    )

    result = daily.run_daily_operation(
        report_only=False,
        use_oanda_practice=True,
        session_date="2026-07-22",
        candle_count=100,
    )

    assert len(commands) == 4
    assert result["session_already_completed"] is True
    assert result["session_executed"] is False
    assert result[
        "observation_reconciliation_executed"
    ] is True
    assert result["session_result"][
        "observations_published"
    ] == 6


def test_operator_must_explicitly_prohibit_live_trading():
    report = operator_report()
    report["safe_for_live_trading"] = True

    with pytest.raises(
        daily.DailyOperationError,
        match="prohibit live trading",
    ):
        daily.require_safe_operator_state(
            report,
        )


def test_run_json_command_rejects_failed_command(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["broken"],
            returncode=1,
            stdout="",
            stderr="failure",
        ),
    )

    with pytest.raises(
        daily.DailyOperationError,
        match="failure",
    ):
        daily.run_json_command(
            ["broken"],
        )


def test_run_json_command_rejects_invalid_json(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["invalid"],
            returncode=0,
            stdout="not-json",
            stderr="",
        ),
    )

    with pytest.raises(
        daily.DailyOperationError,
        match="valid JSON",
    ):
        daily.run_json_command(
            ["invalid"],
        )


def test_duplicate_session_date_skips_session_command(
    monkeypatch,
):
    commands = []

    preflight = healthy_report()
    preflight["last_completed_session_date"] = "2026-07-18"

    responses = iter(
        [
            preflight,
            healthy_report(),
            operator_report(),
        ]
    )

    def fake_run(command):
        commands.append(command)
        return next(responses)

    monkeypatch.setattr(
        daily,
        "run_json_command",
        fake_run,
    )

    result = daily.run_daily_operation(
        report_only=False,
        use_oanda_practice=True,
        session_date="2026-07-18",
        candle_count=500,
    )

    assert len(commands) == 3
    assert result["daily_operation_status"] == "ALREADY_COMPLETED"
    assert result["target_session_date"] == "2026-07-18"
    assert result["session_already_completed"] is True
    assert result["session_executed"] is False
    assert result["session_result"] is None

    assert all(str(daily.SESSION_SCRIPT) not in command for command in commands)


def test_new_session_date_runs_session_command(
    monkeypatch,
):
    commands = []

    preflight = healthy_report()
    preflight["last_completed_session_date"] = "2026-07-17"

    responses = iter(
        [
            preflight,
            {
                "status": "COMPLETED",
                "session_date": "2026-07-18",
            },
            healthy_report(),
            operator_report(),
        ]
    )

    def fake_run(command):
        commands.append(command)
        return next(responses)

    monkeypatch.setattr(
        daily,
        "run_json_command",
        fake_run,
    )

    result = daily.run_daily_operation(
        report_only=False,
        use_oanda_practice=True,
        session_date="2026-07-18",
        candle_count=500,
    )

    assert len(commands) == 4
    assert result["daily_operation_status"] == "COMPLETED"
    assert result["session_already_completed"] is False
    assert result["session_executed"] is True

    assert str(daily.SESSION_SCRIPT) in commands[1]


def test_operation_lock_rejects_overlapping_operation(
    tmp_path,
):
    lock_path = tmp_path / "daily-operation.lock"

    with daily.operation_lock(lock_path):
        assert lock_path.exists()

        with pytest.raises(
            daily.DailyOperationError,
            match="already running",
        ):
            with daily.operation_lock(lock_path):
                pass

    assert not lock_path.exists()


def test_operation_lock_is_removed_after_failure(
    tmp_path,
):
    lock_path = tmp_path / "daily-operation.lock"

    with pytest.raises(
        RuntimeError,
        match="simulated failure",
    ):
        with daily.operation_lock(lock_path):
            raise RuntimeError("simulated failure")

    assert not lock_path.exists()


def test_invalid_daily_session_date_is_rejected():
    with pytest.raises(
        daily.DailyOperationError,
        match="YYYY-MM-DD",
    ):
        daily.resolve_target_session_date(
            "18-07-2026",
        )


def test_lock_contains_structured_metadata(
    tmp_path,
):
    lock_path = tmp_path / "daily-operation.lock"

    with daily.operation_lock(
        lock_path,
        operation_mode="PROSPECTIVE_PAPER_SESSION",
        session_date="2026-07-18",
    ) as metadata:
        stored = daily.json.loads(lock_path.read_text())

        assert stored == metadata
        assert stored["schema_version"] == 1
        assert stored["pid"] == daily.os.getpid()
        assert stored["hostname"] == daily.socket.gethostname()
        assert stored["operation_mode"] == ("PROSPECTIVE_PAPER_SESSION")
        assert stored["session_date"] == "2026-07-18"
        assert stored["ownership_token"]
        assert stored["created_at_utc"]

    assert not lock_path.exists()


def test_stale_operation_lock_is_recovered(
    tmp_path,
    monkeypatch,
):
    lock_path = tmp_path / "daily-operation.lock"

    stale_metadata = daily.build_lock_metadata(
        operation_mode="REPORT_ONLY",
        session_date=None,
    )
    stale_metadata["pid"] = 12345

    lock_path.write_text(daily.json.dumps(stale_metadata))

    monkeypatch.setattr(
        daily,
        "process_is_running",
        lambda pid: False,
    )

    with daily.operation_lock(lock_path) as current_metadata:
        assert lock_path.exists()
        assert current_metadata["pid"] == daily.os.getpid()
        assert current_metadata["ownership_token"] != stale_metadata["ownership_token"]

    assert not lock_path.exists()


def test_active_external_lock_is_not_removed(
    tmp_path,
    monkeypatch,
):
    lock_path = tmp_path / "daily-operation.lock"

    existing_metadata = daily.build_lock_metadata(
        operation_mode="REPORT_ONLY",
        session_date=None,
    )
    existing_metadata["pid"] = 12345

    lock_path.write_text(daily.json.dumps(existing_metadata))

    monkeypatch.setattr(
        daily,
        "process_is_running",
        lambda pid: True,
    )

    with pytest.raises(
        daily.DailyOperationError,
        match="already running",
    ):
        with daily.operation_lock(lock_path):
            pass

    assert lock_path.exists()

    stored = daily.json.loads(lock_path.read_text())
    assert stored == existing_metadata


def test_foreign_host_lock_requires_manual_review(
    tmp_path,
):
    lock_path = tmp_path / "daily-operation.lock"

    existing_metadata = daily.build_lock_metadata(
        operation_mode="REPORT_ONLY",
        session_date=None,
    )
    existing_metadata["hostname"] = "another-host.example"

    lock_path.write_text(daily.json.dumps(existing_metadata))

    with pytest.raises(
        daily.DailyOperationError,
        match="another host",
    ):
        with daily.operation_lock(lock_path):
            pass

    assert lock_path.exists()


def test_malformed_lock_requires_manual_review(
    tmp_path,
):
    lock_path = tmp_path / "daily-operation.lock"
    lock_path.write_text("not-json\n")

    with pytest.raises(
        daily.DailyOperationError,
        match="malformed",
    ):
        with daily.operation_lock(lock_path):
            pass

    assert lock_path.exists()


def test_legacy_pid_only_lock_requires_manual_review(
    tmp_path,
):
    lock_path = tmp_path / "daily-operation.lock"
    lock_path.write_text("12345\n")

    with pytest.raises(
        daily.DailyOperationError,
        match="not a JSON object",
    ):
        with daily.operation_lock(lock_path):
            pass

    assert lock_path.exists()


def test_operation_cleanup_preserves_replacement_lock(
    tmp_path,
):
    lock_path = tmp_path / "daily-operation.lock"

    replacement_metadata = daily.build_lock_metadata(
        operation_mode="REPORT_ONLY",
        session_date=None,
    )

    with daily.operation_lock(lock_path):
        lock_path.write_text(daily.json.dumps(replacement_metadata))

    assert lock_path.exists()

    stored = daily.json.loads(lock_path.read_text())
    assert stored == replacement_metadata


def test_report_only_operation_does_not_write_receipt(
    monkeypatch,
):
    def unexpected_write(*args, **kwargs):
        raise AssertionError("Receipt writer should not run.")

    monkeypatch.setattr(
        daily,
        "write_session_receipt",
        unexpected_write,
    )

    assert (
        daily.write_completed_session_receipt(
            {
                "session_executed": False,
            }
        )
        is None
    )


def test_completed_session_writes_receipt(
    tmp_path,
    monkeypatch,
):
    expected_path = tmp_path / "2026-07-18.json"
    captured = {}

    def fake_write(receipt_directory, **kwargs):
        captured["directory"] = receipt_directory
        captured["kwargs"] = kwargs
        return expected_path

    monkeypatch.setattr(
        daily,
        "write_session_receipt",
        fake_write,
    )

    result = daily.write_completed_session_receipt(
        {
            "session_executed": True,
            "target_session_date": "2026-07-18",
            "session_result": {
                "software_commit": "50cad94",
                "policy_fingerprint": "policy-fingerprint",
            },
            "postflight_health": "HEALTHY",
            "operator_status": "OBSERVING",
            "evidence_gate_status": "NOT_READY",
            "candidate_balance": 10000.0,
            "shadow_balance": 10000.0,
            "completed_sessions": 2,
            "broker_orders_sent": 0,
        },
        receipt_directory=tmp_path,
    )

    assert result == expected_path
    assert captured["directory"] == tmp_path
    assert captured["kwargs"]["session_date"] == "2026-07-18"
    assert captured["kwargs"]["broker_orders_sent"] == 0


def test_receipt_failure_fails_daily_operation(
    tmp_path,
    monkeypatch,
):
    def failed_write(*args, **kwargs):
        raise daily.SessionReceiptError("simulated failure")

    monkeypatch.setattr(
        daily,
        "write_session_receipt",
        failed_write,
    )

    with pytest.raises(
        daily.DailyOperationError,
        match="could not be created safely",
    ):
        daily.write_completed_session_receipt(
            {
                "session_executed": True,
                "target_session_date": "2026-07-18",
                "session_result": {
                    "software_commit": "50cad94",
                    "policy_fingerprint": "policy-fingerprint",
                },
                "postflight_health": "HEALTHY",
                "operator_status": "OBSERVING",
                "evidence_gate_status": "NOT_READY",
                "candidate_balance": 10000.0,
                "shadow_balance": 10000.0,
                "completed_sessions": 2,
                "broker_orders_sent": 0,
            },
            receipt_directory=tmp_path,
        )


def test_main_appends_one_report_only_journal_record(
    monkeypatch,
    tmp_path,
):
    from contextlib import nullcontext

    journal_path = tmp_path / "daily_operations.jsonl"

    monkeypatch.setattr(
        daily,
        "DAILY_OPERATION_JOURNAL_PATH",
        journal_path,
    )
    monkeypatch.setattr(
        daily,
        "operation_lock",
        lambda **kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        daily,
        "run_daily_operation",
        lambda **kwargs: {
            "daily_operation_status": "COMPLETED",
            "operation_mode": "REPORT_ONLY",
            "target_session_date": None,
            "session_already_completed": False,
            "session_executed": False,
            "session_result": None,
            "preflight_health": "HEALTHY",
            "postflight_health": "HEALTHY",
            "operator_status": "OBSERVING",
            "evidence_gate_status": "NOT_READY",
            "completed_sessions": 1,
            "positions_closed": 0,
            "candidate_balance": 10000.0,
            "shadow_balance": 10000.0,
            "safe_to_continue_paper_observation": True,
            "safe_for_live_trading": False,
            "protocol_live_trading_permitted": False,
            "live_trading_decision": "PROHIBITED_BY_DAILY_OPERATION",
            "broker_orders_sent": 0,
        },
    )
    monkeypatch.setattr(
        daily,
        "write_completed_session_receipt",
        lambda report: None,
    )
    monkeypatch.setattr(
        daily,
        "resolve_git_commit",
        lambda: "test-commit",
    )

    assert daily.main(["--report-only"]) == 0

    records = daily.json.loads(journal_path.read_text().strip())

    assert records["status"] == "REPORT_ONLY"
    assert records["session_executed"] is False


def test_main_appends_failed_journal_record(
    monkeypatch,
    tmp_path,
):
    from contextlib import nullcontext

    journal_path = tmp_path / "daily_operations.jsonl"

    monkeypatch.setattr(
        daily,
        "DAILY_OPERATION_JOURNAL_PATH",
        journal_path,
    )
    monkeypatch.setattr(
        daily,
        "operation_lock",
        lambda **kwargs: nullcontext(),
    )

    def fail_operation(**kwargs):
        raise daily.DailyOperationError("simulated failure")

    monkeypatch.setattr(
        daily,
        "run_daily_operation",
        fail_operation,
    )
    monkeypatch.setattr(
        daily,
        "resolve_git_commit",
        lambda: "test-commit",
    )

    assert daily.main(["--report-only"]) == 1

    record = daily.json.loads(journal_path.read_text().strip())

    assert record["status"] == "FAILED"
    assert record["failure_type"] == "DailyOperationError"
    assert record["failure_message"] == "simulated failure"


def test_main_fails_when_journal_append_fails(
    monkeypatch,
):
    from contextlib import nullcontext

    monkeypatch.setattr(
        daily,
        "operation_lock",
        lambda **kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        daily,
        "run_daily_operation",
        lambda **kwargs: {
            "daily_operation_status": "COMPLETED",
            "operation_mode": "REPORT_ONLY",
            "target_session_date": None,
            "session_already_completed": False,
            "session_executed": False,
            "session_result": None,
            "preflight_health": "HEALTHY",
            "postflight_health": "HEALTHY",
            "operator_status": "OBSERVING",
            "evidence_gate_status": "NOT_READY",
            "completed_sessions": 1,
            "positions_closed": 0,
            "candidate_balance": 10000.0,
            "shadow_balance": 10000.0,
            "safe_to_continue_paper_observation": True,
            "safe_for_live_trading": False,
            "protocol_live_trading_permitted": False,
            "live_trading_decision": "PROHIBITED_BY_DAILY_OPERATION",
            "broker_orders_sent": 0,
        },
    )
    monkeypatch.setattr(
        daily,
        "write_completed_session_receipt",
        lambda report: None,
    )
    monkeypatch.setattr(
        daily,
        "resolve_git_commit",
        lambda: "test-commit",
    )

    def fail_append(*args, **kwargs):
        raise daily.DailyOperationJournalError("simulated journal failure")

    monkeypatch.setattr(
        daily,
        "append_daily_operation_record",
        fail_append,
    )

    assert daily.main(["--report-only"]) == 1
