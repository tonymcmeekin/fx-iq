"""Safely remove an uncommitted prospective paper-session tail."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.paper_trading.candle_store import read_candle_store  # noqa: E402
from app.paper_trading.ledger import canonical_json, verify_ledger  # noqa: E402
from app.paper_trading.orchestrator import observation_staging_path  # noqa: E402
from app.paper_trading.runtime_state import read_runtime_state  # noqa: E402

LEDGER_PATH = PROJECT_ROOT / "paper_ledger" / "events.jsonl"
STATE_PATH = PROJECT_ROOT / "paper_ledger" / "state.json"
JOURNAL_PATH = PROJECT_ROOT / "paper_ledger" / "transition.json"
OBSERVATION_PATH = (
    PROJECT_ROOT / "paper_ledger" / "intelligence_observations.jsonl"
)
CANDLE_DIRECTORY = PROJECT_ROOT / "data" / "prospective_paper"
BACKUP_ROOT = PROJECT_ROOT / "paper_ledger" / "recovery_backups"


class IncompleteSessionRecoveryError(RuntimeError):
    """Raised when an incomplete session cannot be repaired safely."""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    records = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise IncompleteSessionRecoveryError(
                f"Invalid JSONL record at {path.name}:{line_number}."
            ) from error

        if not isinstance(record, dict):
            raise IncompleteSessionRecoveryError(
                f"Non-object JSONL record at {path.name}:{line_number}."
            )
        records.append(record)

    return records


def _session_date(record: dict[str, Any]) -> str | None:
    value = record.get("session_date")
    if isinstance(value, str):
        return value

    payload = record.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("session_date"), str):
        return payload["session_date"]

    return None


def _assert_no_broker_activity(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {
                "broker_orders_sent",
                "broker_orders_submitted",
                "broker_order_submitted",
            } and child not in (0, False, None):
                raise IncompleteSessionRecoveryError(
                    "Recovery refused because broker activity is recorded."
                )
            _assert_no_broker_activity(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_broker_activity(child)


def _verify_candle_checkpoints(
    *,
    state: dict[str, Any],
    candle_directory: Path,
) -> None:
    checkpoints = state["processed_candle_timestamps"]
    markets = set(checkpoints)
    markets.update(path.stem for path in candle_directory.glob("*.csv"))

    for market in sorted(markets):
        candles = read_candle_store(
            candle_directory / f"{market}.csv",
            expected_symbol=market,
        )
        latest = (
            candles[-1]
            .timestamp.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z")
            if candles
            else None
        )
        checkpoint = checkpoints.get(market)

        if latest != checkpoint:
            raise IncompleteSessionRecoveryError(
                "Recovery refused because candle storage is ahead of "
                f"runtime state for {market}."
            )


def build_recovery_plan(
    *,
    session_date: date,
    ledger_path: Path = LEDGER_PATH,
    state_path: Path = STATE_PATH,
    journal_path: Path = JOURNAL_PATH,
    observation_path: Path = OBSERVATION_PATH,
    candle_directory: Path = CANDLE_DIRECTORY,
) -> dict[str, Any]:
    if journal_path.exists():
        raise IncompleteSessionRecoveryError(
            "Recovery refused while a transition journal exists."
        )

    events = verify_ledger(ledger_path)
    state = read_runtime_state(state_path)
    observations = _read_jsonl(observation_path)
    staging_path = observation_staging_path(
        observation_path,
        session_date,
    )
    staged_observations = _read_jsonl(
        staging_path
    )
    target = session_date.isoformat()

    _assert_no_broker_activity(state)

    target_indexes = [
        index
        for index, event in enumerate(events)
        if _session_date(event) == target
    ]

    if not target_indexes:
        raise IncompleteSessionRecoveryError(
            "No ledger events exist for the requested session."
        )

    if any(
        events[index]["event_type"] == "SESSION_COMPLETED"
        for index in target_indexes
    ):
        raise IncompleteSessionRecoveryError(
            "Recovery refused because the session is completed."
        )

    first_index = target_indexes[0]
    expected_tail = list(range(first_index, len(events)))

    if target_indexes != expected_tail:
        raise IncompleteSessionRecoveryError(
            "Recovery refused because target events are not a contiguous tail."
        )

    target_events = events[first_index:]

    if target_events[0]["event_type"] != "SESSION_STARTED":
        raise IncompleteSessionRecoveryError(
            "Recovery tail does not begin with SESSION_STARTED."
        )

    _assert_no_broker_activity(target_events)

    if state["last_completed_session_date"] == target:
        raise IncompleteSessionRecoveryError(
            "Recovery refused because runtime state completed the session."
        )

    _verify_candle_checkpoints(
        state=state,
        candle_directory=candle_directory,
    )

    target_observations = [
        record
        for record in observations
        if _session_date(record) == target
    ]

    if any(
        _session_date(record) != target
        for record in staged_observations
    ):
        raise IncompleteSessionRecoveryError(
            "Recovery refused because the staged observation "
            "file contains another session date."
        )

    return {
        "status": "RECOVERY_SAFE",
        "session_date": target,
        "events_total_before": len(events),
        "events_to_remove": len(target_events),
        "events_to_keep": first_index,
        "observations_total_before": len(observations),
        "observations_to_remove": len(target_observations),
        "staged_observations_to_remove": len(
            staged_observations
        ),
        "broker_orders_sent": 0,
        "event_types_to_remove": [
            event["event_type"]
            for event in target_events
        ],
    }


def _atomic_write_jsonl(
    path: Path,
    records: list[dict[str, Any]],
) -> None:
    temporary_path = path.with_name(f".{path.name}.recovery.tmp")
    if temporary_path.exists():
        raise IncompleteSessionRecoveryError(
            f"Recovery temporary file already exists for {path.name}."
        )

    encoded = "".join(
        canonical_json(record) + "\n"
        for record in records
    ).encode("utf-8")
    descriptor = os.open(
        temporary_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )

    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

    os.replace(temporary_path, path)


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_recovery_plan(
    *,
    session_date: date,
    ledger_path: Path = LEDGER_PATH,
    state_path: Path = STATE_PATH,
    journal_path: Path = JOURNAL_PATH,
    observation_path: Path = OBSERVATION_PATH,
    candle_directory: Path = CANDLE_DIRECTORY,
    backup_root: Path = BACKUP_ROOT,
    now_utc: datetime | None = None,
    require_clean_worktree: bool = True,
) -> dict[str, Any]:
    if require_clean_worktree:
        status = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if status.returncode != 0 or status.stdout.strip():
            raise IncompleteSessionRecoveryError(
                "Recovery requires a clean tracked source tree."
            )

    plan = build_recovery_plan(
        session_date=session_date,
        ledger_path=ledger_path,
        state_path=state_path,
        journal_path=journal_path,
        observation_path=observation_path,
        candle_directory=candle_directory,
    )
    resolved_now = now_utc or datetime.now(UTC)
    if resolved_now.tzinfo is None:
        raise ValueError("Recovery time must be timezone-aware.")

    stamp = resolved_now.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_directory = backup_root / f"{session_date.isoformat()}-{stamp}"
    backup_directory.mkdir(parents=True, exist_ok=False)

    staging_path = observation_staging_path(
        observation_path,
        session_date,
    )

    for path in (
        ledger_path,
        state_path,
        observation_path,
        staging_path,
    ):
        if path.exists():
            shutil.copy2(path, backup_directory / path.name)

    events = verify_ledger(ledger_path)
    observations = _read_jsonl(observation_path)
    target = session_date.isoformat()
    kept_events = [event for event in events if _session_date(event) != target]
    kept_observations = [
        record
        for record in observations
        if _session_date(record) != target
    ]

    before_hashes = {
        "ledger": _sha256(ledger_path),
        "observations": _sha256(observation_path),
        "state": _sha256(state_path),
    }
    _atomic_write_jsonl(ledger_path, kept_events)
    if observation_path.exists() or observations:
        _atomic_write_jsonl(observation_path, kept_observations)
    staging_path.unlink(
        missing_ok=True
    )

    verify_ledger(ledger_path)
    verified_plan = build_recovery_plan_after_apply(
        session_date=session_date,
        ledger_path=ledger_path,
        observation_path=observation_path,
    )

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip() or "UNKNOWN"
    receipt = {
        **plan,
        **verified_plan,
        "status": "RECOVERED",
        "recovered_at_utc": resolved_now.astimezone(UTC).isoformat(),
        "software_commit": commit,
        "backup_directory": str(backup_directory),
        "before_sha256": before_hashes,
        "after_sha256": {
            "ledger": _sha256(ledger_path),
            "observations": _sha256(observation_path),
            "state": _sha256(state_path),
        },
        "broker_orders_sent": 0,
    }
    receipt_path = backup_directory / "recovery_receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    receipt_path.chmod(0o600)
    return receipt


def build_recovery_plan_after_apply(
    *,
    session_date: date,
    ledger_path: Path,
    observation_path: Path,
) -> dict[str, int]:
    target = session_date.isoformat()
    remaining_events = [
        event
        for event in verify_ledger(ledger_path)
        if _session_date(event) == target
    ]
    remaining_observations = [
        record
        for record in _read_jsonl(observation_path)
        if _session_date(record) == target
    ]
    if remaining_events or remaining_observations:
        raise IncompleteSessionRecoveryError(
            "Recovery verification found target records remaining."
        )
    return {
        "target_events_remaining": 0,
        "target_observations_remaining": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or apply a backed-up repair of one provably "
            "uncommitted paper-session tail."
        )
    )
    parser.add_argument("--session-date", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create backups and apply the verified recovery plan.",
    )
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        target_date = date.fromisoformat(arguments.session_date)
        result = (
            apply_recovery_plan(session_date=target_date)
            if arguments.apply
            else build_recovery_plan(session_date=target_date)
        )
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
