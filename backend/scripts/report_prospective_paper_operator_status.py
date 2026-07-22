import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]

if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND_DIRECTORY),
    )

from app.intelligence.reporting import build_observation_report  # noqa: E402
from scripts.check_prospective_paper_health import (  # noqa: E402
    perform_health_check,
)
from scripts.report_prospective_paper_evidence_gate import (  # noqa: E402
    build_evidence_gate_report,
)
from scripts.report_prospective_paper_performance import (  # noqa: E402
    DEFAULT_LEDGER_PATH,
    DEFAULT_STATE_PATH,
    build_performance_report,
)
from scripts.report_prospective_paper_rolling_analytics import (  # noqa: E402
    build_rolling_analytics_report,
)


class OperatorStatusError(RuntimeError):
    """Raised when an operator status report cannot be produced."""


def build_operator_status(
    *,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    health_report: dict[str, Any] | None = None,
    performance_report: dict[str, Any] | None = None,
    rolling_analytics_report: dict[str, Any] | None = None,
    observation_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_health = health_report if health_report is not None else perform_health_check()

    resolved_performance = (
        performance_report
        if performance_report is not None
        else build_performance_report(
            ledger_path=ledger_path,
            state_path=state_path,
        )
    )

    resolved_rolling = (
        rolling_analytics_report
        if rolling_analytics_report is not None
        else build_rolling_analytics_report(
            ledger_path=ledger_path,
            state_path=state_path,
        )
    )

    resolved_observations = (
        observation_report
        if observation_report is not None
        else build_observation_report(
            ledger_path=ledger_path,
            observation_path=(
                ledger_path.parent
                / "intelligence_observations.jsonl"
            ),
            outcome_path=(
                ledger_path.parent
                / "intelligence_outcomes.jsonl"
            ),
        )
    )

    runtime_health = resolved_health.get("status")

    performance_status = resolved_performance.get("status")

    rolling_analytics_status = resolved_rolling.get("status")

    observation_integrity_status = resolved_observations.get(
        "status"
    )

    blocking_issues: list[str] = []
    warnings: list[str] = []

    health_broker_orders = int(
        resolved_health.get(
            "broker_orders_sent",
            0,
        )
    )

    performance_broker_orders = int(
        resolved_performance.get(
            "broker_orders_sent",
            0,
        )
    )

    rolling_broker_orders = int(
        resolved_rolling.get(
            "broker_orders_sent",
            0,
        )
    )

    observation_broker_orders = int(
        resolved_observations.get(
            "broker_orders_sent",
            0,
        )
    )

    broker_orders_sent = max(
        health_broker_orders,
        performance_broker_orders,
        rolling_broker_orders,
        observation_broker_orders,
    )

    if runtime_health != "HEALTHY":
        blocking_issues.append("Prospective paper runtime health is not HEALTHY.")

    if observation_integrity_status != "HEALTHY":
        blocking_issues.append(
            "Passive-observation integrity is not HEALTHY."
        )

    if broker_orders_sent != 0:
        blocking_issues.append("Broker-order activity was recorded.")

    duplicate_dates = resolved_performance.get(
        "duplicate_completed_session_dates",
        [],
    )

    if duplicate_dates:
        blocking_issues.append("Duplicate completed prospective sessions were detected.")

    failed_sessions = int(
        resolved_performance.get(
            "failed_sessions",
            0,
        )
    )

    if failed_sessions > 0:
        warnings.append(
            f"{failed_sessions} failed prospective session"
            + (" was" if failed_sessions == 1 else "s were")
            + " recorded."
        )

    completed_sessions = int(
        resolved_performance.get(
            "completed_sessions",
            0,
        )
    )

    minimum_sessions = int(
        resolved_performance.get(
            "minimum_completed_sessions_required",
            0,
        )
    )

    if completed_sessions < minimum_sessions:
        warnings.append(
            f"Only {completed_sessions} completed prospective "
            f"session"
            + (" is" if completed_sessions == 1 else "s are")
            + f" available; {minimum_sessions} are required "
            "for the current evidence threshold."
        )

    positions_closed = int(
        resolved_performance.get(
            "positions_closed",
            0,
        )
    )

    minimum_closed_positions = int(
        resolved_performance.get(
            "minimum_closed_positions_required",
            0,
        )
    )

    if positions_closed == 0:
        warnings.append(
            "No closed prospective paper positions are available for performance evaluation."
        )
    elif positions_closed < minimum_closed_positions:
        warnings.append(
            f"Only {positions_closed} closed prospective paper "
            f"positions are available; {minimum_closed_positions} "
            "are required for the current evidence threshold."
        )

    actionable_signals = int(
        resolved_performance.get(
            "actionable_signals",
            0,
        )
    )

    if actionable_signals == 0:
        warnings.append("No actionable BUY or SELL signals have yet been recorded.")

    rolling_completed_sessions = int(
        resolved_rolling.get(
            "completed_sessions",
            0,
        )
    )

    rolling_positions_closed = int(
        resolved_rolling.get(
            "positions_closed",
            0,
        )
    )

    if rolling_completed_sessions != completed_sessions:
        blocking_issues.append(
            "Rolling analytics completed-session count does not match the performance report."
        )

    if rolling_positions_closed != positions_closed:
        blocking_issues.append(
            "Rolling analytics closed-position count does not match the performance report."
        )

    rolling_evidence_ready = (
        rolling_analytics_status == "SUFFICIENT_DATA"
        and rolling_completed_sessions >= minimum_sessions
        and rolling_positions_closed >= minimum_closed_positions
    )

    candidate_expectancy = resolved_rolling.get("candidate_expectancy_amount")

    candidate_profit_factor = resolved_rolling.get("candidate_profit_factor")

    candidate_win_rate = resolved_rolling.get("candidate_win_rate_percent")

    if positions_closed > 0:
        if candidate_expectancy is None:
            warnings.append(
                "Candidate trade expectancy is not available from the recorded close events."
            )

        if candidate_profit_factor is None:
            warnings.append(
                "Candidate profit factor is not yet available from the recorded evidence."
            )

        if candidate_win_rate is None:
            warnings.append("Candidate win rate is not yet available from the recorded evidence.")

    safe_to_continue = (
        not blocking_issues and runtime_health == "HEALTHY" and broker_orders_sent == 0
    )

    if not safe_to_continue:
        status = "BLOCKED"
    elif performance_status == "SUFFICIENT_DATA" and rolling_evidence_ready:
        status = "EVIDENCE_REVIEW_REQUIRED"
    else:
        status = "OBSERVING"

    report = {
        "status": status,
        "runtime_health": runtime_health,
        "performance_status": (performance_status),
        "rolling_analytics_status": (rolling_analytics_status),
        "observation_integrity_status": (
            observation_integrity_status
        ),
        "observations_recorded": int(
            resolved_observations.get(
                "observation_count",
                0,
            )
        ),
        "observation_outcomes_populated": int(
            resolved_observations.get(
                "outcomes_populated",
                0,
            )
        ),
        "observation_integrity_warnings": list(
            resolved_observations.get(
                "warnings",
                [],
            )
        ),
        "rolling_evidence_ready": (rolling_evidence_ready),
        "safe_to_continue_paper_observation": (safe_to_continue),
        "safe_for_live_trading": False,
        "live_trading_decision": ("PROHIBITED_BY_REPORT"),
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "completed_sessions": (completed_sessions),
        "minimum_completed_sessions_required": (minimum_sessions),
        "signals_evaluated": int(
            resolved_performance.get(
                "signals_evaluated",
                0,
            )
        ),
        "actionable_signals": (actionable_signals),
        "positions_opened": int(
            resolved_performance.get(
                "positions_opened",
                0,
            )
        ),
        "positions_closed": (positions_closed),
        "minimum_closed_positions_required": (minimum_closed_positions),
        "candidate_balance": (resolved_performance.get("candidate_balance")),
        "candidate_return_percent": (resolved_performance.get("candidate_return_percent")),
        "shadow_balance": (resolved_performance.get("shadow_balance")),
        "shadow_return_percent": (resolved_performance.get("shadow_return_percent")),
        "candidate_max_drawdown_percent": (resolved_rolling.get("candidate_max_drawdown_percent")),
        "shadow_max_drawdown_percent": (resolved_rolling.get("shadow_max_drawdown_percent")),
        "candidate_expectancy_amount": (candidate_expectancy),
        "candidate_profit_factor": (candidate_profit_factor),
        "candidate_win_rate_percent": (candidate_win_rate),
        "candidate_average_trade_return_percent": (
            resolved_rolling.get("candidate_average_trade_return_percent")
        ),
        "profitable_sessions": int(
            resolved_rolling.get(
                "profitable_sessions",
                0,
            )
        ),
        "losing_sessions": int(
            resolved_rolling.get(
                "losing_sessions",
                0,
            )
        ),
        "flat_sessions": int(
            resolved_rolling.get(
                "flat_sessions",
                0,
            )
        ),
        "rolling_5_session_candidate_return_percent": (
            resolved_rolling.get("rolling_5_session_candidate_return_percent")
        ),
        "rolling_20_session_candidate_return_percent": (
            resolved_rolling.get("rolling_20_session_candidate_return_percent")
        ),
        "last_completed_session_date": (resolved_performance.get("last_completed_session_date")),
        "ledger_events": int(
            resolved_performance.get(
                "ledger_events",
                0,
            )
        ),
        "broker_orders_sent": (broker_orders_sent),
        "network_calls_made": 0,
        "files_changed": 0,
    }

    evidence_gate = build_evidence_gate_report(
        ledger_path=ledger_path,
        state_path=state_path,
        operator_report=report,
        rolling_analytics_report=resolved_rolling,
    )

    report.update(
        {
            "evidence_gate_status": evidence_gate.get("evidence_gate_status"),
            "protocol_assessment_date": evidence_gate.get("assessment_date"),
            "first_eligible_market_date": evidence_gate.get("first_eligible_market_date"),
            "earliest_eligible_assessment_date": evidence_gate.get(
                "earliest_eligible_assessment_date"
            ),
            "elapsed_calendar_days": evidence_gate.get("elapsed_calendar_days"),
            "minimum_calendar_days_required": evidence_gate.get("minimum_calendar_days_required"),
            "minimum_closed_trades_required": evidence_gate.get("minimum_closed_trades_required"),
            "calendar_days_gate": evidence_gate.get("calendar_days_gate"),
            "closed_trades_gate": evidence_gate.get("closed_trades_gate"),
            "protocol_sample_size_gate": evidence_gate.get("sample_size_gate"),
            "protocol_candidate_return_gate": evidence_gate.get("candidate_return_gate"),
            "protocol_return_exceeds_shadow_gate": evidence_gate.get("return_exceeds_shadow_gate"),
            "protocol_drawdown_gate": evidence_gate.get("drawdown_gate"),
            "protocol_profit_factor_gate": evidence_gate.get("profit_factor_gate"),
            "protocol_positive_markets_gate": evidence_gate.get("positive_markets_gate"),
            "protocol_runtime_integrity_gate": evidence_gate.get("runtime_integrity_gate"),
            "protocol_failed_criteria": evidence_gate.get(
                "failed_criteria",
                [],
            ),
            "protocol_unevaluable_criteria": evidence_gate.get(
                "unevaluable_criteria",
                [],
            ),
            "protocol_immediate_stop_reasons": evidence_gate.get(
                "immediate_stop_reasons",
                [],
            ),
            "protocol_test_passed": evidence_gate.get(
                "protocol_test_passed",
                False,
            ),
            "protocol_live_trading_permitted": False,
        }
    )

    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Produce a combined read-only operator status report for prospective paper trading."
        )
    )

    parser.add_argument(
        "--ledger-path",
        type=Path,
        default=DEFAULT_LEDGER_PATH,
    )

    parser.add_argument(
        "--state-path",
        type=Path,
        default=DEFAULT_STATE_PATH,
    )

    return parser


def main() -> int:
    arguments = build_parser().parse_args()

    try:
        report = build_operator_status(
            ledger_path=arguments.ledger_path,
            state_path=arguments.state_path,
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "safe_to_continue_paper_observation": False,
                    "safe_for_live_trading": False,
                    "network_calls_made": 0,
                    "files_changed": 0,
                },
                sort_keys=True,
                indent=2,
            ),
            file=sys.stderr,
        )

        return 1

    print(
        json.dumps(
            report,
            sort_keys=True,
            indent=2,
        )
    )

    return 0 if report["safe_to_continue_paper_observation"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
