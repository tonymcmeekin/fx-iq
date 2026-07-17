from datetime import date

from scripts import (
    report_prospective_paper_evidence_gate as evidence_gate,
)


def protocol() -> dict:
    return {
        "protocol_name": "Test protocol",
        "protocol_version": "1.0",
        "mode": "SIMULATION_ONLY",
        "prospective_period": {
            "first_eligible_market_date": ("2026-07-14"),
            "minimum_calendar_days": 365,
            "minimum_closed_trades": 50,
            "earliest_eligible_assessment_date": ("2027-07-14"),
        },
        "paper_test_pass_criteria": {
            "candidate_maximum_drawdown_percent_at_most": 8.0,
            "candidate_profit_factor_greater_than": 1.0,
            "markets_with_positive_net_pnl_at_least": 3,
            "markets_total": 6,
        },
    }


def operator_report(
    *,
    positions_closed: int = 0,
    candidate_return: float = 0.0,
    shadow_return: float = 0.0,
    drawdown: float = 0.0,
    profit_factor=None,
    broker_orders: int = 0,
    runtime_health: str = "HEALTHY",
    blocking_issues=None,
) -> dict:
    return {
        "runtime_health": runtime_health,
        "blocking_issues": (blocking_issues or []),
        "broker_orders_sent": broker_orders,
        "completed_sessions": 1,
        "positions_closed": positions_closed,
        "candidate_return_percent": (candidate_return),
        "shadow_return_percent": (shadow_return),
        "candidate_max_drawdown_percent": (drawdown),
        "candidate_profit_factor": (profit_factor),
    }


def rolling_report(
    *,
    positive_markets: int = 0,
    pnl_available: bool = False,
) -> dict:
    markets = {}

    for index in range(6):
        is_positive = index < positive_markets

        markets[f"MARKET_{index}"] = {
            "candidate_net_pnl_available": (pnl_available),
            "candidate_net_pnl": (10.0 if is_positive else -5.0),
        }

    return {
        "per_market": markets,
    }


def test_current_real_stage_is_not_ready():
    result = evidence_gate.build_evidence_gate_report(
        protocol=protocol(),
        operator_report=operator_report(),
        rolling_analytics_report=(rolling_report()),
        assessment_date=date(
            2026,
            7,
            17,
        ),
    )

    assert result["evidence_gate_status"] == "NOT_READY"

    assert result["sample_size_gate"] is False

    assert result["minimum_closed_trades_required"] == 50

    assert result["earliest_eligible_assessment_date"] == "2027-07-14"

    assert result["live_trading_permitted"] is False


def test_sample_requires_time_and_trades():
    result = evidence_gate.build_evidence_gate_report(
        protocol=protocol(),
        operator_report=operator_report(
            positions_closed=50,
        ),
        rolling_analytics_report=(rolling_report()),
        assessment_date=date(
            2026,
            12,
            31,
        ),
    )

    assert result["closed_trades_gate"] is True

    assert result["calendar_days_gate"] is False

    assert result["sample_size_gate"] is False


def test_ready_sample_with_failed_return_fails():
    result = evidence_gate.build_evidence_gate_report(
        protocol=protocol(),
        operator_report=operator_report(
            positions_closed=50,
            candidate_return=-1.0,
            shadow_return=-2.0,
            drawdown=4.0,
            profit_factor=1.2,
        ),
        rolling_analytics_report=(
            rolling_report(
                positive_markets=4,
                pnl_available=True,
            )
        ),
        assessment_date=date(
            2027,
            7,
            14,
        ),
    )

    assert result["sample_size_gate"] is True

    assert result["candidate_return_gate"] is False

    assert result["evidence_gate_status"] == "CRITERIA_FAILED"


def test_drawdown_threshold_blocks():
    result = evidence_gate.build_evidence_gate_report(
        protocol=protocol(),
        operator_report=operator_report(
            positions_closed=50,
            candidate_return=5.0,
            shadow_return=3.0,
            drawdown=8.0,
            profit_factor=1.2,
        ),
        rolling_analytics_report=(
            rolling_report(
                positive_markets=4,
                pnl_available=True,
            )
        ),
        assessment_date=date(
            2027,
            7,
            14,
        ),
    )

    assert result["evidence_gate_status"] == "BLOCKED"

    assert result["immediate_stop_reasons"]

    assert result["safe_for_live_trading"] is False


def test_missing_trade_sequence_requires_review():
    result = evidence_gate.build_evidence_gate_report(
        protocol=protocol(),
        operator_report=operator_report(
            positions_closed=50,
            candidate_return=5.0,
            shadow_return=3.0,
            drawdown=4.0,
            profit_factor=1.2,
        ),
        rolling_analytics_report=(
            rolling_report(
                positive_markets=4,
                pnl_available=True,
            )
        ),
        assessment_date=date(
            2027,
            7,
            14,
        ),
    )

    assert result["evidence_gate_status"] == "MANUAL_REVIEW_REQUIRED"

    assert "trade_count_matches_shadow_gate" in result["unevaluable_criteria"]

    assert "trade_sequence_matches_shadow_gate" in result["unevaluable_criteria"]


def test_broker_order_activity_blocks():
    result = evidence_gate.build_evidence_gate_report(
        protocol=protocol(),
        operator_report=operator_report(
            broker_orders=1,
        ),
        rolling_analytics_report=(rolling_report()),
        assessment_date=date(
            2026,
            7,
            17,
        ),
    )

    assert result["evidence_gate_status"] == "BLOCKED"

    assert result["broker_orders_sent"] == 1

    assert result["live_trading_decision"] == "PROHIBITED_BY_PROTOCOL"


def test_positive_market_gate_needs_all_markets():
    result = evidence_gate.build_evidence_gate_report(
        protocol=protocol(),
        operator_report=operator_report(
            positions_closed=50,
            candidate_return=5.0,
            shadow_return=3.0,
            drawdown=4.0,
            profit_factor=1.2,
        ),
        rolling_analytics_report=(
            rolling_report(
                positive_markets=4,
                pnl_available=False,
            )
        ),
        assessment_date=date(
            2027,
            7,
            14,
        ),
    )

    assert result["positive_markets_gate"] is None

    assert "positive_markets_gate" in result["unevaluable_criteria"]
