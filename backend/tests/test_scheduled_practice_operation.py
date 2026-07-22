import json
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scripts import run_scheduled_practice_operation as scheduled

LONDON = ZoneInfo("Europe/London")
ENVIRONMENT = {
    "OANDA_API_TOKEN": "test-token",
    "OANDA_ACCOUNT_ID": "999-001-12345678-001",
    "OANDA_ENVIRONMENT": "practice",
}


def test_weekday_schedule_runs_guarded_practice_operation(tmp_path):
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "daily_operation_status": "COMPLETED",
                    "broker_orders_sent": 0,
                    "safe_for_live_trading": False,
                }
            ),
            stderr="",
        )

    result = scheduled.run_scheduled_operation(
        now_local=datetime(2026, 7, 22, 22, 20, tzinfo=LONDON),
        runner=runner,
        environment=ENVIRONMENT,
        env_path=tmp_path / "missing.env",
    )

    assert result["status"] == "SCHEDULED_PRACTICE_OPERATION_COMPLETE"
    assert result["broker_orders_sent"] == 0
    assert "--use-oanda-practice" in captured["command"]
    assert captured["command"][-3:] == ["2026-07-22", "--candle-count", "100"]
    assert captured["env"]["OANDA_ENVIRONMENT"] == "practice"


def test_schedule_skips_weekends_without_loading_credentials(tmp_path):
    result = scheduled.run_scheduled_operation(
        now_local=datetime(2026, 7, 25, 22, 20, tzinfo=LONDON),
        environment={},
        env_path=tmp_path / "missing.env",
    )
    assert result["status"] == "SKIPPED_MARKET_WEEKEND"
    assert result["broker_orders_sent"] == 0


def test_schedule_refuses_early_or_live_environment(tmp_path):
    with pytest.raises(scheduled.ScheduledPracticeError, match="before 22:20"):
        scheduled.run_scheduled_operation(
            now_local=datetime(2026, 7, 22, 22, 19, tzinfo=LONDON),
            environment=ENVIRONMENT,
            env_path=tmp_path / "missing.env",
        )

    with pytest.raises(scheduled.ScheduledPracticeError, match="exactly 'practice'"):
        scheduled.run_scheduled_operation(
            now_local=datetime(2026, 7, 22, 22, 20, tzinfo=LONDON),
            environment={**ENVIRONMENT, "OANDA_ENVIRONMENT": "live"},
            env_path=tmp_path / "missing.env",
        )


def test_schedule_fails_closed_on_broker_activity(tmp_path):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "broker_orders_sent": 1,
                    "safe_for_live_trading": False,
                }
            ),
            stderr="",
        )

    with pytest.raises(scheduled.ScheduledPracticeError, match="broker-order activity"):
        scheduled.run_scheduled_operation(
            now_local=datetime(2026, 7, 22, 22, 20, tzinfo=LONDON),
            runner=runner,
            environment=ENVIRONMENT,
            env_path=tmp_path / "missing.env",
        )
