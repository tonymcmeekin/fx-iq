from datetime import UTC, datetime, timedelta

import pytest

from app.market_data.models import Candle
from app.portfolio.engine import run_portfolio_backtest
from app.portfolio.models import PortfolioStrategyConfig
from app.signals.models import TradeSignal
from app.strategies.manager import STRATEGIES


def make_candles(
    symbol: str,
    closes: list[float],
) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)

    candles = []

    for index, close in enumerate(closes):
        candles.append(
            Candle(
                symbol=symbol,
                timeframe="D",
                timestamp=(
                    start + timedelta(days=index)
                ),
                open=close,
                high=close * 1.002,
                low=close * 0.998,
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
        strategy_name="always_buy",
        reason="Test signal.",
    )


def always_sell(candles):
    latest = candles[-1]

    return TradeSignal(
        symbol=latest.symbol,
        direction="SELL",
        confidence=1.0,
        strategy_name="always_sell",
        reason="Test signal.",
    )


@pytest.fixture(autouse=True)
def temporary_strategies():
    STRATEGIES["always_buy"] = always_buy
    STRATEGIES["always_sell"] = always_sell

    yield

    STRATEGIES.pop("always_buy", None)
    STRATEGIES.pop("always_sell", None)


def test_portfolio_enters_on_next_candle_open():
    candles = make_candles(
        "EUR_USD",
        [100.0, 101.0, 102.0, 103.0],
    )

    result = run_portfolio_backtest(
        candles_by_symbol={"EUR_USD": candles},
        strategy_configs=[
            PortfolioStrategyConfig(
                strategy_name="always_buy",
                symbol="EUR_USD",
                stop_loss_percent=50.0,
                take_profit_percent=50.0,
            )
        ],
    )

    trade = result.trades[0]

    assert trade.signal_timestamp == candles[0].timestamp
    assert trade.entry_timestamp == candles[1].timestamp
    assert trade.entry_price == candles[1].open


def test_portfolio_allows_overlapping_positions():
    eur = make_candles(
        "EUR_USD",
        [100.0, 101.0, 102.0, 103.0],
    )
    gbp = make_candles(
        "GBP_USD",
        [120.0, 121.0, 122.0, 123.0],
    )

    result = run_portfolio_backtest(
        candles_by_symbol={
            "EUR_USD": eur,
            "GBP_USD": gbp,
        },
        strategy_configs=[
            PortfolioStrategyConfig(
                strategy_name="always_buy",
                symbol="EUR_USD",
                stop_loss_percent=50.0,
                take_profit_percent=50.0,
                risk_per_trade_percent=0.25,
            ),
            PortfolioStrategyConfig(
                strategy_name="always_buy",
                symbol="GBP_USD",
                stop_loss_percent=50.0,
                take_profit_percent=50.0,
                risk_per_trade_percent=0.25,
            ),
        ],
        max_total_risk_percent=1.0,
    )

    assert result.maximum_open_positions == 2
    assert any(
        point.open_positions == 2
        for point in result.equity_curve
    )


def test_shared_portfolio_leverage_is_enforced():
    eur = make_candles(
        "EUR_USD",
        [100.0, 101.0, 102.0, 103.0],
    )
    gbp = make_candles(
        "GBP_USD",
        [100.0, 101.0, 102.0, 103.0],
    )

    result = run_portfolio_backtest(
        candles_by_symbol={
            "EUR_USD": eur,
            "GBP_USD": gbp,
        },
        strategy_configs=[
            PortfolioStrategyConfig(
                strategy_name="always_buy",
                symbol="EUR_USD",
                stop_loss_percent=0.1,
                take_profit_percent=50.0,
                risk_per_trade_percent=10.0,
            ),
            PortfolioStrategyConfig(
                strategy_name="always_buy",
                symbol="GBP_USD",
                stop_loss_percent=0.1,
                take_profit_percent=50.0,
                risk_per_trade_percent=10.0,
            ),
        ],
        max_portfolio_leverage=1.0,
        max_total_risk_percent=20.0,
    )

    assert result.maximum_gross_leverage <= 1.01


def test_portfolio_has_chronological_equity_curve():
    candles = make_candles(
        "EUR_USD",
        [100.0, 101.0, 95.0, 105.0, 106.0],
    )

    result = run_portfolio_backtest(
        candles_by_symbol={"EUR_USD": candles},
        strategy_configs=[
            PortfolioStrategyConfig(
                strategy_name="always_buy",
                symbol="EUR_USD",
                stop_loss_percent=50.0,
                take_profit_percent=50.0,
                risk_per_trade_percent=1.0,
            )
        ],
    )

    timestamps = [
        point.timestamp
        for point in result.equity_curve
    ]

    assert timestamps == sorted(timestamps)
    assert len(result.equity_curve) == len(candles)
    assert result.max_drawdown_percent > 0


def test_portfolio_reports_strategy_summaries():
    candles = make_candles(
        "EUR_USD",
        [100.0, 101.0, 102.0, 103.0],
    )

    result = run_portfolio_backtest(
        candles_by_symbol={"EUR_USD": candles},
        strategy_configs=[
            PortfolioStrategyConfig(
                strategy_name="always_buy",
                symbol="EUR_USD",
                stop_loss_percent=50.0,
                take_profit_percent=50.0,
            ),
            PortfolioStrategyConfig(
                strategy_name="always_sell",
                symbol="EUR_USD",
                stop_loss_percent=50.0,
                take_profit_percent=50.0,
            ),
        ],
    )

    assert len(result.strategy_summaries) == 2
    assert {
        summary.strategy_name
        for summary in result.strategy_summaries
    } == {"always_buy", "always_sell"}


def test_portfolio_rejects_invalid_balance():
    candles = make_candles(
        "EUR_USD",
        [100.0, 101.0],
    )

    with pytest.raises(
        ValueError,
        match="Initial balance must be greater than zero.",
    ):
        run_portfolio_backtest(
            candles_by_symbol={
                "EUR_USD": candles
            },
            strategy_configs=[
                PortfolioStrategyConfig(
                    strategy_name="always_buy",
                    symbol="EUR_USD",
                )
            ],
            initial_balance=0.0,
        )
