from datetime import UTC, datetime, timedelta

import pytest

from app.backtesting.engine import run_strategy_backtest
from app.market_data.models import Candle
from app.trading.simulator import simulate_multi_candle_trade


def make_trending_candles() -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]

    return [
        Candle(
            symbol="EUR_USD",
            timeframe="D",
            timestamp=start + timedelta(days=index),
            open=close,
            high=close * 1.001,
            low=close * 0.999,
            close=close,
            volume=1000,
        )
        for index, close in enumerate(closes)
    ]


def test_backtest_uses_fixed_risk_position_sizing():
    result = run_strategy_backtest(
        strategy_name="simple_trend",
        candles=make_trending_candles(),
        stop_loss_percent=1.0,
        take_profit_percent=2.0,
        initial_balance=10000.0,
        risk_per_trade_percent=0.5,
        max_leverage=100.0,
    )

    trade = result.trades[0]

    assert trade.account_balance_before == 10000.0
    assert trade.risk_amount == 50.0
    assert trade.position_size_units is not None
    assert trade.notional_value is not None
    assert trade.leverage_used is not None
    assert trade.position_limited_by_leverage is False


def test_position_size_is_limited_by_maximum_leverage():
    result = run_strategy_backtest(
        strategy_name="simple_trend",
        candles=make_trending_candles(),
        stop_loss_percent=0.1,
        take_profit_percent=2.0,
        initial_balance=10000.0,
        risk_per_trade_percent=5.0,
        max_leverage=2.0,
    )

    trade = result.trades[0]

    assert trade.position_limited_by_leverage is True
    assert trade.notional_value <= 20000.01
    assert trade.leverage_used <= 2.0001


def test_slippage_is_deducted_from_profit():
    without_slippage = simulate_multi_candle_trade(
        candles=make_trending_candles()[:2],
        direction="BUY",
        stop_loss_percent=10.0,
        take_profit_percent=10.0,
        spread_pips=1.0,
        slippage_pips=0.0,
    )

    with_slippage = simulate_multi_candle_trade(
        candles=make_trending_candles()[:2],
        direction="BUY",
        stop_loss_percent=10.0,
        take_profit_percent=10.0,
        spread_pips=1.0,
        slippage_pips=1.0,
    )

    assert (
        with_slippage.trading_cost_percent
        > without_slippage.trading_cost_percent
    )
    assert (
        with_slippage.profit_percent
        < without_slippage.profit_percent
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "initial_balance",
            0.0,
            "Initial balance must be greater than zero.",
        ),
        (
            "risk_per_trade_percent",
            0.0,
            "Risk per trade percent must be greater than zero.",
        ),
        (
            "max_leverage",
            0.0,
            "Maximum leverage must be greater than zero.",
        ),
        (
            "slippage_pips",
            -1.0,
            "Slippage pips cannot be negative.",
        ),
    ],
)
def test_invalid_money_management_settings_are_rejected(
    field,
    value,
    message,
):
    arguments = {
        "strategy_name": "simple_trend",
        "candles": make_trending_candles(),
    }
    arguments[field] = value

    with pytest.raises(ValueError, match=message):
        run_strategy_backtest(**arguments)
