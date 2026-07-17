"""Read-only protocol readiness reporting."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.analytics.operator_status_reporting import (
    build_operator_status,
)


class ReadinessReportError(RuntimeError):
    """Raised when readiness cannot be determined safely."""


_READY_STATUSES = {
    "READY",
    "PASSED",
    "PASS",
    "ELIGIBLE",
    "QUALIFIED",
}


def _safe_int(
    value: object,
    *,
    default: int = 0,
) -> int:
    try:
        return max(int(value), 0)
    except TypeError, ValueError:
        return default


def _date_requirement_met(
    earliest_date: str | None,
) -> bool:
    if not earliest_date:
        return False

    try:
        return date.today() >= date.fromisoformat(earliest_date)
    except ValueError:
        return False


def _progress_item(
    *,
    current: int,
    required: int,
) -> dict[str, int | bool]:
    return {
        "current": current,
        "required": required,
        "remaining": max(required - current, 0),
        "requirement_met": (required > 0 and current >= required),
    }


def _determine_stage(
    *,
    operator: dict[str, Any],
    sessions_met: bool,
    trades_met: bool,
    date_met: bool,
) -> tuple[str, str | None]:
    blocking_issues = list(operator.get("blocking_issues") or [])
    immediate_stop_reasons = list(operator.get("protocol_immediate_stop_reasons") or [])
    safe_to_continue = bool(
        operator.get(
            "safe_to_continue_paper_observation",
            False,
        )
    )
    evidence_status = str(operator.get("evidence_gate_status") or "").upper()

    if immediate_stop_reasons or blocking_issues:
        return "SAFETY_REVIEW", "PROTOCOL_OBSERVATION"

    if not safe_to_continue:
        return "PAPER_OBSERVATION_PAUSED", None

    if evidence_status in _READY_STATUSES:
        return "EVIDENCE_QUALIFIED", None

    if sessions_met and trades_met and date_met:
        return "EVIDENCE_ASSESSMENT", ("EVIDENCE_QUALIFIED")

    if sessions_met and trades_met:
        return "AWAITING_ASSESSMENT_DATE", ("EVIDENCE_ASSESSMENT")

    return "PROTOCOL_OBSERVATION", ("EVIDENCE_ASSESSMENT")


def _build_next_actions(
    *,
    operator: dict[str, Any],
    completed_sessions: int,
    required_sessions: int,
    positions_closed: int,
    required_trades: int,
    earliest_date: str | None,
    date_met: bool,
) -> list[str]:
    actions: list[str] = []

    if not bool(
        operator.get(
            "safe_to_continue_paper_observation",
            False,
        )
    ):
        actions.append("Resolve all blocking issues before continuing paper observation.")

    if completed_sessions < required_sessions:
        remaining = required_sessions - completed_sessions
        actions.append(
            f"Complete {remaining} additional "
            "prospective paper session" + ("" if remaining == 1 else "s") + "."
        )

    if positions_closed < required_trades:
        remaining = required_trades - positions_closed
        actions.append(
            f"Accumulate {remaining} additional "
            "closed paper trade" + ("" if remaining == 1 else "s") + " under the frozen protocol."
        )

    if earliest_date and not date_met:
        actions.append(f"Continue unchanged paper observation until at least {earliest_date}.")

    failed = list(operator.get("protocol_failed_criteria") or [])
    unevaluable = list(operator.get("protocol_unevaluable_criteria") or [])

    if failed:
        actions.append("Review the failed protocol criteria without changing the frozen strategy.")

    if unevaluable:
        actions.append(
            "Collect sufficient evidence to make the unevaluable protocol criteria assessable."
        )

    if not actions:
        actions.append(
            "Maintain the frozen paper-trading protocol and await formal evidence assessment."
        )

    return actions


def build_readiness_report() -> dict[str, Any]:
    """Build a protocol-grounded readiness decision."""

    try:
        operator = build_operator_status()
    except Exception as error:
        raise ReadinessReportError(str(error)) from error

    completed_sessions = _safe_int(operator.get("completed_sessions"))
    required_sessions = _safe_int(operator.get("minimum_completed_sessions_required"))
    positions_closed = _safe_int(operator.get("positions_closed"))
    required_trades = _safe_int(operator.get("minimum_closed_trades_required"))

    earliest_date_value = operator.get("earliest_eligible_assessment_date")
    earliest_date = str(earliest_date_value) if earliest_date_value else None

    sessions_progress = _progress_item(
        current=completed_sessions,
        required=required_sessions,
    )
    trades_progress = _progress_item(
        current=positions_closed,
        required=required_trades,
    )
    date_met = _date_requirement_met(earliest_date)

    current_stage, next_stage = _determine_stage(
        operator=operator,
        sessions_met=bool(sessions_progress["requirement_met"]),
        trades_met=bool(trades_progress["requirement_met"]),
        date_met=date_met,
    )

    next_actions = _build_next_actions(
        operator=operator,
        completed_sessions=completed_sessions,
        required_sessions=required_sessions,
        positions_closed=positions_closed,
        required_trades=required_trades,
        earliest_date=earliest_date,
        date_met=date_met,
    )

    return {
        "schema_version": 1,
        "status": operator.get(
            "status",
            "UNKNOWN",
        ),
        "current_stage": current_stage,
        "next_stage": next_stage,
        "evidence_gate_status": operator.get("evidence_gate_status"),
        "progress": {
            "completed_sessions": (sessions_progress),
            "closed_trades": trades_progress,
            "calendar_requirement": {
                "earliest_eligible_assessment_date": (earliest_date),
                "requirement_met": date_met,
            },
        },
        "blocking_issues": list(operator.get("blocking_issues") or []),
        "warnings": list(operator.get("warnings") or []),
        "failed_criteria": list(operator.get("protocol_failed_criteria") or []),
        "unevaluable_criteria": list(operator.get("protocol_unevaluable_criteria") or []),
        "immediate_stop_reasons": list(operator.get("protocol_immediate_stop_reasons") or []),
        "next_actions": next_actions,
        "paper_observation_allowed": bool(
            operator.get(
                "safe_to_continue_paper_observation",
                False,
            )
        ),
        "live_trading_allowed": False,
        "network_calls_made": 0,
        "files_changed": 0,
        "ledger_writes_performed": 0,
        "broker_orders_submitted": 0,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
    }
