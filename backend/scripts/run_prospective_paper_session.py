import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]

if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND_DIRECTORY),
    )

from app.paper_trading.orchestrator import (  # noqa: E402
    run_controlled_daily_session,
)
from app.paper_trading.policy import (  # noqa: E402
    verify_frozen_policy,
)
from app.paper_trading.runtime_state import (  # noqa: E402
    read_runtime_state,
)
from app.safety.broker_preflight import (  # noqa: E402
    build_broker_backed_preflight,
)

PROTOCOL_PATH = BACKEND_DIRECTORY / "research_protocols" / "prospective_paper_trading_protocol.json"

LEDGER_PATH = BACKEND_DIRECTORY / "paper_ledger" / "events.jsonl"

STATE_PATH = BACKEND_DIRECTORY / "paper_ledger" / "state.json"

JOURNAL_PATH = BACKEND_DIRECTORY / "paper_ledger" / "transition.json"

CANDLE_STORE_DIRECTORY = BACKEND_DIRECTORY / "data" / "prospective_paper"

OBSERVATION_STORE_PATH = (
    BACKEND_DIRECTORY
    / "paper_ledger"
    / "intelligence_observations.jsonl"
)

SessionRunner = Callable[..., dict[str, Any]]
PolicyVerifier = Callable[[], str]
CommitReader = Callable[[], tuple[str, bool]]
NowProvider = Callable[[], datetime]


class GuardedRunnerError(RuntimeError):
    """Raised when the guarded practice runner refuses to start."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one simulation-only prospective paper session using OANDA practice candle data."
        )
    )

    parser.add_argument(
        "--use-oanda-practice",
        action="store_true",
        help=("Explicitly permit OANDA practice market-data collection for this invocation."),
    )

    parser.add_argument(
        "--session-date",
        help=("Session date in YYYY-MM-DD format. Defaults to the current UTC date."),
    )

    parser.add_argument(
        "--candle-count",
        type=int,
        default=100,
        help=("Complete daily candles requested per market. Allowed range: 21 to 5000."),
    )

    return parser


def read_git_snapshot() -> tuple[str, bool]:
    commit_process = subprocess.run(
        [
            "git",
            "-C",
            str(BACKEND_DIRECTORY),
            "rev-parse",
            "--short",
            "HEAD",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    commit = commit_process.stdout.strip()

    if not re.fullmatch(
        r"[0-9a-f]{7,40}",
        commit,
    ):
        raise GuardedRunnerError("Current Git commit could not be verified.")

    status_process = subprocess.run(
        [
            "git",
            "-C",
            str(BACKEND_DIRECTORY),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    tracked_files_dirty = bool(status_process.stdout.strip())

    return commit, tracked_files_dirty


def resolve_session_date(
    value: str | None,
    *,
    current_time: datetime,
) -> date:
    if current_time.tzinfo is None:
        raise GuardedRunnerError("Current time must be timezone-aware.")

    if value is None:
        return current_time.astimezone(UTC).date()

    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise GuardedRunnerError("Session date must use YYYY-MM-DD format.") from error


def safe_summary(
    result: Mapping[str, Any],
    *,
    software_commit: str,
) -> dict[str, Any]:
    broker_orders = result.get(
        "broker_orders_sent",
        result.get(
            "broker_orders_submitted",
            0,
        ),
    )

    if broker_orders != 0:
        raise GuardedRunnerError("The session result records broker orders.")

    return {
        "status": result.get("status"),
        "session_date": result.get("session_date"),
        "policy_fingerprint": result.get("policy_fingerprint"),
        "software_commit": software_commit,
        "recovered_existing_journal": result.get(
            "recovered_existing_journal",
            False,
        ),
        "runtime_state_updated": result.get(
            "runtime_state_updated",
            False,
        ),
        "pending_entries_total": result.get(
            "pending_entries_total",
            0,
        ),
        "open_positions_total": result.get(
            "open_positions_total",
            0,
        ),
        "candidate_balance": result.get("candidate_balance"),
        "shadow_balance": result.get("shadow_balance"),
        "broker_orders_sent": 0,
    }


def execute(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    session_runner: SessionRunner | None = None,
    policy_verifier: PolicyVerifier | None = None,
    commit_reader: CommitReader | None = None,
    now_provider: NowProvider | None = None,
) -> dict[str, Any]:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if not arguments.use_oanda_practice:
        raise GuardedRunnerError(
            "Network collection is disabled. Pass --use-oanda-practice explicitly."
        )

    resolved_environment = os.environ if environment is None else environment

    oanda_environment = (
        resolved_environment.get(
            "OANDA_ENVIRONMENT",
            "practice",
        )
        .strip()
        .lower()
    )

    if oanda_environment != "practice":
        raise GuardedRunnerError("Only the OANDA practice environment is permitted.")

    api_token = resolved_environment.get(
        "OANDA_API_TOKEN",
        "",
    ).strip()

    if not api_token:
        raise GuardedRunnerError("OANDA_API_TOKEN is required.")

    account_id = resolved_environment.get(
        "OANDA_ACCOUNT_ID",
        "",
    ).strip()

    if not account_id:
        raise GuardedRunnerError("OANDA_ACCOUNT_ID is required.")

    minimum_margin_raw = resolved_environment.get(
        "OANDA_MINIMUM_MARGIN_AVAILABLE",
        "0",
    ).strip()

    try:
        minimum_margin_available = float(minimum_margin_raw)
    except ValueError as error:
        raise GuardedRunnerError("OANDA_MINIMUM_MARGIN_AVAILABLE must be numeric.") from error

    if minimum_margin_available < 0:
        raise GuardedRunnerError("OANDA_MINIMUM_MARGIN_AVAILABLE cannot be negative.")

    if arguments.candle_count < 21 or arguments.candle_count > 5000:
        raise GuardedRunnerError("Candle count must be between 21 and 5000.")

    resolved_commit_reader = read_git_snapshot if commit_reader is None else commit_reader

    software_commit, tracked_files_dirty = resolved_commit_reader()

    if tracked_files_dirty:
        raise GuardedRunnerError(
            "Tracked source files are modified. Commit or "
            "restore them before a prospective session."
        )

    resolved_policy_verifier = verify_frozen_policy if policy_verifier is None else policy_verifier

    policy_fingerprint = resolved_policy_verifier()

    if now_provider is None:
        session_time = datetime.now(UTC)
    else:
        session_time = now_provider()

    if session_time.tzinfo is None:
        raise GuardedRunnerError("Session time must be timezone-aware.")

    session_time = session_time.astimezone(UTC)

    session_date = resolve_session_date(
        arguments.session_date,
        current_time=session_time,
    )

    resolved_session_runner = (
        run_controlled_daily_session if session_runner is None else session_runner
    )

    def broker_preflight():
        runtime_state = read_runtime_state(STATE_PATH)

        return build_broker_backed_preflight(
            token=api_token,
            account_id=account_id,
            runtime_state=runtime_state,
            minimum_margin_available=(minimum_margin_available),
        )

    result = resolved_session_runner(
        api_token=api_token,
        session_date=session_date,
        ledger_path=LEDGER_PATH,
        state_path=STATE_PATH,
        journal_path=JOURNAL_PATH,
        candle_store_directory=(CANDLE_STORE_DIRECTORY),
        observation_store_path=(OBSERVATION_STORE_PATH),
        protocol_path=PROTOCOL_PATH,
        environment="practice",
        candle_count=(arguments.candle_count),
        policy_verifier=(lambda: policy_fingerprint),
        preflight_runner=broker_preflight,
        preflight_context={},
        session_time_utc=session_time,
        software_commit=software_commit,
    )

    return safe_summary(
        result,
        software_commit=software_commit,
    )


def redact_error(
    error: Exception,
    *,
    environment: Mapping[str, str],
) -> str:
    message = str(error)

    token = environment.get(
        "OANDA_API_TOKEN",
        "",
    )

    if token:
        message = message.replace(
            token,
            "[REDACTED]",
        )

    return message


def main(
    argv: Sequence[str] | None = None,
) -> int:
    try:
        summary = execute(argv)
    except Exception as error:
        message = redact_error(
            error,
            environment=os.environ,
        )

        print(
            f"ERROR: {type(error).__name__}: {message}",
            file=sys.stderr,
        )

        return 1

    print(
        json.dumps(
            summary,
            sort_keys=True,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
