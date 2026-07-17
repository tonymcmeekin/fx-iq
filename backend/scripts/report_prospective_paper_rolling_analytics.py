import argparse
import json
import math
import sys
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
from scripts.report_prospective_paper_performance import (  # noqa: E402
    DEFAULT_LEDGER_PATH,
    DEFAULT_STATE_PATH,
    MINIMUM_CLOSED_POSITIONS,
    MINIMUM_COMPLETED_SESSIONS,
)

INITIAL_BALANCE = 10000.0


class RollingAnalyticsError(RuntimeError):
    """Raised when rolling analytics cannot be generated safely."""


def numeric_value(
    value: Any,
) -> float | None:
    if not isinstance(
        value,
        int | float,
    ):
        return None

    resolved = float(value)

    if not math.isfinite(resolved):
        return None

    return resolved


def payload_numeric_value(
    payload: dict[str, Any],
    keys: tuple[str, ...],
) -> float | None:
    for key in keys:
        value = numeric_value(payload.get(key))

        if value is not None:
            return value

    return None


def percentage_change(
    previous: float,
    current: float,
) -> float:
    if previous <= 0:
        raise RollingAnalyticsError("Previous equity must be positive.")

    return round(
        (current - previous) / previous * 100,
        10,
    )


def maximum_drawdown_percent(
    balances: list[float],
) -> float:
    if not balances:
        return 0.0

    peak = balances[0]
    maximum_drawdown = 0.0

    for balance in balances:
        if balance <= 0:
            raise RollingAnalyticsError("Equity values must remain positive.")

        peak = max(
            peak,
            balance,
        )

        drawdown = (peak - balance) / peak * 100

        maximum_drawdown = max(
            maximum_drawdown,
            drawdown,
        )

    return round(
        maximum_drawdown,
        10,
    )


def average(
    values: list[float],
) -> float | None:
    if not values:
        return None

    return round(
        sum(values) / len(values),
        10,
    )


def rolling_average(
    values: list[float],
    window: int,
) -> float | None:
    if not values:
        return None

    selected = values[-window:]

    return average(selected)


def trade_pnl(
    payload: dict[str, Any],
    *,
    account: str,
) -> float | None:
    direct_keys = (
        f"{account}_net_pnl",
        f"{account}_realized_pnl",
        f"{account}_pnl",
        f"{account}_profit",
        f"{account}_profit_amount",
    )

    direct = payload_numeric_value(
        payload,
        direct_keys,
    )

    if direct is not None:
        return direct

    trade = payload.get(f"{account}_trade")

    if not isinstance(
        trade,
        dict,
    ):
        return None

    return payload_numeric_value(
        trade,
        (
            "net_pnl",
            "realized_pnl",
            "pnl",
            "profit",
        ),
    )


def trade_return_percent(
    payload: dict[str, Any],
    *,
    account: str,
) -> float | None:
    direct = payload_numeric_value(
        payload,
        (
            f"{account}_return_percent",
            f"{account}_trade_return_percent",
        ),
    )

    if direct is not None:
        return direct

    trade = payload.get(f"{account}_trade")

    if not isinstance(
        trade,
        dict,
    ):
        return None

    return payload_numeric_value(
        trade,
        (
            "account_return_percent",
            "return_percent",
        ),
    )


def session_date(
    event: dict[str, Any],
) -> str | None:
    value = event["payload"].get("session_date")

    if isinstance(value, str) and value:
        return value

    return None


def build_session_equity_curve(
    completed_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    curve = []

    previous_candidate = INITIAL_BALANCE

    previous_shadow = INITIAL_BALANCE

    for event in completed_events:
        payload = event["payload"]

        date_value = session_date(event)

        if date_value is None:
            continue

        candidate_balance = payload_numeric_value(
            payload,
            ("candidate_balance",),
        )

        shadow_balance = payload_numeric_value(
            payload,
            ("shadow_balance",),
        )

        if candidate_balance is None:
            candidate_balance = previous_candidate

        if shadow_balance is None:
            shadow_balance = previous_shadow

        if candidate_balance <= 0 or shadow_balance <= 0:
            raise RollingAnalyticsError("Completed-session balances must remain positive.")

        curve.append(
            {
                "session_date": date_value,
                "candidate_balance": round(
                    candidate_balance,
                    10,
                ),
                "shadow_balance": round(
                    shadow_balance,
                    10,
                ),
                "candidate_session_return_percent": (
                    percentage_change(
                        previous_candidate,
                        candidate_balance,
                    )
                ),
                "shadow_session_return_percent": (
                    percentage_change(
                        previous_shadow,
                        shadow_balance,
                    )
                ),
            }
        )

        previous_candidate = candidate_balance

        previous_shadow = shadow_balance

    return curve


def empty_market_summary() -> dict[str, Any]:
    return {
        "signals": 0,
        "buy_signals": 0,
        "sell_signals": 0,
        "hold_signals": 0,
        "risk_decisions": 0,
        "positions_opened": 0,
        "position_marks": 0,
        "positions_closed": 0,
        "candidate_net_pnl": 0.0,
        "shadow_net_pnl": 0.0,
        "candidate_net_pnl_available": False,
        "shadow_net_pnl_available": False,
        "winning_trades": 0,
        "losing_trades": 0,
        "flat_trades": 0,
    }


def build_per_market_analytics(
    events: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    markets: dict[
        str,
        dict[str, Any],
    ] = {}

    for event in events:
        payload = event["payload"]

        market = payload.get("market")

        if not isinstance(market, str) or not market:
            continue

        summary = markets.setdefault(
            market,
            empty_market_summary(),
        )

        event_type = event["event_type"]

        if event_type == ("SIGNAL_EVALUATED"):
            summary["signals"] += 1

            direction = payload.get("direction")

            if isinstance(
                direction,
                str,
            ):
                key = f"{direction.lower()}_signals"

                if key in summary:
                    summary[key] += 1

        elif event_type == "RISK_DECIDED":
            summary["risk_decisions"] += 1

        elif event_type == ("PAPER_POSITION_OPENED"):
            summary["positions_opened"] += 1

        elif event_type == ("PAPER_POSITION_MARKED"):
            summary["position_marks"] += 1

        elif event_type == ("PAPER_POSITION_CLOSED"):
            summary["positions_closed"] += 1

            candidate_pnl = trade_pnl(
                payload,
                account="candidate",
            )

            shadow_pnl = trade_pnl(
                payload,
                account="shadow",
            )

            if candidate_pnl is not None:
                summary["candidate_net_pnl"] += candidate_pnl

                summary["candidate_net_pnl_available"] = True

                if candidate_pnl > 0:
                    summary["winning_trades"] += 1
                elif candidate_pnl < 0:
                    summary["losing_trades"] += 1
                else:
                    summary["flat_trades"] += 1

            if shadow_pnl is not None:
                summary["shadow_net_pnl"] += shadow_pnl

                summary["shadow_net_pnl_available"] = True

    for summary in markets.values():
        summary["candidate_net_pnl"] = round(
            summary["candidate_net_pnl"],
            10,
        )

        summary["shadow_net_pnl"] = round(
            summary["shadow_net_pnl"],
            10,
        )

    return {market: markets[market] for market in sorted(markets)}


def build_rolling_analytics_report(
    *,
    ledger_path: Path,
    state_path: Path,
) -> dict[str, Any]:
    events = verify_ledger(ledger_path)

    state = verify_runtime_state(read_runtime_state(state_path))

    broker_orders = []

    for event in events:
        payload = event["payload"]

        for key in (
            "broker_orders_sent",
            "broker_orders_submitted",
        ):
            value = payload.get(key)

            if isinstance(
                value,
                int | float,
            ):
                broker_orders.append(int(value))

    if state["broker_orders_sent"] != 0 or any(value != 0 for value in broker_orders):
        raise RollingAnalyticsError("Prospective evidence records broker orders.")

    completed_events = [event for event in events if event["event_type"] == "SESSION_COMPLETED"]

    closed_events = [event for event in events if event["event_type"] == "PAPER_POSITION_CLOSED"]

    curve = build_session_equity_curve(completed_events)

    candidate_session_returns = [point["candidate_session_return_percent"] for point in curve]

    shadow_session_returns = [point["shadow_session_return_percent"] for point in curve]

    candidate_balances = [
        INITIAL_BALANCE,
        *[point["candidate_balance"] for point in curve],
    ]

    shadow_balances = [
        INITIAL_BALANCE,
        *[point["shadow_balance"] for point in curve],
    ]

    candidate_trade_pnls = [
        value
        for event in closed_events
        for value in [
            trade_pnl(
                event["payload"],
                account="candidate",
            )
        ]
        if value is not None
    ]

    shadow_trade_pnls = [
        value
        for event in closed_events
        for value in [
            trade_pnl(
                event["payload"],
                account="shadow",
            )
        ]
        if value is not None
    ]

    candidate_trade_returns = [
        value
        for event in closed_events
        for value in [
            trade_return_percent(
                event["payload"],
                account="candidate",
            )
        ]
        if value is not None
    ]

    winning_trade_pnls = [value for value in candidate_trade_pnls if value > 0]

    losing_trade_pnls = [value for value in candidate_trade_pnls if value < 0]

    flat_trade_pnls = [value for value in candidate_trade_pnls if value == 0]

    profitable_sessions = sum(value > 0 for value in candidate_session_returns)

    losing_sessions = sum(value < 0 for value in candidate_session_returns)

    flat_sessions = sum(value == 0 for value in candidate_session_returns)

    gross_profit = sum(winning_trade_pnls)

    gross_loss = abs(sum(losing_trade_pnls))

    profit_factor = (
        round(
            gross_profit / gross_loss,
            10,
        )
        if gross_loss > 0
        else None
    )

    expectancy = average(candidate_trade_pnls)

    completed_sessions = len(completed_events)

    positions_closed = len(closed_events)

    sufficient_data = (
        completed_sessions >= MINIMUM_COMPLETED_SESSIONS
        and positions_closed >= MINIMUM_CLOSED_POSITIONS
    )

    return {
        "status": ("SUFFICIENT_DATA" if sufficient_data else "INSUFFICIENT_DATA"),
        "ledger_events": len(events),
        "completed_sessions": (completed_sessions),
        "minimum_completed_sessions_required": (MINIMUM_COMPLETED_SESSIONS),
        "positions_closed": (positions_closed),
        "minimum_closed_positions_required": (MINIMUM_CLOSED_POSITIONS),
        "session_equity_curve": curve,
        "candidate_max_drawdown_percent": (maximum_drawdown_percent(candidate_balances)),
        "shadow_max_drawdown_percent": (maximum_drawdown_percent(shadow_balances)),
        "profitable_sessions": (profitable_sessions),
        "losing_sessions": losing_sessions,
        "flat_sessions": flat_sessions,
        "average_candidate_session_return_percent": (average(candidate_session_returns)),
        "average_shadow_session_return_percent": (average(shadow_session_returns)),
        "rolling_5_session_candidate_return_percent": (
            rolling_average(
                candidate_session_returns,
                5,
            )
        ),
        "rolling_20_session_candidate_return_percent": (
            rolling_average(
                candidate_session_returns,
                20,
            )
        ),
        "candidate_winning_trades": len(winning_trade_pnls),
        "candidate_losing_trades": len(losing_trade_pnls),
        "candidate_flat_trades": len(flat_trade_pnls),
        "candidate_win_rate_percent": (
            round(
                len(winning_trade_pnls) / len(candidate_trade_pnls) * 100,
                10,
            )
            if candidate_trade_pnls
            else None
        ),
        "candidate_expectancy_amount": (expectancy),
        "candidate_average_trade_return_percent": (average(candidate_trade_returns)),
        "candidate_gross_profit": round(
            gross_profit,
            10,
        ),
        "candidate_gross_loss": round(
            gross_loss,
            10,
        ),
        "candidate_profit_factor": (profit_factor),
        "candidate_trade_pnl_available": bool(candidate_trade_pnls),
        "shadow_trade_pnl_available": bool(shadow_trade_pnls),
        "candidate_balance": state["candidate_balance"],
        "shadow_balance": state["shadow_balance"],
        "per_market": (build_per_market_analytics(events)),
        "broker_orders_sent": 0,
        "network_calls_made": 0,
        "files_changed": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Produce read-only rolling analytics for prospective paper trading.")
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
        report = build_rolling_analytics_report(
            ledger_path=(arguments.ledger_path),
            state_path=(arguments.state_path),
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "broker_orders_sent": 0,
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
