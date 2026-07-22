"""Read-only readiness reporting for isolated canary rehearsals."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app.broker.canary_audit import CanaryAuditError, read_canary_audit
from app.broker.canary_failure_audit import (
    CanaryFailureAuditError,
    read_canary_failure_audit,
)
from app.broker.canary_gateway import LIVE_CANARY_BUILD_ENABLED

BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]
DEFAULT_CANARY_AUDIT_PATH = BACKEND_DIRECTORY / "paper_ledger" / "canary_rehearsals.jsonl"
DEFAULT_CANARY_FAILURE_AUDIT_PATH = (
    BACKEND_DIRECTORY / "paper_ledger" / "canary_rehearsal_failures.jsonl"
)
MINIMUM_PRACTICE_REHEARSALS = 20


def build_canary_readiness_report(
    *,
    audit_path: Path = DEFAULT_CANARY_AUDIT_PATH,
    failure_audit_path: Path = DEFAULT_CANARY_FAILURE_AUDIT_PATH,
) -> dict[str, Any]:
    """Verify canary receipts without contacting OANDA or enabling live execution."""
    try:
        records = read_canary_audit(audit_path)
        failures = read_canary_failure_audit(failure_audit_path)
    except (CanaryAuditError, CanaryFailureAuditError, OSError, ValueError) as error:
        return {
            "schema_version": 1,
            "status": "INTEGRITY_ERROR",
            "rehearsal_count": 0,
            "qualifying_rehearsal_count": 0,
            "failed_rehearsal_count": 0,
            "unresolved_failure_count": 0,
            "required_rehearsals": MINIMUM_PRACTICE_REHEARSALS,
            "remaining_rehearsals": MINIMUM_PRACTICE_REHEARSALS,
            "operational_rehearsal_target_met": False,
            "all_positions_verified_closed": False,
            "practice_entry_orders_submitted": 0,
            "practice_close_orders_submitted": 0,
            "live_orders_submitted": 0,
            "latest_rehearsal_id": None,
            "latest_completed_at_utc": None,
            "latest_instrument": None,
            "latest_failure_at_utc": None,
            "latest_failure_stage": None,
            "live_canary_build_enabled": LIVE_CANARY_BUILD_ENABLED,
            "live_execution_locked": True,
            "live_trading_allowed": False,
            "network_calls_made": 0,
            "files_changed": 0,
            "blocking_issues": [f"Canary audit integrity failed: {error}"],
            "next_actions": [
                "Stop canary rehearsals and inspect the local audit chain.",
                "Keep the live canary build lock disabled.",
            ],
        }

    rehearsal_count = len(records)
    latest_failure = failures[-1] if failures else None
    latest_failure_time = (
        None
        if latest_failure is None
        else datetime.fromisoformat(str(latest_failure["failed_at_utc"]).replace("Z", "+00:00"))
    )
    qualifying_records = [
        record
        for record in records
        if latest_failure_time is None
        or datetime.fromisoformat(str(record["completed_at_utc"]).replace("Z", "+00:00"))
        > latest_failure_time
    ]
    qualifying_count = len(qualifying_records)
    unresolved_failures = sum(
        1 for failure in failures if failure.get("operator_action_required") is True
    )
    remaining = max(0, MINIMUM_PRACTICE_REHEARSALS - qualifying_count)
    target_met = qualifying_count >= MINIMUM_PRACTICE_REHEARSALS
    all_closed = bool(records) and all(
        record.get("position_verified_open") is True
        and record.get("position_verified_closed") is True
        for record in records
    )
    live_orders = sum(int(record["live_orders_submitted"]) for record in records)
    latest = records[-1] if records else None
    next_actions = []
    if unresolved_failures:
        next_actions.append(
            "Reconcile the OANDA Practice account and resolve every action-required failure."
        )
    if remaining:
        next_actions.append(
            f"Complete {remaining} additional manually approved one-unit practice rehearsals."
        )
    else:
        next_actions.append(
            "Review the completed practice evidence; the target does not authorize live trading."
        )
    next_actions.append("Keep the live canary build lock disabled.")
    return {
        "schema_version": 1,
        "status": (
            "ACTION_REQUIRED"
            if unresolved_failures
            else "NO_EVIDENCE"
            if not records and not failures
            else "REHEARSAL_TARGET_MET"
            if target_met and all_closed and live_orders == 0 and not unresolved_failures
            else "REHEARSING"
        ),
        "rehearsal_count": rehearsal_count,
        "qualifying_rehearsal_count": qualifying_count,
        "failed_rehearsal_count": len(failures),
        "unresolved_failure_count": unresolved_failures,
        "required_rehearsals": MINIMUM_PRACTICE_REHEARSALS,
        "remaining_rehearsals": remaining,
        "operational_rehearsal_target_met": target_met and all_closed and live_orders == 0,
        "all_positions_verified_closed": all_closed,
        "practice_entry_orders_submitted": sum(
            int(record["practice_entry_orders_submitted"]) for record in records
        ),
        "practice_close_orders_submitted": sum(
            int(record["practice_close_orders_submitted"]) for record in records
        ),
        "live_orders_submitted": live_orders,
        "latest_rehearsal_id": None if latest is None else latest["rehearsal_id"],
        "latest_completed_at_utc": None if latest is None else latest["completed_at_utc"],
        "latest_instrument": None if latest is None else latest["instrument"],
        "latest_failure_at_utc": (
            None if latest_failure is None else latest_failure["failed_at_utc"]
        ),
        "latest_failure_stage": None if latest_failure is None else latest_failure["stage"],
        "live_canary_build_enabled": LIVE_CANARY_BUILD_ENABLED,
        "live_execution_locked": True,
        "live_trading_allowed": False,
        "network_calls_made": 0,
        "files_changed": 0,
        "blocking_issues": [],
        "next_actions": next_actions,
    }
