"""Tests for deterministic strategy performance attribution."""

from __future__ import annotations

import pytest

from app.analytics.strategy_attribution import (
    StrategyAttributionError,
    attribute_by_dimension,
    attribution_trade_from_mapping,
    build_attribution_trade,
    build_strategy_attribution_report,
    calculate_attribution_metrics,
)


def trade(
    *,
    strategy: str = "atr_breakout",
    symbol: str = "EUR_GBP",
    direction: str = "BUY",
    exit_reason: str = "TAKE_PROFIT",
    profit_percent: float = 1.0,
    candles_held: int = 3,
):
    return build_attribution_trade(
        strategy=strategy,
        symbol=symbol,
        direction=direction,
        exit_reason=exit_reason,
        profit_percent=profit_percent,
        candles_held=candles_held,
    )


def test_builds_valid_trade():
    result = trade(
        direction="buy",
    )

    assert result.strategy == "atr_breakout"
    assert result.direction == "BUY"
    assert result.profit_percent == 1.0


def test_builds_trade_from_mapping():
    result = attribution_trade_from_mapping(
        {
            "strategy": "atr_breakout",
            "symbol": "EUR_GBP",
            "direction": "SELL",
            "exit_reason": "STOP_LOSS",
            "profit_percent": -0.5,
            "candles_held": 2,
        }
    )

    assert result.direction == "SELL"
    assert result.profit_percent == -0.5


def test_rejects_non_finite_profit():
    with pytest.raises(
        StrategyAttributionError,
        match="finite",
    ):
        trade(
            profit_percent=float("inf"),
        )


def test_rejects_negative_holding_period():
    with pytest.raises(
        StrategyAttributionError,
        match="non-negative",
    ):
        trade(
            candles_held=-1,
        )


def test_empty_metrics_are_stable():
    result = calculate_attribution_metrics(
        [],
    )

    assert result["total_trades"] == 0
    assert result["win_rate_percent"] is None
    assert result["expectancy_percent"] is None
    assert result["profit_factor"] is None
    assert result["net_profit_percent"] == 0.0


def test_calculates_winners_losers_and_breakeven():
    result = calculate_attribution_metrics(
        [
            trade(
                profit_percent=2.0,
                candles_held=2,
            ),
            trade(
                profit_percent=-1.0,
                candles_held=4,
            ),
            trade(
                profit_percent=0.0,
                candles_held=3,
            ),
        ]
    )

    assert result["total_trades"] == 3
    assert result["winning_trades"] == 1
    assert result["losing_trades"] == 1
    assert result["breakeven_trades"] == 1
    assert result["win_rate_percent"] == pytest.approx(33.333333)
    assert result["gross_profit_percent"] == 2.0
    assert result["gross_loss_percent"] == 1.0
    assert result["net_profit_percent"] == 1.0
    assert result["expectancy_percent"] == pytest.approx(0.333333)
    assert result["profit_factor"] == 2.0
    assert result["average_candles_held"] == 3.0


def test_all_winners_have_undefined_profit_factor():
    result = calculate_attribution_metrics(
        [
            trade(
                profit_percent=1.0,
            ),
            trade(
                profit_percent=2.0,
            ),
        ]
    )

    assert result["profit_factor"] is None
    assert result["average_win_percent"] == 1.5
    assert result["average_loss_percent"] is None


def test_all_losers_have_zero_profit_factor():
    result = calculate_attribution_metrics(
        [
            trade(
                profit_percent=-1.0,
            ),
            trade(
                profit_percent=-2.0,
            ),
        ]
    )

    assert result["profit_factor"] == 0.0
    assert result["average_win_percent"] is None
    assert result["average_loss_percent"] == -1.5


def test_groups_by_strategy_in_stable_order():
    result = attribute_by_dimension(
        [
            trade(
                strategy="z_strategy",
            ),
            trade(
                strategy="a_strategy",
            ),
            trade(
                strategy="z_strategy",
            ),
        ],
        dimension="strategy",
    )

    assert [row["strategy"] for row in result] == [
        "a_strategy",
        "z_strategy",
    ]

    assert result[1]["total_trades"] == 2


def test_groups_by_symbol_direction_and_exit_reason():
    trades = [
        trade(
            symbol="GBP_USD",
            direction="BUY",
            exit_reason="TAKE_PROFIT",
            profit_percent=1.0,
        ),
        trade(
            symbol="EUR_GBP",
            direction="SELL",
            exit_reason="STOP_LOSS",
            profit_percent=-0.5,
        ),
    ]

    assert (
        len(
            attribute_by_dimension(
                trades,
                dimension="symbol",
            )
        )
        == 2
    )

    assert (
        len(
            attribute_by_dimension(
                trades,
                dimension="direction",
            )
        )
        == 2
    )

    assert (
        len(
            attribute_by_dimension(
                trades,
                dimension="exit_reason",
            )
        )
        == 2
    )


def test_rejects_unsupported_dimension():
    with pytest.raises(
        StrategyAttributionError,
        match="Unsupported",
    ):
        attribute_by_dimension(
            [trade()],
            dimension="weekday",  # type: ignore[arg-type]
        )


def test_complete_report_contains_all_dimensions():
    report = build_strategy_attribution_report(
        [
            trade(
                strategy="atr_breakout",
                symbol="EUR_GBP",
                direction="BUY",
                exit_reason="TAKE_PROFIT",
                profit_percent=1.5,
            ),
            trade(
                strategy="simple_trend",
                symbol="GBP_USD",
                direction="SELL",
                exit_reason="STOP_LOSS",
                profit_percent=-0.5,
            ),
        ]
    )

    assert report["schema_version"] == 1
    assert report["completed_trade_count"] == 2
    assert report["overall"]["net_profit_percent"] == 1.0
    assert len(report["by_strategy"]) == 2
    assert len(report["by_symbol"]) == 2
    assert len(report["by_direction"]) == 2
    assert len(report["by_exit_reason"]) == 2
    assert report["safe_for_live_trading"] is False
    assert report["protocol_live_trading_permitted"] is False


def test_report_is_deterministic_for_same_trade_order():
    trades = [
        trade(
            strategy="b",
            profit_percent=-0.5,
        ),
        trade(
            strategy="a",
            profit_percent=1.0,
        ),
    ]

    first = build_strategy_attribution_report(
        trades,
    )
    second = build_strategy_attribution_report(
        trades,
    )

    assert first == second
