"""Read-only portfolio exposure and return-correlation intelligence."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

from app.paper_trading.candle_store import read_candle_store
from app.paper_trading.runtime_state import read_runtime_state

BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]
DEFAULT_STATE_PATH = BACKEND_DIRECTORY / "paper_ledger" / "state.json"
DEFAULT_CANDLE_DIRECTORY = BACKEND_DIRECTORY / "data" / "prospective_paper"
DEFAULT_MINIMUM_ALIGNED_RETURNS = 20


class PortfolioIntelligenceError(RuntimeError):
    """Raised when verified portfolio intelligence cannot be produced."""


def _risk_percent(position: dict[str, Any], account: str) -> float:
    direct_key = f"{account}_risk_percent"
    value = position.get(direct_key)
    if value is None:
        nested = position.get(account)
        if isinstance(nested, dict):
            value = nested.get("configured_risk_percent")
    if value is None:
        raise PortfolioIntelligenceError(
            f"Position is missing {account} risk metadata."
        )
    return float(value)


def _market_currencies(market: str) -> tuple[str, str]:
    parts = market.split("_")
    if len(parts) != 2 or any(len(part) != 3 for part in parts):
        raise PortfolioIntelligenceError(
            f"Market {market!r} does not use BASE_QUOTE format."
        )
    return parts[0], parts[1]


def _position_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for position_status, positions in (
        ("PENDING", state["pending_entries"]),
        ("OPEN", state["open_positions"]),
    ):
        for market, position in sorted(positions.items()):
            direction = str(position.get("direction"))
            if direction not in {"BUY", "SELL"}:
                raise PortfolioIntelligenceError(
                    f"Position for {market} has an invalid direction."
                )
            base_currency, quote_currency = _market_currencies(market)
            rows.append(
                {
                    "market": market,
                    "position_status": position_status,
                    "direction": direction,
                    "base_currency": base_currency,
                    "quote_currency": quote_currency,
                    "candidate_risk_percent": _risk_percent(
                        position,
                        "candidate",
                    ),
                    "shadow_risk_percent": _risk_percent(
                        position,
                        "shadow",
                    ),
                    "evidence_timestamp_utc": position.get(
                        "entry_timestamp"
                    )
                    or position.get("signal_candle_timestamp"),
                }
            )
    return rows


def _currency_exposure(
    positions: list[dict[str, Any]],
    account: str,
) -> list[dict[str, Any]]:
    exposure: dict[str, float] = {}
    risk_key = f"{account}_risk_percent"
    for position in positions:
        sign = 1.0 if position["direction"] == "BUY" else -1.0
        risk = float(position[risk_key])
        base_currency = str(position["base_currency"])
        quote_currency = str(position["quote_currency"])
        exposure[base_currency] = exposure.get(base_currency, 0.0) + sign * risk
        exposure[quote_currency] = exposure.get(quote_currency, 0.0) - sign * risk

    return [
        {
            "currency": currency,
            "signed_risk_percent": round(value, 6),
            "side": "LONG" if value > 0 else "SHORT" if value < 0 else "FLAT",
            "absolute_risk_percent": round(abs(value), 6),
        }
        for currency, value in sorted(exposure.items())
    ]


def _return_series(candle_directory: Path) -> dict[str, dict[datetime, float]]:
    series = {}
    for store_path in sorted(candle_directory.glob("*.csv")):
        market = store_path.stem
        candles = read_candle_store(store_path, expected_symbol=market)
        returns = {}
        for previous, current in zip(candles, candles[1:], strict=False):
            returns[current.timestamp.astimezone(UTC)] = (
                float(current.close) / float(previous.close) - 1.0
            )
        series[market] = returns
    return series


def _pearson(left: list[float], right: list[float]) -> float | None:
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    left_delta = [value - left_mean for value in left]
    right_delta = [value - right_mean for value in right]
    denominator = math.sqrt(
        sum(value * value for value in left_delta)
        * sum(value * value for value in right_delta)
    )
    if denominator == 0:
        return None
    return sum(
        left_value * right_value
        for left_value, right_value in zip(left_delta, right_delta, strict=True)
    ) / denominator


def _correlation_rows(
    series: dict[str, dict[datetime, float]],
    *,
    minimum_aligned_returns: int,
) -> list[dict[str, Any]]:
    rows = []
    for left_market, right_market in combinations(sorted(series), 2):
        aligned = sorted(set(series[left_market]) & set(series[right_market]))
        sample_count = len(aligned)
        correlation = None
        status = "INSUFFICIENT_DATA"
        strength = "UNAVAILABLE"

        if sample_count >= minimum_aligned_returns:
            correlation = _pearson(
                [series[left_market][timestamp] for timestamp in aligned],
                [series[right_market][timestamp] for timestamp in aligned],
            )
            if correlation is not None:
                status = "AVAILABLE"
                absolute = abs(correlation)
                strength = (
                    "HIGH"
                    if absolute >= 0.8
                    else "ELEVATED"
                    if absolute >= 0.6
                    else "NORMAL"
                )

        rows.append(
            {
                "left_market": left_market,
                "right_market": right_market,
                "aligned_return_count": sample_count,
                "minimum_return_count": minimum_aligned_returns,
                "status": status,
                "correlation": (
                    None if correlation is None else round(correlation, 6)
                ),
                "absolute_correlation": (
                    None if correlation is None else round(abs(correlation), 6)
                ),
                "strength": strength,
            }
        )
    return rows


def build_portfolio_intelligence_report(
    *,
    state_path: Path = DEFAULT_STATE_PATH,
    candle_directory: Path = DEFAULT_CANDLE_DIRECTORY,
    minimum_aligned_returns: int = DEFAULT_MINIMUM_ALIGNED_RETURNS,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Build exposure and correlation views from verified paper artifacts."""
    if minimum_aligned_returns < 3:
        raise PortfolioIntelligenceError(
            "Minimum aligned returns must be at least three."
        )
    try:
        state = read_runtime_state(state_path)
        positions = _position_rows(state)
        series = _return_series(candle_directory)
        correlations = _correlation_rows(
            series,
            minimum_aligned_returns=minimum_aligned_returns,
        )
    except (OSError, RuntimeError, ValueError) as error:
        if isinstance(error, PortfolioIntelligenceError):
            raise
        raise PortfolioIntelligenceError(str(error)) from error

    resolved_now = now_utc or datetime.now(UTC)
    if resolved_now.tzinfo is None:
        raise PortfolioIntelligenceError(
            "Portfolio intelligence time must be timezone-aware."
        )

    candidate_exposure = _currency_exposure(positions, "candidate")
    shadow_exposure = _currency_exposure(positions, "shadow")
    available_pairs = [
        row for row in correlations if row["status"] == "AVAILABLE"
    ]
    high_pairs = [
        row for row in available_pairs if row["strength"] == "HIGH"
    ]
    candidate_gross_risk = sum(
        float(position["candidate_risk_percent"]) for position in positions
    )
    shadow_gross_risk = sum(
        float(position["shadow_risk_percent"]) for position in positions
    )

    return {
        "schema_version": 1,
        "status": (
            "AVAILABLE"
            if correlations and len(available_pairs) == len(correlations)
            else "INSUFFICIENT_DATA"
        ),
        "generated_at_utc": resolved_now.astimezone(UTC).isoformat(),
        "methodology": "ALIGNED_CLOSE_TO_CLOSE_PEARSON",
        "minimum_aligned_returns_required": minimum_aligned_returns,
        "market_count": len(series),
        "correlation_pair_count": len(correlations),
        "available_correlation_pair_count": len(available_pairs),
        "high_correlation_pair_count": len(high_pairs),
        "pending_entry_count": len(state["pending_entries"]),
        "open_position_count": len(state["open_positions"]),
        "candidate_gross_risk_percent": round(candidate_gross_risk, 6),
        "shadow_gross_risk_percent": round(shadow_gross_risk, 6),
        "candidate_currency_gross_exposure_percent": round(
            sum(row["absolute_risk_percent"] for row in candidate_exposure),
            6,
        ),
        "shadow_currency_gross_exposure_percent": round(
            sum(row["absolute_risk_percent"] for row in shadow_exposure),
            6,
        ),
        "positions": positions,
        "candidate_currency_exposure": candidate_exposure,
        "shadow_currency_exposure": shadow_exposure,
        "correlations": correlations,
        "high_correlation_pairs": high_pairs,
        "broker_orders_sent": int(state["broker_orders_sent"]),
        "network_calls_made": 0,
        "files_changed": 0,
        "ledger_writes_performed": 0,
        "broker_orders_submitted": 0,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
    }
