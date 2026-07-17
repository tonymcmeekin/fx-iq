"""Deterministic performance attribution for completed simulated trades."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite
from typing import Any, Literal

AttributionDimension = Literal[
    "strategy",
    "symbol",
    "direction",
    "exit_reason",
]

SUPPORTED_DIMENSIONS: tuple[AttributionDimension, ...] = (
    "strategy",
    "symbol",
    "direction",
    "exit_reason",
)


class StrategyAttributionError(ValueError):
    """Raised when attribution input is incomplete or invalid."""


@dataclass(frozen=True, slots=True)
class AttributionTrade:
    """Minimal immutable representation of one completed trade."""

    strategy: str
    symbol: str
    direction: str
    exit_reason: str
    profit_percent: float
    candles_held: int


def _require_label(
    value: Any,
    *,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StrategyAttributionError(f"Trade field {field!r} must be a non-empty string.")

    return value.strip()


def _require_profit_percent(
    value: Any,
) -> float:
    if isinstance(value, bool) or not isinstance(
        value,
        int | float,
    ):
        raise StrategyAttributionError("Trade profit_percent must be numeric.")

    resolved = float(value)

    if not isfinite(resolved):
        raise StrategyAttributionError("Trade profit_percent must be finite.")

    return resolved


def _require_candles_held(
    value: Any,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StrategyAttributionError("Trade candles_held must be a non-negative integer.")

    return value


def build_attribution_trade(
    *,
    strategy: str,
    symbol: str,
    direction: str,
    exit_reason: str,
    profit_percent: int | float,
    candles_held: int,
) -> AttributionTrade:
    """Build and validate one immutable attribution trade."""
    return AttributionTrade(
        strategy=_require_label(
            strategy,
            field="strategy",
        ),
        symbol=_require_label(
            symbol,
            field="symbol",
        ),
        direction=_require_label(
            direction,
            field="direction",
        ).upper(),
        exit_reason=_require_label(
            exit_reason,
            field="exit_reason",
        ),
        profit_percent=_require_profit_percent(
            profit_percent,
        ),
        candles_held=_require_candles_held(
            candles_held,
        ),
    )


def attribution_trade_from_mapping(
    record: dict[str, Any],
) -> AttributionTrade:
    """Build an attribution trade from a dictionary-like trade record."""
    if not isinstance(record, dict):
        raise StrategyAttributionError("Trade record must be a dictionary.")

    return build_attribution_trade(
        strategy=record.get("strategy"),
        symbol=record.get("symbol"),
        direction=record.get("direction"),
        exit_reason=record.get("exit_reason"),
        profit_percent=record.get("profit_percent"),
        candles_held=record.get("candles_held"),
    )


def _rounded(
    value: float,
) -> float:
    return round(
        value,
        6,
    )


def calculate_attribution_metrics(
    trades: Iterable[AttributionTrade],
) -> dict[str, int | float | None]:
    """Calculate stable metrics for one collection of completed trades."""
    resolved = list(
        trades,
    )

    for trade in resolved:
        if not isinstance(
            trade,
            AttributionTrade,
        ):
            raise StrategyAttributionError(
                "Attribution metrics require AttributionTrade instances."
            )

    total_trades = len(
        resolved,
    )

    winners = [trade for trade in resolved if trade.profit_percent > 0]
    losers = [trade for trade in resolved if trade.profit_percent < 0]
    breakeven = [trade for trade in resolved if trade.profit_percent == 0]

    gross_profit = sum(trade.profit_percent for trade in winners)
    gross_loss = abs(sum(trade.profit_percent for trade in losers))
    net_profit = sum(trade.profit_percent for trade in resolved)

    profit_factor: float | None

    if gross_loss > 0:
        profit_factor = _rounded(
            gross_profit / gross_loss,
        )
    else:
        profit_factor = None

    average_win = (
        _rounded(
            gross_profit / len(winners),
        )
        if winners
        else None
    )

    average_loss = (
        _rounded(
            -gross_loss / len(losers),
        )
        if losers
        else None
    )

    expectancy = (
        _rounded(
            net_profit / total_trades,
        )
        if total_trades
        else None
    )

    average_candles_held = (
        _rounded(
            sum(trade.candles_held for trade in resolved) / total_trades,
        )
        if total_trades
        else None
    )

    largest_winner = _rounded(max(trade.profit_percent for trade in winners)) if winners else None

    largest_loser = _rounded(min(trade.profit_percent for trade in losers)) if losers else None

    return {
        "total_trades": total_trades,
        "winning_trades": len(winners),
        "losing_trades": len(losers),
        "breakeven_trades": len(breakeven),
        "win_rate_percent": (_rounded(len(winners) / total_trades * 100) if total_trades else None),
        "gross_profit_percent": _rounded(
            gross_profit,
        ),
        "gross_loss_percent": _rounded(
            gross_loss,
        ),
        "net_profit_percent": _rounded(
            net_profit,
        ),
        "average_win_percent": average_win,
        "average_loss_percent": average_loss,
        "expectancy_percent": expectancy,
        "profit_factor": profit_factor,
        "largest_winner_percent": largest_winner,
        "largest_loser_percent": largest_loser,
        "average_candles_held": average_candles_held,
    }


def attribute_by_dimension(
    trades: Iterable[AttributionTrade],
    *,
    dimension: AttributionDimension,
) -> list[dict[str, Any]]:
    """Group trades by one supported dimension with stable ordering."""
    if dimension not in SUPPORTED_DIMENSIONS:
        raise StrategyAttributionError(f"Unsupported attribution dimension: {dimension!r}.")

    resolved = list(
        trades,
    )

    grouped: dict[str, list[AttributionTrade]] = {}

    for trade in resolved:
        if not isinstance(
            trade,
            AttributionTrade,
        ):
            raise StrategyAttributionError("Attribution requires AttributionTrade instances.")

        key = getattr(
            trade,
            dimension,
        )

        grouped.setdefault(
            key,
            [],
        ).append(
            trade,
        )

    return [
        {
            dimension: key,
            **calculate_attribution_metrics(
                grouped[key],
            ),
        }
        for key in sorted(
            grouped,
        )
    ]


def build_strategy_attribution_report(
    trades: Iterable[AttributionTrade],
) -> dict[str, Any]:
    """Build a complete deterministic attribution report."""
    resolved = list(
        trades,
    )

    return {
        "schema_version": 1,
        "completed_trade_count": len(resolved),
        "overall": calculate_attribution_metrics(
            resolved,
        ),
        "by_strategy": attribute_by_dimension(
            resolved,
            dimension="strategy",
        ),
        "by_symbol": attribute_by_dimension(
            resolved,
            dimension="symbol",
        ),
        "by_direction": attribute_by_dimension(
            resolved,
            dimension="direction",
        ),
        "by_exit_reason": attribute_by_dimension(
            resolved,
            dimension="exit_reason",
        ),
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
    }
