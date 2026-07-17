import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]

if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND_DIRECTORY),
    )

from app.paper_trading.ledger import verify_ledger  # noqa: E402
from app.paper_trading.runtime_state import (  # noqa: E402
    read_runtime_state,
    verify_runtime_state,
)

DEFAULT_LEDGER_PATH = BACKEND_DIRECTORY / "paper_ledger" / "events.jsonl"

DEFAULT_STATE_PATH = BACKEND_DIRECTORY / "paper_ledger" / "state.json"

MINIMUM_COMPLETED_SESSIONS = 20
MINIMUM_CLOSED_POSITIONS = 10


class PerformanceReportError(RuntimeError):
    """Raised when a prospective performance report is invalid."""


def percentage_return(
    current: float,
    initial: float,
) -> float:
    if initial <= 0:
        raise PerformanceReportError("Initial balance must be greater than zero.")

    return round(
        ((current / initial) - 1.0) * 100.0,
        6,
    )


def numeric_payload_value(
    payload: dict[str, Any],
    names: tuple[str, ...],
) -> float | None:
    for name in names:
        value = payload.get(name)

        if isinstance(value, int | float):
            return float(value)

    return None


def session_date_from_event(
    event: dict[str, Any],
) -> str | None:
    payload = event.get("payload", {})

    value = payload.get("session_date")

    if isinstance(value, str):
        return value

    return None


def build_performance_report(
    *,
    ledger_path: Path,
    state_path: Path,
) -> dict[str, Any]:
    events = verify_ledger(ledger_path)

    state = verify_runtime_state(read_runtime_state(state_path))

    event_counts = Counter(event["event_type"] for event in events)

    completed_events = [event for event in events if event["event_type"] == "SESSION_COMPLETED"]

    failed_events = [event for event in events if event["event_type"] == "SESSION_FAILED"]

    signal_events = [event for event in events if event["event_type"] == "SIGNAL_EVALUATED"]

    risk_events = [event for event in events if event["event_type"] == "RISK_DECIDED"]

    opened_events = [event for event in events if event["event_type"] == "PAPER_POSITION_OPENED"]

    marked_events = [event for event in events if event["event_type"] == "PAPER_POSITION_MARKED"]

    closed_events = [event for event in events if event["event_type"] == "PAPER_POSITION_CLOSED"]

    directions = Counter()

    for event in signal_events:
        direction = event["payload"].get("direction")

        if isinstance(direction, str):
            directions[direction.upper()] += 1

    markets = sorted(
        {
            market
            for event in events
            for market in [event["payload"].get("market")]
            if isinstance(market, str)
        }
    )

    completed_session_dates = [
        session_date
        for event in completed_events
        for session_date in [session_date_from_event(event)]
        if session_date is not None
    ]

    duplicate_completed_dates = sorted(
        date for date, count in Counter(completed_session_dates).items() if count > 1
    )

    candidate_realized_values = []
    shadow_realized_values = []

    for event in closed_events:
        payload = event["payload"]

        candidate_value = numeric_payload_value(
            payload,
            (
                "candidate_realized_pnl",
                "candidate_pnl",
                "candidate_profit",
                "candidate_profit_amount",
            ),
        )

        shadow_value = numeric_payload_value(
            payload,
            (
                "shadow_realized_pnl",
                "shadow_pnl",
                "shadow_profit",
                "shadow_profit_amount",
            ),
        )

        if candidate_value is not None:
            candidate_realized_values.append(candidate_value)

        if shadow_value is not None:
            shadow_realized_values.append(shadow_value)

    initial_candidate_balance = 10000.0
    initial_shadow_balance = 10000.0

    candidate_balance = float(state["candidate_balance"])

    shadow_balance = float(state["shadow_balance"])

    completed_sessions = len(completed_events)

    positions_closed = len(closed_events)

    sufficient_data = (
        completed_sessions >= MINIMUM_COMPLETED_SESSIONS
        and positions_closed >= MINIMUM_CLOSED_POSITIONS
    )

    broker_orders_from_events = sum(
        int(
            event["payload"].get(
                "broker_orders_sent",
                event["payload"].get(
                    "broker_orders_submitted",
                    0,
                ),
            )
        )
        for event in events
        if isinstance(
            event.get("payload"),
            dict,
        )
    )

    broker_orders_sent = max(
        int(state["broker_orders_sent"]),
        broker_orders_from_events,
    )

    if broker_orders_sent != 0:
        raise PerformanceReportError("Prospective performance data records broker orders.")

    report = {
        "status": ("SUFFICIENT_DATA" if sufficient_data else "INSUFFICIENT_DATA"),
        "ledger_events": len(events),
        "first_sequence": (events[0]["sequence"] if events else None),
        "last_sequence": (events[-1]["sequence"] if events else None),
        "last_event_type": (events[-1]["event_type"] if events else None),
        "completed_sessions": (completed_sessions),
        "failed_sessions": len(failed_events),
        "completed_session_dates": (completed_session_dates),
        "duplicate_completed_session_dates": (duplicate_completed_dates),
        "markets_observed": len(markets),
        "markets": markets,
        "signals_evaluated": len(signal_events),
        "hold_signals": directions["HOLD"],
        "buy_signals": directions["BUY"],
        "sell_signals": directions["SELL"],
        "actionable_signals": (directions["BUY"] + directions["SELL"]),
        "risk_decisions": len(risk_events),
        "positions_opened": len(opened_events),
        "position_marks": len(marked_events),
        "positions_closed": (positions_closed),
        "open_positions": len(state["open_positions"]),
        "pending_entries": len(state["pending_entries"]),
        "initial_candidate_balance": (initial_candidate_balance),
        "candidate_balance": (candidate_balance),
        "candidate_return_percent": (
            percentage_return(
                candidate_balance,
                initial_candidate_balance,
            )
        ),
        "candidate_peak_equity": float(state["candidate_peak_equity"]),
        "initial_shadow_balance": (initial_shadow_balance),
        "shadow_balance": (shadow_balance),
        "shadow_return_percent": (
            percentage_return(
                shadow_balance,
                initial_shadow_balance,
            )
        ),
        "shadow_peak_equity": float(state["shadow_peak_equity"]),
        "candidate_realized_pnl_available": (
            len(candidate_realized_values) == positions_closed and positions_closed > 0
        ),
        "candidate_realized_pnl": (
            round(
                sum(candidate_realized_values),
                6,
            )
            if candidate_realized_values
            else None
        ),
        "shadow_realized_pnl_available": (
            len(shadow_realized_values) == positions_closed and positions_closed > 0
        ),
        "shadow_realized_pnl": (
            round(
                sum(shadow_realized_values),
                6,
            )
            if shadow_realized_values
            else None
        ),
        "last_completed_session_date": (state["last_completed_session_date"]),
        "processed_markets": len(state["processed_candle_timestamps"]),
        "minimum_completed_sessions_required": (MINIMUM_COMPLETED_SESSIONS),
        "minimum_closed_positions_required": (MINIMUM_CLOSED_POSITIONS),
        "broker_orders_sent": 0,
        "network_calls_made": 0,
        "files_changed": 0,
        "event_counts": dict(sorted(event_counts.items())),
    }

    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Produce a read-only prospective paper performance report.")
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
    parser = build_parser()
    arguments = parser.parse_args()

    try:
        report = build_performance_report(
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
