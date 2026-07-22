"""Scheduler-safe weekday launcher for the guarded OANDA Practice operation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DAILY_OPERATION = PROJECT_ROOT / "scripts" / "run_prospective_paper_daily_operation.py"
ENV_PATH = PROJECT_ROOT / ".env"
LOCAL_ZONE = ZoneInfo("Europe/London")
EARLIEST_RUN_TIME = time(22, 20)
ALLOWED_ENVIRONMENT_KEYS = {
    "OANDA_API_TOKEN",
    "OANDA_ACCOUNT_ID",
    "OANDA_ENVIRONMENT",
}


class ScheduledPracticeError(RuntimeError):
    """Raised when a scheduled operation cannot proceed safely."""


def load_local_practice_environment(
    path: Path = ENV_PATH,
    *,
    environment: dict[str, str] | None = None,
) -> dict[str, str]:
    """Load only the three OANDA settings without executing shell content."""
    values = dict(os.environ if environment is None else environment)
    if path.exists():
        for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line.removeprefix("export ").strip()
            if "=" not in line:
                raise ScheduledPracticeError(f"Invalid .env assignment at line {line_number}.")
            key, raw_value = line.split("=", 1)
            key = key.strip()
            if key not in ALLOWED_ENVIRONMENT_KEYS:
                continue
            value = raw_value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            values.setdefault(key, value)
    missing = sorted(key for key in ALLOWED_ENVIRONMENT_KEYS if not values.get(key))
    if missing:
        raise ScheduledPracticeError(
            "Missing required local practice settings: " + ", ".join(missing)
        )
    if values["OANDA_ENVIRONMENT"] != "practice":
        raise ScheduledPracticeError("OANDA_ENVIRONMENT must be exactly 'practice'.")
    return values


Runner = Callable[..., subprocess.CompletedProcess[str]]


def run_scheduled_operation(
    *,
    now_local: datetime | None = None,
    runner: Runner = subprocess.run,
    environment: dict[str, str] | None = None,
    env_path: Path = ENV_PATH,
) -> dict[str, object]:
    resolved_now = now_local or datetime.now(LOCAL_ZONE)
    if resolved_now.tzinfo is None:
        raise ScheduledPracticeError("Scheduled operation time must be timezone-aware.")
    local_now = resolved_now.astimezone(LOCAL_ZONE)
    if local_now.weekday() >= 5:
        return {
            "status": "SKIPPED_MARKET_WEEKEND",
            "session_date": local_now.date().isoformat(),
            "broker_orders_sent": 0,
            "live_trading_allowed": False,
        }
    if local_now.time().replace(tzinfo=None) < EARLIEST_RUN_TIME:
        raise ScheduledPracticeError("Scheduled operation refused before 22:20 Europe/London.")
    values = load_local_practice_environment(path=env_path, environment=environment)
    command = [
        sys.executable,
        str(DAILY_OPERATION),
        "--use-oanda-practice",
        "--session-date",
        local_now.date().isoformat(),
        "--candle-count",
        "100",
    ]
    completed = runner(
        command,
        cwd=PROJECT_ROOT,
        env=values,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        message = " ".join((completed.stderr or completed.stdout).split())[:1000]
        raise ScheduledPracticeError(f"Guarded daily operation failed: {message}")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ScheduledPracticeError("Guarded daily operation returned invalid JSON.") from error
    if not isinstance(report, dict):
        raise ScheduledPracticeError("Guarded daily operation returned a non-object result.")
    if report.get("broker_orders_sent") != 0:
        raise ScheduledPracticeError("Scheduled operation detected broker-order activity.")
    if report.get("safe_for_live_trading") is not False:
        raise ScheduledPracticeError("Scheduled operation did not prohibit live trading.")
    return {
        "status": "SCHEDULED_PRACTICE_OPERATION_COMPLETE",
        "session_date": local_now.date().isoformat(),
        "daily_operation": report,
        "broker_orders_sent": 0,
        "live_trading_allowed": False,
    }


def main() -> int:
    try:
        result = run_scheduled_operation()
    except (OSError, ScheduledPracticeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
