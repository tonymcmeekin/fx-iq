"""Read-only performance attribution from verified paper-trading ledgers."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.analytics.strategy_attribution import (
    AttributionTrade,
    StrategyAttributionError,
    build_attribution_trade,
    build_strategy_attribution_report,
)
from app.paper_trading.ledger import verify_ledger

CLOSED_POSITION_EVENT_TYPE = "PAPER_POSITION_CLOSED"


class LedgerAttributionError(ValueError):
    """Raised when a verified close event cannot be attributed safely."""


def _require_mapping(
    value: Any,
    *,
    description: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LedgerAttributionError(f"{description} must be a dictionary.")

    return value


def _first_present(
    mapping: dict[str, Any],
    keys: tuple[str, ...],
    *,
    description: str,
) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]

    joined = ", ".join(repr(key) for key in keys)

    raise LedgerAttributionError(f"{description} is missing; expected one of: {joined}.")


def _strategy_name(
    trade: dict[str, Any],
    payload: dict[str, Any],
) -> Any:
    for mapping in (
        trade,
        payload,
    ):
        for key in (
            "strategy",
            "strategy_name",
        ):
            if key in mapping:
                return mapping[key]

    raise LedgerAttributionError("Closed candidate trade is missing strategy information.")


def _symbol(
    trade: dict[str, Any],
    payload: dict[str, Any],
) -> Any:
    for mapping in (
        trade,
        payload,
    ):
        for key in (
            "symbol",
            "market",
        ):
            if key in mapping:
                return mapping[key]

    raise LedgerAttributionError("Closed candidate trade is missing symbol or market information.")


def _profit_percent(
    trade: dict[str, Any],
) -> Any:
    return _first_present(
        trade,
        (
            "account_return_percent",
            "profit_percent",
        ),
        description=("Closed candidate trade return percentage"),
    )


def _candles_held(
    trade: dict[str, Any],
) -> Any:
    return _first_present(
        trade,
        (
            "candles_held",
            "holding_candles",
        ),
        description=("Closed candidate trade holding period"),
    )


def attribution_trade_from_close_event(
    event: dict[str, Any],
) -> AttributionTrade:
    """Convert one verified PAPER_POSITION_CLOSED event."""
    resolved_event = _require_mapping(
        event,
        description="Ledger event",
    )

    event_type = resolved_event.get(
        "event_type",
    )

    if event_type != CLOSED_POSITION_EVENT_TYPE:
        raise LedgerAttributionError("Ledger event is not a PAPER_POSITION_CLOSED event.")

    payload = _require_mapping(
        resolved_event.get("payload"),
        description="Closed-position event payload",
    )

    candidate_trade = _require_mapping(
        payload.get("candidate_trade"),
        description="Closed-position candidate_trade",
    )

    try:
        return build_attribution_trade(
            strategy=_strategy_name(
                candidate_trade,
                payload,
            ),
            symbol=_symbol(
                candidate_trade,
                payload,
            ),
            direction=_first_present(
                candidate_trade,
                ("direction",),
                description=("Closed candidate trade direction"),
            ),
            exit_reason=_first_present(
                candidate_trade,
                ("exit_reason",),
                description=("Closed candidate trade exit reason"),
            ),
            profit_percent=_profit_percent(
                candidate_trade,
            ),
            candles_held=_candles_held(
                candidate_trade,
            ),
        )
    except StrategyAttributionError as error:
        raise LedgerAttributionError(f"Invalid closed candidate trade: {error}") from error


def attribution_trades_from_verified_events(
    events: Iterable[dict[str, Any]],
) -> list[AttributionTrade]:
    """Extract supported closed candidate trades in ledger order."""
    trades: list[AttributionTrade] = []

    for event in events:
        resolved_event = _require_mapping(
            event,
            description="Ledger event",
        )

        if resolved_event.get("event_type") != CLOSED_POSITION_EVENT_TYPE:
            continue

        trades.append(
            attribution_trade_from_close_event(
                resolved_event,
            )
        )

    return trades


def build_ledger_attribution_report(
    ledger_path: str | Path,
) -> dict[str, Any]:
    """Verify a ledger and build a read-only attribution report."""
    verified_events = verify_ledger(
        Path(ledger_path),
    )

    trades = attribution_trades_from_verified_events(
        verified_events,
    )

    report = build_strategy_attribution_report(
        trades,
    )

    return {
        **report,
        "source": "verified_paper_ledger",
        "verified_ledger_event_count": len(
            verified_events,
        ),
        "supported_close_event_count": len(
            trades,
        ),
        "ledger_writes_performed": 0,
        "broker_orders_submitted": 0,
    }
