"""Run one controlled prospective paper-trading daily operation."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )

from app.intelligence.outcome_store import read_outcomes  # noqa: E402
from app.paper_trading.daily_operation_journal import (  # noqa: E402
    DailyOperationJournalError,
    append_daily_operation_record,
    build_daily_operation_record,
)
from app.paper_trading.ledger import verify_ledger  # noqa: E402
from app.paper_trading.orchestrator import (  # noqa: E402
    observation_staging_path,
)
from app.paper_trading.session_receipts import (  # noqa: E402
    SessionReceiptError,
    write_session_receipt,
)

SCRIPTS_DIR = PROJECT_ROOT / "scripts"

SESSION_SCRIPT = SCRIPTS_DIR / "run_prospective_paper_session.py"
HEALTH_SCRIPT = SCRIPTS_DIR / "check_prospective_paper_health.py"
OPERATOR_SCRIPT = SCRIPTS_DIR / "report_prospective_paper_operator_status.py"
RECOVERY_SCRIPT = SCRIPTS_DIR / "recover_incomplete_paper_session.py"
LOCK_PATH = PROJECT_ROOT / "paper_ledger" / "daily_operation.lock"
RECEIPT_DIRECTORY = PROJECT_ROOT / "paper_ledger" / "receipts"
DAILY_OPERATION_JOURNAL_PATH = PROJECT_ROOT / "paper_ledger" / "daily_operations.jsonl"
OBSERVATION_STORE_PATH = (
    PROJECT_ROOT / "paper_ledger" / "intelligence_observations.jsonl"
)
OUTCOME_STORE_PATH = (
    PROJECT_ROOT / "paper_ledger" / "intelligence_outcomes.jsonl"
)


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


def build_lock_metadata(
    *,
    operation_mode: str,
    session_date: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "operation_mode": operation_mode,
        "session_date": session_date,
        "ownership_token": uuid.uuid4().hex,
    }


def read_lock_metadata(
    lock_path: Path,
) -> dict[str, Any]:
    try:
        raw_value = lock_path.read_text()
    except FileNotFoundError:
        raise
    except OSError as error:
        raise DailyOperationError(
            "The prospective paper operation lock could not be read."
        ) from error

    try:
        metadata = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise DailyOperationError(
            "The prospective paper operation lock is malformed and requires manual review."
        ) from error

    if not isinstance(metadata, dict):
        raise DailyOperationError(
            "The prospective paper operation lock is not a JSON object and requires manual review."
        )

    if metadata.get("schema_version") != 1:
        raise DailyOperationError(
            "The prospective paper operation lock uses an "
            "unsupported schema and requires manual review."
        )

    pid = metadata.get("pid")

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise DailyOperationError(
            "The prospective paper operation lock contains an "
            "invalid process identifier and requires manual review."
        )

    hostname = metadata.get("hostname")

    if not isinstance(hostname, str) or not hostname.strip():
        raise DailyOperationError(
            "The prospective paper operation lock contains an "
            "invalid hostname and requires manual review."
        )

    ownership_token = metadata.get("ownership_token")

    if not isinstance(ownership_token, str) or not ownership_token:
        raise DailyOperationError(
            "The prospective paper operation lock contains an "
            "invalid ownership token and requires manual review."
        )

    created_at_utc = metadata.get("created_at_utc")

    if not isinstance(created_at_utc, str):
        raise DailyOperationError(
            "The prospective paper operation lock contains an "
            "invalid creation time and requires manual review."
        )

    try:
        created_at = datetime.fromisoformat(created_at_utc)
    except ValueError as error:
        raise DailyOperationError(
            "The prospective paper operation lock contains an "
            "invalid creation time and requires manual review."
        ) from error

    if created_at.tzinfo is None:
        raise DailyOperationError(
            "The prospective paper operation lock creation time must be timezone-aware."
        )

    operation_mode = metadata.get("operation_mode")

    if operation_mode not in {
        "REPORT_ONLY",
        "PROSPECTIVE_PAPER_SESSION",
    }:
        raise DailyOperationError(
            "The prospective paper operation lock contains an "
            "invalid operation mode and requires manual review."
        )

    session_date = metadata.get("session_date")

    if session_date is not None and not isinstance(
        session_date,
        str,
    ):
        raise DailyOperationError(
            "The prospective paper operation lock contains an "
            "invalid session date and requires manual review."
        )

    return metadata


def process_is_running(
    pid: int,
) -> bool:
    try:
        os.kill(
            pid,
            0,
        )
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

    return True


def remove_owned_lock(
    lock_path: Path,
    *,
    ownership_token: str,
) -> None:
    try:
        current_metadata = read_lock_metadata(
            lock_path,
        )
    except DailyOperationError, FileNotFoundError:
        return

    if current_metadata["ownership_token"] == ownership_token:
        lock_path.unlink(
            missing_ok=True,
        )


@contextmanager
def operation_lock(
    lock_path: Path = LOCK_PATH,
    *,
    operation_mode: str = "REPORT_ONLY",
    session_date: str | None = None,
) -> Iterator[dict[str, Any]]:
    lock_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    metadata = build_lock_metadata(
        operation_mode=operation_mode,
        session_date=session_date,
    )
    ownership_token = metadata["ownership_token"]
    encoded_metadata = (
        json.dumps(
            metadata,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()

    descriptor = -1
    acquired = False

    for _attempt in range(3):
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as error:
            try:
                existing_metadata = read_lock_metadata(
                    lock_path,
                )
            except FileNotFoundError:
                continue

            existing_hostname = existing_metadata["hostname"]
            local_hostname = socket.gethostname()

            if existing_hostname != local_hostname:
                raise DailyOperationError(
                    "A prospective paper operation lock exists "
                    f"for another host: {existing_hostname!r}. "
                    "Manual review is required."
                ) from error

            existing_pid = existing_metadata["pid"]

            if process_is_running(existing_pid):
                raise DailyOperationError(
                    "Another prospective paper daily operation is "
                    f"already running with process ID {existing_pid}."
                ) from error

            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

            continue

        try:
            os.write(
                descriptor,
                encoded_metadata,
            )
        finally:
            os.close(descriptor)
            descriptor = -1

        acquired = True
        break

    if not acquired:
        raise DailyOperationError(
            "The stale prospective paper operation lock could not be safely recovered."
        )

    try:
        yield metadata
    finally:
        if descriptor != -1:
            os.close(descriptor)

        remove_owned_lock(
            lock_path,
            ownership_token=ownership_token,
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
        help=(
            "Skip the paper session, run only the health and "
            "operator reports, and append one audit-journal record."
        ),
    )

    parser.add_argument(
        "--recover-incomplete-session",
        action="store_true",
        help=(
            "If preflight health is degraded by the requested "
            "incomplete session, apply the guarded backed-up "
            "recovery before retrying."
        ),
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

    if report.get("observation_integrity_status") != "HEALTHY":
        raise DailyOperationError(
            "Final passive-observation integrity is not healthy."
        )


def observation_reconciliation_pending(
    session_date: str,
) -> bool:
    return observation_staging_path(
        OBSERVATION_STORE_PATH,
        date.fromisoformat(session_date),
    ).exists()


def outcome_reconciliation_pending() -> bool:
    close_event_ids = {
        event["event_id"]
        for event in verify_ledger(
            PROJECT_ROOT / "paper_ledger" / "events.jsonl"
        )
        if event["event_type"] == "PAPER_POSITION_CLOSED"
    }
    outcome_close_ids = {
        outcome.close_event_id
        for outcome in read_outcomes(
            OUTCOME_STORE_PATH
        )
    }
    return bool(
        close_event_ids - outcome_close_ids
    )


def run_daily_operation(
    *,
    report_only: bool,
    use_oanda_practice: bool,
    session_date: str | None,
    candle_count: int | None,
    recover_incomplete_session: bool = False,
) -> dict[str, Any]:
    if report_only and use_oanda_practice:
        raise DailyOperationError("--report-only cannot be combined with --use-oanda-practice.")

    if not report_only and not use_oanda_practice:
        raise DailyOperationError(
            "A paper session requires explicit "
            "--use-oanda-practice permission. Use --report-only "
            "for a non-trading audited operation."
        )

    if report_only and recover_incomplete_session:
        raise DailyOperationError(
            "--recover-incomplete-session cannot be "
            "combined with --report-only."
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

    recovery_result: dict[str, Any] | None = None

    if (
        preflight_health.get("status") != "HEALTHY"
        and recover_incomplete_session
    ):
        if target_session_date is None:
            raise DailyOperationError(
                "Recovery requires an explicit target session date."
            )

        recovery_result = run_json_command(
            [
                sys.executable,
                str(RECOVERY_SCRIPT),
                "--session-date",
                target_session_date,
                "--apply",
            ]
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
    reconcile_observations = (
        target_session_date is not None
        and session_already_completed
        and observation_reconciliation_pending(
            target_session_date
        )
    )
    reconcile_outcomes = (
        target_session_date is not None
        and session_already_completed
        and outcome_reconciliation_pending()
    )

    session_result: dict[str, Any] | None = None

    if not report_only and (
        not session_already_completed
        or reconcile_observations
        or reconcile_outcomes
    ):
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
        "observation_reconciliation_executed": (
            reconcile_observations
        ),
        "outcome_reconciliation_executed": (
            reconcile_outcomes
        ),
        "preflight_health": preflight_health.get("status"),
        "postflight_health": postflight_health.get("status"),
        "operator_status": operator_report.get("status"),
        "observation_integrity_status": operator_report.get(
            "observation_integrity_status"
        ),
        "observations_recorded": operator_report.get(
            "observations_recorded"
        ),
        "observation_outcomes_populated": operator_report.get(
            "observation_outcomes_populated"
        ),
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
        "incomplete_session_recovery": recovery_result,
    }


def write_completed_session_receipt(
    report: dict[str, Any],
    *,
    receipt_directory: Path = RECEIPT_DIRECTORY,
) -> Path | None:
    if report.get("session_executed") is not True:
        return None

    session_result = report.get("session_result")

    if not isinstance(session_result, dict):
        raise DailyOperationError("Executed session did not return a valid session result.")

    try:
        return write_session_receipt(
            receipt_directory,
            session_date=str(report["target_session_date"]),
            software_commit=str(session_result["software_commit"]),
            policy_fingerprint=str(session_result["policy_fingerprint"]),
            runtime_health=str(report["postflight_health"]),
            operator_status=str(report["operator_status"]),
            evidence_gate_status=str(report["evidence_gate_status"]),
            candidate_balance=report["candidate_balance"],
            shadow_balance=report["shadow_balance"],
            completed_sessions=report["completed_sessions"],
            broker_orders_sent=report["broker_orders_sent"],
            created_at_utc=datetime.now(UTC),
        )
    except (KeyError, TypeError, SessionReceiptError) as error:
        raise DailyOperationError(
            "The completed prospective paper session receipt could not be created safely."
        ) from error


def resolve_git_commit() -> str:
    """Return the current software commit without failing an operation."""
    completed = subprocess.run(
        [
            "git",
            "rev-parse",
            "HEAD",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    commit = completed.stdout.strip()

    return commit or "UNKNOWN"


def sanitize_failure_message(
    error: BaseException,
) -> str:
    """Return a bounded single-line failure description."""
    message = " ".join(str(error).split())

    if not message:
        message = type(error).__name__

    return message[:1000]


def resolve_journal_status(
    *,
    report_only: bool,
    report: dict[str, Any],
) -> str:
    """Map a completed invocation to its stable journal status."""
    if report_only:
        return "REPORT_ONLY"

    if report.get("session_already_completed") is True:
        return "ALREADY_COMPLETED"

    return "COMPLETED"


def main(
    argv: Sequence[str] | None = None,
) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    operation_id = uuid.uuid4().hex
    started_at_utc = datetime.now(UTC)
    operation_mode = "REPORT_ONLY" if arguments.report_only else "PROSPECTIVE_PAPER_SESSION"

    report: dict[str, Any] | None = None
    operation_error: BaseException | None = None

    try:
        with operation_lock(
            operation_mode=operation_mode,
            session_date=arguments.session_date,
        ):
            report = run_daily_operation(
                report_only=arguments.report_only,
                use_oanda_practice=arguments.use_oanda_practice,
                session_date=arguments.session_date,
                candle_count=arguments.candle_count,
                recover_incomplete_session=(
                    arguments.recover_incomplete_session
                ),
            )

            receipt_path = write_completed_session_receipt(
                report,
            )

            report["session_receipt_path"] = (
                None
                if receipt_path is None
                else str(
                    receipt_path.relative_to(
                        PROJECT_ROOT,
                    )
                )
            )
    except Exception as error:
        operation_error = error

    completed_at_utc = datetime.now(UTC)

    if report is None:
        journal_status = "FAILED"
        target_session_date = (
            None
            if arguments.report_only
            else (
                arguments.session_date
                if arguments.session_date is not None
                else started_at_utc.date().isoformat()
            )
        )
        session_executed = False
        session_already_completed = False
        session_receipt_path = None
        runtime_health = None
        operator_status = None
        evidence_gate_status = None
        completed_sessions = None
        candidate_balance = None
        shadow_balance = None
        broker_orders_sent = 0
    else:
        journal_status = resolve_journal_status(
            report_only=arguments.report_only,
            report=report,
        )
        target_session_date = report.get("target_session_date")
        session_executed = report.get("session_executed") is True
        session_already_completed = report.get("session_already_completed") is True
        session_receipt_path = report.get("session_receipt_path")
        runtime_health = report.get("postflight_health")
        operator_status = report.get("operator_status")
        evidence_gate_status = report.get("evidence_gate_status")
        completed_sessions = report.get("completed_sessions")
        candidate_balance = report.get("candidate_balance")
        shadow_balance = report.get("shadow_balance")
        broker_orders_sent = report.get(
            "broker_orders_sent",
            0,
        )

    try:
        journal_record = build_daily_operation_record(
            operation_id=operation_id,
            started_at_utc=started_at_utc,
            completed_at_utc=completed_at_utc,
            status=journal_status,
            operation_mode=operation_mode,
            target_session_date=target_session_date,
            session_executed=session_executed,
            session_already_completed=session_already_completed,
            session_receipt_path=session_receipt_path,
            runtime_health=runtime_health,
            operator_status=operator_status,
            evidence_gate_status=evidence_gate_status,
            completed_sessions=completed_sessions,
            candidate_balance=candidate_balance,
            shadow_balance=shadow_balance,
            broker_orders_sent=broker_orders_sent,
            safe_for_live_trading=False,
            protocol_live_trading_permitted=False,
            git_commit=resolve_git_commit(),
            hostname=socket.gethostname(),
            pid=os.getpid(),
            failure_type=(None if operation_error is None else type(operation_error).__name__),
            failure_message=(
                None if operation_error is None else sanitize_failure_message(operation_error)
            ),
        )

        append_daily_operation_record(
            DAILY_OPERATION_JOURNAL_PATH,
            journal_record,
        )
    except DailyOperationJournalError as error:
        print(
            f"ERROR: Daily operation journal failure: {error}",
            file=sys.stderr,
        )
        return 1

    if operation_error is not None:
        print(
            f"ERROR: {operation_error}",
            file=sys.stderr,
        )
        return 1

    if report is None:
        print(
            "ERROR: Daily operation completed without a report.",
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
