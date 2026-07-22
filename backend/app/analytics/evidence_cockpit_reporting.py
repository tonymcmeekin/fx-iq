"""Read-only evidence cockpit assembled from verified paper artifacts."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.analytics.operator_status_reporting import (
    perform_report as perform_operator_status_report,
)
from app.analytics.prospective_health_reporting import (
    perform_report as perform_health_report,
)
from app.analytics.readiness_reporting import (
    build_readiness_report,
)
from app.paper_trading.ledger import verify_ledger
from app.paper_trading.policy import verify_frozen_policy
from app.paper_trading.runtime_state import read_runtime_state
from app.paper_trading.session_receipts import (
    verify_session_receipt,
)

BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER_PATH = BACKEND_DIRECTORY / "paper_ledger" / "events.jsonl"
DEFAULT_STATE_PATH = BACKEND_DIRECTORY / "paper_ledger" / "state.json"
DEFAULT_RECEIPT_DIRECTORY = BACKEND_DIRECTORY / "paper_ledger" / "receipts"


class EvidenceCockpitError(RuntimeError):
    """Raised when verified cockpit evidence cannot be assembled."""


def read_git_snapshot() -> tuple[str, bool]:
    """Return the current commit and tracked-source cleanliness."""
    commit_process = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=BACKEND_DIRECTORY,
        capture_output=True,
        text=True,
        check=False,
    )
    status_process = subprocess.run(
        ["git", "status", "--short", "--untracked-files=no"],
        cwd=BACKEND_DIRECTORY,
        capture_output=True,
        text=True,
        check=False,
    )

    commit = commit_process.stdout.strip()
    if commit_process.returncode != 0 or not commit:
        raise EvidenceCockpitError("Current software commit could not be verified.")
    if status_process.returncode != 0:
        raise EvidenceCockpitError("Tracked-source status could not be verified.")

    return commit, not bool(status_process.stdout.strip())


def _session_lineage(
    events: list[dict[str, Any]],
    *,
    receipt_directory: Path,
) -> list[dict[str, Any]]:
    starts = {
        event["payload"]["session_date"]: event
        for event in events
        if event["event_type"] == "SESSION_STARTED"
    }
    completed = [
        event
        for event in events
        if event["event_type"] == "SESSION_COMPLETED"
    ]
    lineage = []

    for completion in completed[-5:]:
        session_date = str(completion["payload"]["session_date"])
        start = starts.get(session_date)
        receipt_path = receipt_directory / f"{session_date}.json"
        receipt_status = "NOT_AVAILABLE"
        receipt_hash = None

        if receipt_path.exists():
            receipt = verify_session_receipt(receipt_path)
            receipt_status = "VERIFIED"
            receipt_hash = receipt["receipt_hash"]

        lineage.append(
            {
                "session_date": session_date,
                "started_event_id": (
                    start["event_id"] if start is not None else None
                ),
                "completed_event_id": completion["event_id"],
                "completed_event_hash": completion["event_hash"],
                "software_commit": (
                    start["payload"].get("software_commit")
                    if start is not None
                    else None
                ),
                "policy_fingerprint": (
                    start["payload"].get("policy_fingerprint")
                    if start is not None
                    else None
                ),
                "receipt_status": receipt_status,
                "receipt_hash": receipt_hash,
            }
        )

    return lineage


def _position_risk(position: dict[str, Any]) -> float | None:
    value = position.get("candidate_risk_percent")
    if value is None:
        candidate = position.get("candidate")
        if isinstance(candidate, dict):
            value = candidate.get("configured_risk_percent")
    return None if value is None else float(value)


def build_evidence_cockpit(
    *,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    receipt_directory: Path = DEFAULT_RECEIPT_DIRECTORY,
    health_report: dict[str, Any] | None = None,
    operator_report: dict[str, Any] | None = None,
    readiness_report: dict[str, Any] | None = None,
    git_snapshot_reader: Callable[[], tuple[str, bool]] = read_git_snapshot,
    policy_verifier: Callable[[], str] = verify_frozen_policy,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Build a non-mutating operator cockpit from verified evidence."""
    try:
        events = verify_ledger(ledger_path)
        state = read_runtime_state(state_path)
        health = health_report or perform_health_report()
        operator = operator_report or perform_operator_status_report()
        readiness = readiness_report or build_readiness_report()
        current_commit, tracked_source_clean = git_snapshot_reader()
        current_policy_fingerprint = policy_verifier()
        lineage = _session_lineage(
            events,
            receipt_directory=receipt_directory,
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise EvidenceCockpitError(str(error)) from error

    resolved_now = now_utc or datetime.now(UTC)
    if resolved_now.tzinfo is None:
        raise EvidenceCockpitError("Cockpit time must be timezone-aware.")

    latest_lineage = lineage[-1] if lineage else None
    market_rows = [
        {
            "market": market,
            "latest_complete_timestamp": details.get("latest_timestamp"),
            "stored_candles": int(details.get("rows", 0)),
        }
        for market, details in sorted(
            dict(health.get("markets") or {}).items()
        )
    ]
    market_timestamps = {
        row["latest_complete_timestamp"]
        for row in market_rows
        if row["latest_complete_timestamp"] is not None
    }
    pending_entries = [
        {
            "market": market,
            "direction": entry.get("direction"),
            "signal_candle_timestamp": entry.get(
                "signal_candle_timestamp"
            ),
            "candidate_risk_percent": _position_risk(entry),
        }
        for market, entry in sorted(state["pending_entries"].items())
    ]
    open_positions = [
        {
            "market": market,
            "direction": position.get("direction"),
            "entry_timestamp": position.get("entry_timestamp"),
            "candidate_risk_percent": _position_risk(position),
        }
        for market, position in sorted(state["open_positions"].items())
    ]

    last_completed_value = health.get("last_completed_session_date")
    next_session_date = None
    if last_completed_value:
        next_session_date = (
            date.fromisoformat(str(last_completed_value))
            + timedelta(days=1)
        ).isoformat()

    blocking_issues = list(operator.get("blocking_issues") or [])
    if not tracked_source_clean:
        blocking_issues.append("Tracked source contains uncommitted changes.")
    if health.get("status") != "HEALTHY":
        blocking_issues.append("Prospective paper runtime is not healthy.")
    if operator.get("observation_integrity_status") != "HEALTHY":
        blocking_issues.append("Passive-observation integrity is not healthy.")

    if blocking_issues:
        next_action = "RESOLVE_BLOCKING_ISSUES"
    elif pending_entries:
        next_action = "WAIT_FOR_NEXT_COMPLETE_CANDLE"
    else:
        next_action = "RUN_NEXT_GUARDED_PAPER_SESSION"

    warnings = [
        *list(operator.get("warnings") or []),
        *list(operator.get("observation_integrity_warnings") or []),
    ]
    if latest_lineage and latest_lineage["receipt_status"] == "NOT_AVAILABLE":
        warnings.append(
            "The latest completed session predates immutable session receipts."
        )

    return {
        "schema_version": 1,
        "status": "BLOCKED" if blocking_issues else "HEALTHY",
        "generated_at_utc": resolved_now.astimezone(UTC).isoformat(),
        "current_software_commit": current_commit,
        "tracked_source_clean": tracked_source_clean,
        "current_policy_fingerprint": current_policy_fingerprint,
        "protocol_mode": "SIMULATION_ONLY",
        "live_order_submission_permitted": False,
        "runtime_health": health.get("status"),
        "operator_status": operator.get("status"),
        "evidence_gate_status": operator.get("evidence_gate_status"),
        "observation_integrity_status": operator.get(
            "observation_integrity_status"
        ),
        "candidate_balance": health.get("candidate_balance"),
        "shadow_balance": health.get("shadow_balance"),
        "broker_orders_sent": int(health.get("broker_orders_sent", 0)),
        "last_completed_session_date": last_completed_value,
        "next_session_date": next_session_date,
        "next_action": next_action,
        "markets_aligned": len(market_timestamps) <= 1,
        "markets": market_rows,
        "pending_entries": pending_entries,
        "open_positions": open_positions,
        "observations_recorded": int(
            operator.get("observations_recorded", 0)
        ),
        "observation_outcomes_populated": int(
            operator.get("observation_outcomes_populated", 0)
        ),
        "session_lineage": lineage,
        "software_changed_since_last_session": bool(
            latest_lineage
            and latest_lineage["software_commit"] != current_commit
        ),
        "policy_matches_last_session": bool(
            latest_lineage
            and latest_lineage["policy_fingerprint"]
            == current_policy_fingerprint
        ),
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "readiness_next_actions": list(readiness.get("next_actions") or []),
        "network_calls_made": 0,
        "files_changed": 0,
        "ledger_writes_performed": 0,
        "broker_orders_submitted": 0,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
    }
