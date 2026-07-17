"""Deterministic explanations of protocol readiness."""

from __future__ import annotations

from typing import Any

from app.analytics.readiness_reporting import (
    ReadinessReportError,
    build_readiness_report,
)


class ReadinessExplanationError(RuntimeError):
    """Raised when a readiness explanation cannot be built."""


def _plural(
    value: int,
    singular: str,
    plural: str | None = None,
) -> str:
    word = singular if value == 1 else (plural or f"{singular}s")
    return f"{value} {word}"


def _build_progress_summary(
    report: dict[str, Any],
) -> list[str]:
    progress = report["progress"]

    sessions = progress["completed_sessions"]
    trades = progress["closed_trades"]
    calendar = progress["calendar_requirement"]

    lines = [
        (f"Prospective paper sessions: {sessions['current']} of {sessions['required']} completed."),
        (f"Closed paper trades: {trades['current']} of {trades['required']} completed."),
    ]

    eligible_date = calendar.get("earliest_eligible_assessment_date")

    if eligible_date:
        if calendar["requirement_met"]:
            lines.append("The minimum calendar observation requirement has been reached.")
        else:
            lines.append(f"The earliest eligible evidence assessment date is {eligible_date}.")
    else:
        lines.append("No eligible evidence assessment date is currently available.")

    return lines


def _build_status_summary(
    report: dict[str, Any],
) -> str:
    current_stage = report["current_stage"]
    paper_allowed = report["paper_observation_allowed"]
    blocking_issues = report["blocking_issues"]
    stop_reasons = report["immediate_stop_reasons"]

    if stop_reasons:
        return (
            "The protocol is in a safety review "
            "because an immediate-stop condition "
            "has been recorded."
        )

    if blocking_issues:
        return "The protocol is in a safety review because blocking issues must be resolved."

    if not paper_allowed:
        return "Prospective paper observation is currently paused."

    if current_stage == "EVIDENCE_QUALIFIED":
        return (
            "The recorded evidence currently satisfies the configured evidence qualification stage."
        )

    if current_stage == "EVIDENCE_ASSESSMENT":
        return "The protocol has reached the evidence assessment stage."

    if current_stage == ("AWAITING_ASSESSMENT_DATE"):
        return (
            "The count-based evidence requirements "
            "have been reached, but the minimum "
            "calendar observation period has not."
        )

    return "Trade IQ remains in prospective paper observation while evidence is accumulated."


def _build_requirement_summary(
    report: dict[str, Any],
) -> str:
    progress = report["progress"]

    sessions_remaining = progress["completed_sessions"]["remaining"]
    trades_remaining = progress["closed_trades"]["remaining"]
    calendar_met = progress["calendar_requirement"]["requirement_met"]

    outstanding: list[str] = []

    if sessions_remaining:
        outstanding.append(
            _plural(
                sessions_remaining,
                "additional session",
            )
        )

    if trades_remaining:
        outstanding.append(
            _plural(
                trades_remaining,
                "additional closed trade",
            )
        )

    if not calendar_met:
        outstanding.append("completion of the minimum calendar observation period")

    if not outstanding:
        return "All displayed observation thresholds have been reached."

    if len(outstanding) == 1:
        requirements = outstanding[0]
    else:
        requirements = ", ".join(outstanding[:-1]) + f", and {outstanding[-1]}"

    return f"The current evidence threshold still requires {requirements}."


def _build_evidence_summary(
    report: dict[str, Any],
) -> str:
    failed = report["failed_criteria"]
    unevaluable = report["unevaluable_criteria"]

    if failed and unevaluable:
        return (
            f"{len(failed)} protocol criteria have "
            f"failed and {len(unevaluable)} remain "
            "unevaluable."
        )

    if failed:
        return f"{len(failed)} protocol criteria have failed."

    if unevaluable:
        return f"{len(unevaluable)} protocol criteria remain unevaluable."

    return "No failed or unevaluable protocol criteria are currently reported."


def build_readiness_explanation() -> dict[str, Any]:
    """Build a deterministic operator briefing."""

    try:
        report = build_readiness_report()
    except ReadinessReportError:
        raise
    except Exception as error:
        raise ReadinessExplanationError(str(error)) from error

    progress_summary = _build_progress_summary(report)
    status_summary = _build_status_summary(report)
    requirement_summary = _build_requirement_summary(report)
    evidence_summary = _build_evidence_summary(report)

    safety_statement = (
        "This report authorises paper observation "
        "only where explicitly shown. It does not "
        "authorise live trading."
    )

    briefing = " ".join(
        [
            status_summary,
            requirement_summary,
            evidence_summary,
            safety_statement,
        ]
    )

    return {
        "schema_version": 1,
        "status": report["status"],
        "current_stage": report["current_stage"],
        "headline": "Trade IQ readiness briefing",
        "briefing": briefing,
        "status_summary": status_summary,
        "requirement_summary": requirement_summary,
        "evidence_summary": evidence_summary,
        "progress_summary": progress_summary,
        "blocking_issues": list(report["blocking_issues"]),
        "warnings": list(report["warnings"]),
        "next_actions": list(report["next_actions"]),
        "safety_statement": safety_statement,
        "paper_observation_allowed": report["paper_observation_allowed"],
        "live_trading_allowed": False,
        "network_calls_made": 0,
        "files_changed": 0,
        "ledger_writes_performed": 0,
        "broker_orders_submitted": 0,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
    }
