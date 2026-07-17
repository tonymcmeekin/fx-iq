"""Run one controlled prospective paper-trading daily operation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

SESSION_SCRIPT = SCRIPTS_DIR / "run_prospective_paper_session.py"
HEALTH_SCRIPT = SCRIPTS_DIR / "check_prospective_paper_health.py"
OPERATOR_SCRIPT = SCRIPTS_DIR / "report_prospective_paper_operator_status.py"
LOCK_PATH = PROJECT_ROOT / "paper_ledger" / "daily_operation.lock"


class DailyOperationError(RuntimeError):
    """Raised when a daily operation safety or execution check fails."""


def resolve_target_session_date(
    value: str | None,
) -> str:
    if value is None:
        return datetime.now(UTC).date().isoformat()

    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise DailyOperationError("Session date must use YYYY-MM-DD format.") from error


@contextmanager
def operation_lock(
    lock_path: Path = LOCK_PATH,
) -> Iterator[None]:
    lock_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
    except FileExistsError as error:
        raise DailyOperationError(
            "Another prospective paper daily operation is already running."
        ) from error

    try:
        os.write(
            descriptor,
            f"{os.getpid()}\n".encode(),
        )
        os.close(descriptor)
        descriptor = -1

        yield
    finally:
        if descriptor != -1:
            os.close(descriptor)

        lock_path.unlink(
            missing_ok=True,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a controlled simulation-only prospective paper "
            "operation and produce one combined operator summary."
        ),
    )

    parser.add_argument(
        "--use-oanda-practice",
        action="store_true",
        help=("Explicitly permit OANDA practice candle-data collection for the paper session."),
    )

    parser.add_argument(
        "--report-only",
        action="store_true",
        help=("Skip the paper session and run only the health and operator reports."),
    )

    parser.add_argument(
        "--session-date",
        help=("Session date in YYYY-MM-DD format. Passed through to the prospective paper runner."),
    )

    parser.add_argument(
        "--candle-count",
        type=int,
        help=(
            "Complete daily candles requested per market. Passed "
            "through to the prospective paper runner."
        ),
    )

    return parser


def run_json_command(
    command: Sequence[str],
) -> dict[str, Any]:
    completed = subprocess.run(
        list(command),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()

        raise DailyOperationError(
            f"Command failed with exit code {completed.returncode}: {' '.join(command)}\n{message}"
        )

    output = completed.stdout.strip()

    try:
        result = json.loads(output)
    except json.JSONDecodeError as error:
        raise DailyOperationError(
            f"Command did not return valid JSON: {' '.join(command)}"
        ) from error

    if not isinstance(result, dict):
        raise DailyOperationError(f"Command returned a non-object JSON value: {' '.join(command)}")

    return result


def build_session_command(
    *,
    use_oanda_practice: bool,
    session_date: str | None,
    candle_count: int | None,
) -> list[str]:
    command = [
        sys.executable,
        str(SESSION_SCRIPT),
    ]

    if use_oanda_practice:
        command.append("--use-oanda-practice")

    if session_date is not None:
        command.extend(
            [
                "--session-date",
                session_date,
            ]
        )

    if candle_count is not None:
        command.extend(
            [
                "--candle-count",
                str(candle_count),
            ]
        )

    return command


def require_healthy(
    report: dict[str, Any],
    *,
    stage: str,
) -> None:
    if report.get("status") != "HEALTHY":
        raise DailyOperationError(
            f"Runtime health check failed during {stage}: {report.get('status')!r}"
        )

    if report.get("broker_orders_sent") != 0:
        raise DailyOperationError(f"Broker-order safety violation during {stage}.")


def require_safe_operator_state(
    report: dict[str, Any],
) -> None:
    if report.get("safe_for_live_trading") is not False:
        raise DailyOperationError("Operator report did not explicitly prohibit live trading.")

    if report.get("protocol_live_trading_permitted") is not False:
        raise DailyOperationError("Protocol report did not explicitly prohibit live trading.")

    if report.get("broker_orders_sent") != 0:
        raise DailyOperationError("Operator report indicates broker orders were sent.")

    if report.get("runtime_health") != "HEALTHY":
        raise DailyOperationError("Final operator report is not runtime healthy.")


def run_daily_operation(
    *,
    report_only: bool,
    use_oanda_practice: bool,
    session_date: str | None,
    candle_count: int | None,
) -> dict[str, Any]:
    if report_only and use_oanda_practice:
        raise DailyOperationError("--report-only cannot be combined with --use-oanda-practice.")

    if not report_only and not use_oanda_practice:
        raise DailyOperationError(
            "A paper session requires explicit "
            "--use-oanda-practice permission. Use --report-only "
            "for a read-only operation."
        )

    health_command = [
        sys.executable,
        str(HEALTH_SCRIPT),
    ]

    operator_command = [
        sys.executable,
        str(OPERATOR_SCRIPT),
    ]

    target_session_date = (
        None
        if report_only
        else resolve_target_session_date(
            session_date,
        )
    )

    preflight_health = run_json_command(
        health_command,
    )
    require_healthy(
        preflight_health,
        stage="preflight",
    )

    session_already_completed = (
        target_session_date is not None
        and preflight_health.get("last_completed_session_date") == target_session_date
    )

    session_result: dict[str, Any] | None = None

    if not report_only and not session_already_completed:
        session_result = run_json_command(
            build_session_command(
                use_oanda_practice=use_oanda_practice,
                session_date=target_session_date,
                candle_count=candle_count,
            )
        )

    postflight_health = run_json_command(
        health_command,
    )
    require_healthy(
        postflight_health,
        stage="postflight",
    )

    operator_report = run_json_command(
        operator_command,
    )
    require_safe_operator_state(
        operator_report,
    )

    return {
        "daily_operation_status": (
            "ALREADY_COMPLETED" if session_already_completed else "COMPLETED"
        ),
        "operation_mode": ("REPORT_ONLY" if report_only else "PROSPECTIVE_PAPER_SESSION"),
        "target_session_date": target_session_date,
        "session_already_completed": session_already_completed,
        "session_executed": (not report_only and not session_already_completed),
        "session_result": session_result,
        "preflight_health": preflight_health.get("status"),
        "postflight_health": postflight_health.get("status"),
        "operator_status": operator_report.get("status"),
        "evidence_gate_status": operator_report.get("evidence_gate_status"),
        "completed_sessions": operator_report.get("completed_sessions"),
        "positions_closed": operator_report.get("positions_closed"),
        "candidate_balance": operator_report.get("candidate_balance"),
        "shadow_balance": operator_report.get("shadow_balance"),
        "safe_to_continue_paper_observation": operator_report.get(
            "safe_to_continue_paper_observation"
        ),
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
        "live_trading_decision": "PROHIBITED_BY_DAILY_OPERATION",
        "broker_orders_sent": operator_report.get("broker_orders_sent"),
    }


def main(
    argv: Sequence[str] | None = None,
) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    try:
        with operation_lock():
            report = run_daily_operation(
                report_only=arguments.report_only,
                use_oanda_practice=arguments.use_oanda_practice,
                session_date=arguments.session_date,
                candle_count=arguments.candle_count,
            )
    except DailyOperationError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
