"""Read-only readiness reporting for isolated canary rehearsals."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.broker.canary_audit import CanaryAuditError, read_canary_audit
from app.broker.canary_gateway import LIVE_CANARY_BUILD_ENABLED

BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]
DEFAULT_CANARY_AUDIT_PATH = BACKEND_DIRECTORY / "paper_ledger" / "canary_rehearsals.jsonl"
MINIMUM_PRACTICE_REHEARSALS = 20


def build_canary_readiness_report(
    *,
    audit_path: Path = DEFAULT_CANARY_AUDIT_PATH,
) -> dict[str, Any]:
    """Verify canary receipts without contacting OANDA or enabling live execution."""
    try:
        records = read_canary_audit(audit_path)
    except (CanaryAuditError, OSError, ValueError) as error:
        return {
            "schema_version": 1,
            "status": "INTEGRITY_ERROR",
            "rehearsal_count": 0,
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
    remaining = max(0, MINIMUM_PRACTICE_REHEARSALS - rehearsal_count)
    target_met = rehearsal_count >= MINIMUM_PRACTICE_REHEARSALS
    all_closed = bool(records) and all(
        record.get("position_verified_open") is True
        and record.get("position_verified_closed") is True
        for record in records
    )
    live_orders = sum(int(record["live_orders_submitted"]) for record in records)
    latest = records[-1] if records else None
    next_actions = []
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
            "NO_EVIDENCE"
            if not records
            else "REHEARSAL_TARGET_MET"
            if target_met and all_closed and live_orders == 0
            else "REHEARSING"
        ),
        "rehearsal_count": rehearsal_count,
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
        "live_canary_build_enabled": LIVE_CANARY_BUILD_ENABLED,
        "live_execution_locked": True,
        "live_trading_allowed": False,
        "network_calls_made": 0,
        "files_changed": 0,
        "blocking_issues": [],
        "next_actions": next_actions,
    }
