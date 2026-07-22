"""Shared read-only analytics overview reporting service."""

from __future__ import annotations

from typing import Any

from app.analytics.attribution_reporting import (
    AttributionReportError,
)
from app.analytics.attribution_reporting import (
    perform_report as perform_attribution_report,
)
from app.analytics.operator_status_reporting import (
    OperatorStatusReportError,
)
from app.analytics.operator_status_reporting import (
    perform_report as perform_operator_status_report,
)
from app.analytics.prospective_health_reporting import (
    ProspectiveHealthReportError,
)
from app.analytics.prospective_health_reporting import (
    perform_report as perform_health_report,
)


class AnalyticsOverviewError(RuntimeError):
    """Raised when a verified analytics overview cannot be produced."""


def _best_strategy(
    attribution: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the strongest strategy by net profit, when available."""
    strategies = attribution.get("by_strategy", [])

    if not isinstance(strategies, list) or not strategies:
        return None

    valid_strategies = [
        strategy
        for strategy in strategies
        if isinstance(strategy, dict)
        and isinstance(
            strategy.get("net_profit_percent"),
            int | float,
        )
    ]

    if not valid_strategies:
        return None

    best = max(
        valid_strategies,
        key=lambda strategy: strategy["net_profit_percent"],
    )

    return {
        "strategy": best.get("strategy"),
        "net_profit_percent": best.get("net_profit_percent"),
        "total_trades": best.get("total_trades"),
        "win_rate_percent": best.get("win_rate_percent"),
    }


def perform_report() -> dict[str, Any]:
    """
    Build one verified operator-facing analytics overview.

    This service performs no network calls, writes no files or ledger
    events, submits no broker orders, and cannot enable live trading.
    """
    try:
        health = perform_health_report()
        attribution = perform_attribution_report()
        operator_status = perform_operator_status_report()

        health = {
            **health,
            "safe_for_live_trading": False,
            "protocol_live_trading_permitted": False,
        }
        attribution = {
            **attribution,
            "ledger_writes_performed": 0,
            "broker_orders_submitted": 0,
            "safe_for_live_trading": False,
            "protocol_live_trading_permitted": False,
        }
        operator_status = {
            **operator_status,
            "network_calls_made": 0,
            "files_changed": 0,
            "ledger_writes_performed": 0,
            "broker_orders_submitted": 0,
            "safe_for_live_trading": False,
            "protocol_live_trading_permitted": False,
        }
    except (
        AttributionReportError,
        OperatorStatusReportError,
        ProspectiveHealthReportError,
        OSError,
    ) as error:
        raise AnalyticsOverviewError(str(error)) from error

    overall = attribution.get("overall", {})

    return {
        "schema_version": 2,
        "status": ("HEALTHY" if health.get("status") == "HEALTHY" else "UNHEALTHY"),
        "summary": {
            "candidate_balance": health.get("candidate_balance"),
            "shadow_balance": health.get("shadow_balance"),
            "open_positions": health.get("open_positions"),
            "pending_entries": health.get("pending_entries"),
            "completed_trade_count": attribution.get(
                "completed_trade_count",
                0,
            ),
            "net_profit_percent": (
                overall.get("net_profit_percent") if isinstance(overall, dict) else None
            ),
            "win_rate_percent": (
                overall.get("win_rate_percent") if isinstance(overall, dict) else None
            ),
            "best_strategy": _best_strategy(attribution),
            "last_completed_session_date": (
                health.get("last_completed_session_date") or health.get("latest_completed_session")
            ),
            "operator_status": operator_status.get("status"),
            "runtime_health": operator_status.get("runtime_health"),
            "performance_status": operator_status.get("performance_status"),
            "rolling_analytics_status": (operator_status.get("rolling_analytics_status")),
            "observation_integrity_status": (
                operator_status.get(
                    "observation_integrity_status"
                )
            ),
            "observations_recorded": operator_status.get(
                "observations_recorded"
            ),
            "observation_outcomes_populated": (
                operator_status.get(
                    "observation_outcomes_populated"
                )
            ),
            "evidence_gate_status": operator_status.get("evidence_gate_status"),
            "safe_to_continue_paper_observation": (
                operator_status.get("safe_to_continue_paper_observation")
            ),
            "earliest_eligible_assessment_date": (
                operator_status.get("earliest_eligible_assessment_date")
            ),
        },
        "runtime": health,
        "operator_status": operator_status,
        "strategy_attribution": attribution,
        "safety": {
            "paper_trading_only": True,
            "runtime_verified": (health.get("status") == "HEALTHY"),
            "ledger_verified": (attribution.get("source") == "verified_paper_ledger"),
            "network_calls_made": 0,
            "files_changed": 0,
            "ledger_writes_performed": 0,
            "broker_orders_submitted": 0,
            "safe_for_live_trading": False,
            "protocol_live_trading_permitted": False,
        },
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
    }
