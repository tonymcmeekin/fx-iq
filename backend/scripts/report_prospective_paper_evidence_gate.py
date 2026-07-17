import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]

if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND_DIRECTORY),
    )

from scripts.report_prospective_paper_operator_status import (  # noqa: E402
    build_operator_status,
)
from scripts.report_prospective_paper_performance import (  # noqa: E402
    DEFAULT_LEDGER_PATH,
    DEFAULT_STATE_PATH,
)
from scripts.report_prospective_paper_rolling_analytics import (  # noqa: E402
    build_rolling_analytics_report,
)

DEFAULT_PROTOCOL_PATH = (
    BACKEND_DIRECTORY / "research_protocols" / "prospective_paper_trading_protocol.json"
)


class EvidenceGateError(RuntimeError):
    """Raised when the prospective evidence gate cannot be evaluated safely."""


def load_protocol(
    protocol_path: Path,
) -> dict[str, Any]:
    try:
        payload = json.loads(
            protocol_path.read_text(
                encoding="utf-8",
            )
        )
    except FileNotFoundError as error:
        raise EvidenceGateError(f"Protocol file does not exist: {protocol_path}") from error
    except json.JSONDecodeError as error:
        raise EvidenceGateError(f"Protocol file is not valid JSON: {protocol_path}") from error

    if not isinstance(
        payload,
        dict,
    ):
        raise EvidenceGateError("Protocol root must be a JSON object.")

    return payload


def parse_iso_date(
    value: Any,
    *,
    field_name: str,
) -> date:
    if not isinstance(
        value,
        str,
    ):
        raise EvidenceGateError(f"{field_name} must be an ISO date string.")

    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise EvidenceGateError(f"{field_name} is not a valid ISO date.") from error


def numeric_value(
    value: Any,
) -> float | None:
    if isinstance(
        value,
        bool,
    ):
        return None

    if isinstance(
        value,
        int | float,
    ):
        return float(value)

    return None


def positive_market_count(
    per_market: Any,
) -> tuple[int, int]:
    if not isinstance(
        per_market,
        dict,
    ):
        return 0, 0

    available_markets = 0
    positive_markets = 0

    for market_report in per_market.values():
        if not isinstance(
            market_report,
            dict,
        ):
            continue

        pnl_available = market_report.get("candidate_net_pnl_available")

        pnl = numeric_value(market_report.get("candidate_net_pnl"))

        if pnl_available is not True or pnl is None:
            continue

        available_markets += 1

        if pnl > 0:
            positive_markets += 1

    return positive_markets, available_markets


def build_evidence_gate_report(
    *,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    protocol_path: Path = DEFAULT_PROTOCOL_PATH,
    assessment_date: date | None = None,
    protocol: dict[str, Any] | None = None,
    operator_report: dict[str, Any] | None = None,
    rolling_analytics_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_protocol = protocol if protocol is not None else load_protocol(protocol_path)

    resolved_operator = (
        operator_report
        if operator_report is not None
        else build_operator_status(
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

    prospective_period = resolved_protocol.get("prospective_period")

    pass_criteria = resolved_protocol.get("paper_test_pass_criteria")

    if not isinstance(
        prospective_period,
        dict,
    ):
        raise EvidenceGateError("Protocol prospective_period is missing.")

    if not isinstance(
        pass_criteria,
        dict,
    ):
        raise EvidenceGateError("Protocol paper_test_pass_criteria is missing.")

    current_date = assessment_date or datetime.now(UTC).date()

    first_eligible_date = parse_iso_date(
        prospective_period.get("first_eligible_market_date"),
        field_name="first_eligible_market_date",
    )

    earliest_assessment_date = parse_iso_date(
        prospective_period.get("earliest_eligible_assessment_date"),
        field_name="earliest_eligible_assessment_date",
    )

    minimum_calendar_days = int(
        prospective_period.get(
            "minimum_calendar_days",
            0,
        )
    )

    minimum_closed_trades = int(
        prospective_period.get(
            "minimum_closed_trades",
            0,
        )
    )

    elapsed_calendar_days = max(
        (current_date - first_eligible_date).days,
        0,
    )

    completed_sessions = int(
        resolved_operator.get(
            "completed_sessions",
            0,
        )
    )

    positions_closed = int(
        resolved_operator.get(
            "positions_closed",
            0,
        )
    )

    candidate_return = numeric_value(resolved_operator.get("candidate_return_percent"))

    shadow_return = numeric_value(resolved_operator.get("shadow_return_percent"))

    candidate_drawdown = numeric_value(resolved_operator.get("candidate_max_drawdown_percent"))

    candidate_profit_factor = numeric_value(resolved_operator.get("candidate_profit_factor"))

    maximum_drawdown_allowed = float(
        pass_criteria.get(
            "candidate_maximum_drawdown_percent_at_most",
            0.0,
        )
    )

    minimum_profit_factor = float(
        pass_criteria.get(
            "candidate_profit_factor_greater_than",
            0.0,
        )
    )

    minimum_positive_markets = int(
        pass_criteria.get(
            "markets_with_positive_net_pnl_at_least",
            0,
        )
    )

    markets_total_required = int(
        pass_criteria.get(
            "markets_total",
            0,
        )
    )

    positive_markets, markets_with_pnl = positive_market_count(resolved_rolling.get("per_market"))

    calendar_days_gate = (
        elapsed_calendar_days >= minimum_calendar_days and current_date >= earliest_assessment_date
    )

    closed_trades_gate = positions_closed >= minimum_closed_trades

    sample_size_gate = calendar_days_gate and closed_trades_gate

    candidate_return_gate = candidate_return > 0.0 if candidate_return is not None else None

    return_exceeds_shadow_gate = (
        candidate_return > shadow_return
        if (candidate_return is not None and shadow_return is not None)
        else None
    )

    drawdown_gate = (
        candidate_drawdown <= maximum_drawdown_allowed if candidate_drawdown is not None else None
    )

    profit_factor_gate = (
        candidate_profit_factor > minimum_profit_factor
        if candidate_profit_factor is not None
        else None
    )

    positive_markets_gate = (
        positive_markets >= minimum_positive_markets
        if markets_with_pnl == markets_total_required
        else None
    )

    trade_count_matches_shadow_gate = None
    trade_sequence_matches_shadow_gate = None

    broker_orders_sent = int(
        resolved_operator.get(
            "broker_orders_sent",
            0,
        )
    )

    runtime_integrity_gate = (
        resolved_operator.get("runtime_health") == "HEALTHY"
        and not resolved_operator.get(
            "blocking_issues",
            [],
        )
        and broker_orders_sent == 0
    )

    immediate_stop_reasons: list[str] = []

    if broker_orders_sent != 0:
        immediate_stop_reasons.append("Broker-order activity was recorded.")

    if resolved_operator.get("runtime_health") != "HEALTHY":
        immediate_stop_reasons.append("Prospective runtime health is not HEALTHY.")

    if resolved_operator.get("blocking_issues"):
        immediate_stop_reasons.extend(str(issue) for issue in resolved_operator["blocking_issues"])

    if candidate_drawdown is not None and candidate_drawdown >= maximum_drawdown_allowed:
        immediate_stop_reasons.append(
            "Candidate drawdown has reached the protocol immediate-stop threshold."
        )

    required_gates = {
        "sample_size_gate": sample_size_gate,
        "candidate_return_gate": (candidate_return_gate),
        "return_exceeds_shadow_gate": (return_exceeds_shadow_gate),
        "drawdown_gate": drawdown_gate,
        "profit_factor_gate": (profit_factor_gate),
        "positive_markets_gate": (positive_markets_gate),
        "trade_count_matches_shadow_gate": (trade_count_matches_shadow_gate),
        "trade_sequence_matches_shadow_gate": (trade_sequence_matches_shadow_gate),
        "runtime_integrity_gate": (runtime_integrity_gate),
    }

    evaluable_required_gates = [value for value in required_gates.values() if value is not None]

    unevaluable_criteria = [name for name, value in required_gates.items() if value is None]

    failed_criteria = [name for name, value in required_gates.items() if value is False]

    if immediate_stop_reasons:
        evidence_gate_status = "BLOCKED"
    elif not sample_size_gate:
        evidence_gate_status = "NOT_READY"
    elif failed_criteria:
        evidence_gate_status = "CRITERIA_FAILED"
    elif unevaluable_criteria:
        evidence_gate_status = "MANUAL_REVIEW_REQUIRED"
    elif all(evaluable_required_gates):
        evidence_gate_status = "EVIDENCE_REVIEW_REQUIRED"
    else:
        evidence_gate_status = "NOT_READY"

    protocol_test_passed = evidence_gate_status == "EVIDENCE_REVIEW_REQUIRED"

    return {
        "evidence_gate_status": (evidence_gate_status),
        "protocol_name": resolved_protocol.get("protocol_name"),
        "protocol_version": resolved_protocol.get("protocol_version"),
        "protocol_mode": resolved_protocol.get("mode"),
        "assessment_date": (current_date.isoformat()),
        "first_eligible_market_date": (first_eligible_date.isoformat()),
        "earliest_eligible_assessment_date": (earliest_assessment_date.isoformat()),
        "elapsed_calendar_days": (elapsed_calendar_days),
        "minimum_calendar_days_required": (minimum_calendar_days),
        "completed_sessions": (completed_sessions),
        "positions_closed": (positions_closed),
        "minimum_closed_trades_required": (minimum_closed_trades),
        "calendar_days_gate": (calendar_days_gate),
        "closed_trades_gate": (closed_trades_gate),
        "sample_size_gate": (sample_size_gate),
        "candidate_return_percent": (candidate_return),
        "shadow_return_percent": (shadow_return),
        "candidate_return_gate": (candidate_return_gate),
        "return_exceeds_shadow_gate": (return_exceeds_shadow_gate),
        "candidate_max_drawdown_percent": (candidate_drawdown),
        "maximum_drawdown_allowed_percent": (maximum_drawdown_allowed),
        "drawdown_gate": (drawdown_gate),
        "candidate_profit_factor": (candidate_profit_factor),
        "minimum_profit_factor_exclusive": (minimum_profit_factor),
        "profit_factor_gate": (profit_factor_gate),
        "positive_candidate_markets": (positive_markets),
        "markets_with_pnl_available": (markets_with_pnl),
        "minimum_positive_markets_required": (minimum_positive_markets),
        "markets_total_required": (markets_total_required),
        "positive_markets_gate": (positive_markets_gate),
        "trade_count_matches_shadow_gate": (trade_count_matches_shadow_gate),
        "trade_sequence_matches_shadow_gate": (trade_sequence_matches_shadow_gate),
        "runtime_integrity_gate": (runtime_integrity_gate),
        "required_gates": required_gates,
        "failed_criteria": failed_criteria,
        "unevaluable_criteria": (unevaluable_criteria),
        "immediate_stop_reasons": (immediate_stop_reasons),
        "manual_review_required": True,
        "protocol_test_passed": (protocol_test_passed),
        "safe_for_live_trading": False,
        "live_trading_permitted": False,
        "live_trading_decision": ("PROHIBITED_BY_PROTOCOL"),
        "broker_orders_sent": (broker_orders_sent),
        "network_calls_made": 0,
        "files_changed": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Evaluate prospective paper evidence against the frozen protocol.")
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

    parser.add_argument(
        "--protocol-path",
        type=Path,
        default=DEFAULT_PROTOCOL_PATH,
    )

    return parser


def main() -> int:
    arguments = build_parser().parse_args()

    try:
        report = build_evidence_gate_report(
            ledger_path=arguments.ledger_path,
            state_path=arguments.state_path,
            protocol_path=arguments.protocol_path,
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "evidence_gate_status": "ERROR",
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "safe_for_live_trading": False,
                    "live_trading_permitted": False,
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

    return 1 if report["evidence_gate_status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
