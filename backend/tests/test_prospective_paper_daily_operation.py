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
