import json

from scripts import (
    report_prospective_paper_operator_status as operator_status,
)


def healthy_report() -> dict:
    return {
        "status": "HEALTHY",
        "broker_orders_sent": 0,
    }


def performance_report(
    *,
    status: str = "INSUFFICIENT_DATA",
    completed_sessions: int = 1,
    positions_closed: int = 0,
    actionable_signals: int = 0,
    failed_sessions: int = 0,
    broker_orders_sent: int = 0,
    duplicate_dates: list[str] | None = None,
) -> dict:
    return {
        "status": status,
        "ledger_events": 14,
        "completed_sessions": (completed_sessions),
        "failed_sessions": (failed_sessions),
        "minimum_completed_sessions_required": 20,
        "signals_evaluated": 6,
        "actionable_signals": (actionable_signals),
        "positions_opened": 0,
        "positions_closed": (positions_closed),
        "minimum_closed_positions_required": 10,
        "candidate_balance": 10000.0,
        "candidate_return_percent": 0.0,
        "shadow_balance": 10000.0,
        "shadow_return_percent": 0.0,
        "last_completed_session_date": ("2026-07-17"),
        "duplicate_completed_session_dates": (duplicate_dates or []),
        "broker_orders_sent": (broker_orders_sent),
    }


def test_healthy_insufficient_data_is_observing():
    result = operator_status.build_operator_status(
        health_report=healthy_report(),
        performance_report=(performance_report()),
    )

    assert result["status"] == ("OBSERVING")

    assert result["safe_to_continue_paper_observation"] is True

    assert result["safe_for_live_trading"] is False

    assert result["live_trading_decision"] == "PROHIBITED_BY_REPORT"

    assert result["blocking_issues"] == []

    assert any("Only 1 completed" in warning for warning in result["warnings"])

    assert any("No closed" in warning for warning in result["warnings"])


def test_unhealthy_runtime_blocks_observation():
    health = healthy_report()
    health["status"] = "UNHEALTHY"

    result = operator_status.build_operator_status(
        health_report=health,
        performance_report=(performance_report()),
    )

    assert result["status"] == "BLOCKED"

    assert result["safe_to_continue_paper_observation"] is False

    assert result["blocking_issues"]


def test_broker_orders_block_observation():
    result = operator_status.build_operator_status(
        health_report=healthy_report(),
        performance_report=(
            performance_report(
                broker_orders_sent=1,
            )
        ),
    )

    assert result["status"] == "BLOCKED"
    assert result["broker_orders_sent"] == 1

    assert result["safe_to_continue_paper_observation"] is False


def test_duplicate_completed_dates_block_observation():
    result = operator_status.build_operator_status(
        health_report=healthy_report(),
        performance_report=(
            performance_report(
                duplicate_dates=["2026-07-17"],
            )
        ),
    )

    assert result["status"] == "BLOCKED"

    assert any("Duplicate" in issue for issue in result["blocking_issues"])


def test_sufficient_data_requires_review_not_live_trading():
    result = operator_status.build_operator_status(
        health_report=healthy_report(),
        performance_report=(
            performance_report(
                status="SUFFICIENT_DATA",
                completed_sessions=20,
                positions_closed=10,
                actionable_signals=12,
            )
        ),
    )

    assert result["status"] == ("EVIDENCE_REVIEW_REQUIRED")

    assert result["safe_to_continue_paper_observation"] is True

    assert result["safe_for_live_trading"] is False


def test_failed_sessions_create_warning():
    result = operator_status.build_operator_status(
        health_report=healthy_report(),
        performance_report=(
            performance_report(
                failed_sessions=2,
            )
        ),
    )

    assert any("2 failed" in warning for warning in result["warnings"])


def test_report_is_json_serializable():
    result = operator_status.build_operator_status(
        health_report=healthy_report(),
        performance_report=(performance_report()),
    )

    encoded = json.dumps(
        result,
        sort_keys=True,
    )

    assert "OBSERVING" in encoded
    assert "PROHIBITED_BY_REPORT" in encoded
