from datetime import UTC, datetime, timedelta

import pytest

from app.ai.regime_risk import (
    calculate_historical_regime_risk_percent,
)
from app.market_data.models import Candle
from app.portfolio.engine import run_portfolio_backtest
from app.portfolio.models import PortfolioStrategyConfig
from app.signals.models import TradeSignal
from app.strategies.manager import STRATEGIES


def make_candles(
    count: int = 60,
) -> list[Candle]:
    start = datetime(2020, 1, 1, tzinfo=UTC)

    candles = []

    for index in range(count):
        close = 100.0 + index

        candles.append(
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
        )

    return candles


def always_buy(candles):
    latest = candles[-1]

    return TradeSignal(
        symbol=latest.symbol,
        direction="BUY",
        confidence=1.0,
        strategy_name="portfolio_regime_test",
        reason="Test signal.",
    )


@pytest.fixture(autouse=True)
def temporary_strategy():
    STRATEGIES[
        "portfolio_regime_test"
    ] = always_buy

    yield

    STRATEGIES.pop(
        "portfolio_regime_test",
        None,
    )


def strategy_config():
    return PortfolioStrategyConfig(
        strategy_name="portfolio_regime_test",
        symbol="EUR_USD",
        stop_loss_percent=50.0,
        take_profit_percent=50.0,
        risk_per_trade_percent=0.5,
    )


def test_default_portfolio_risk_is_unchanged():
    result = run_portfolio_backtest(
        candles_by_symbol={
            "EUR_USD": make_candles(),
        },
        strategy_configs=[
            strategy_config(),
        ],
        initial_balance=10000.0,
        max_portfolio_leverage=100.0,
    )

    assert result.trades
    assert result.trades[0].risk_amount == 50.0


def test_risk_callback_reduces_position_risk():
    result = run_portfolio_backtest(
        candles_by_symbol={
            "EUR_USD": make_candles(),
        },
        strategy_configs=[
            strategy_config(),
        ],
        initial_balance=10000.0,
        max_portfolio_leverage=100.0,
        risk_percent_adjuster=(
            lambda config, history:
            config.risk_per_trade_percent * 0.5
        ),
    )

    assert result.trades
    assert result.trades[0].risk_amount == 25.0


def test_callback_cannot_increase_configured_risk():
    with pytest.raises(
        ValueError,
        match=(
            "Adjusted risk percent cannot exceed "
            "the configured risk per trade."
        ),
    ):
        run_portfolio_backtest(
            candles_by_symbol={
                "EUR_USD": make_candles(),
            },
            strategy_configs=[
                strategy_config(),
            ],
            risk_percent_adjuster=(
                lambda config, history:
                config.risk_per_trade_percent * 2
            ),
        )


def test_callback_rejects_zero_risk():
    with pytest.raises(
        ValueError,
        match=(
            "Adjusted risk percent must be "
            "greater than zero."
        ),
    ):
        run_portfolio_backtest(
            candles_by_symbol={
                "EUR_USD": make_candles(),
            },
            strategy_configs=[
                strategy_config(),
            ],
            risk_percent_adjuster=(
                lambda config, history: 0.0
            ),
        )


def test_callback_does_not_receive_entry_candle():
    candles = make_candles()
    observed_histories = []

    def inspect_history(config, history):
        observed_histories.append(
            {
                "last_timestamp": history[-1].timestamp,
                "count": len(history),
            }
        )

        return config.risk_per_trade_percent

    result = run_portfolio_backtest(
        candles_by_symbol={
            "EUR_USD": candles,
        },
        strategy_configs=[
            strategy_config(),
        ],
        risk_percent_adjuster=inspect_history,
    )

    assert observed_histories
    assert len(observed_histories) == len(result.trades)

    for observed, trade in zip(
        observed_histories,
        result.trades,
        strict=True,
    ):
        assert (
            observed["last_timestamp"]
            < trade.entry_timestamp
        )
        assert observed["count"] >= 1


def test_regime_helper_retains_base_risk_during_warmup():
    risk = calculate_historical_regime_risk_percent(
        base_risk_percent=0.5,
        candles=make_candles(20),
    )

    assert risk == 0.5


def test_regime_helper_never_increases_risk():
    risk = calculate_historical_regime_risk_percent(
        base_risk_percent=0.5,
        candles=make_candles(60),
    )

    assert 0 < risk <= 0.5



def test_direction_aware_callback_receives_pending_trade_direction():
    candles = make_candles()
    observed_directions = []

    def direction_aware_adjuster(
        config,
        history,
        direction,
    ):
        assert history
        observed_directions.append(direction)
        return config.risk_per_trade_percent

    result = run_portfolio_backtest(
        candles_by_symbol={
            "EUR_USD": candles,
        },
        strategy_configs=[
            strategy_config(),
        ],
        risk_percent_adjuster=direction_aware_adjuster,
    )

    assert result.trades
    assert observed_directions
    assert all(
        direction in {"BUY", "SELL"}
        for direction in observed_directions
    )
    assert (
        observed_directions[0]
        == result.trades[0].direction
    )
