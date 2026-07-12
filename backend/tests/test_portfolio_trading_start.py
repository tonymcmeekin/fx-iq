from datetime import UTC, datetime, timedelta

from app.market_data.models import Candle
from app.portfolio.engine import run_portfolio_backtest
from app.portfolio.models import PortfolioStrategyConfig


def make_candles() -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    closes = [
        100.0,
        101.0,
        102.0,
        103.0,
        104.0,
        105.0,
        106.0,
    ]

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


def test_warmup_period_does_not_create_test_period_trades():
    candles = make_candles()
    trading_start = candles[4].timestamp

    result = run_portfolio_backtest(
        candles_by_symbol={
            "EUR_USD": candles,
        },
        strategy_configs=[
            PortfolioStrategyConfig(
                strategy_name="simple_trend",
                symbol="EUR_USD",
                stop_loss_percent=50.0,
                take_profit_percent=50.0,
                risk_per_trade_percent=0.5,
            )
        ],
        trading_start_timestamp=trading_start,
    )

    assert result.total_trades == 1
    assert all(
        trade.entry_timestamp >= trading_start
        for trade in result.trades
    )
    assert result.trades[0].entry_timestamp == trading_start


def test_reported_equity_curve_starts_at_test_boundary():
    candles = make_candles()
    trading_start = candles[4].timestamp

    result = run_portfolio_backtest(
        candles_by_symbol={
            "EUR_USD": candles,
        },
        strategy_configs=[
            PortfolioStrategyConfig(
                strategy_name="simple_trend",
                symbol="EUR_USD",
                stop_loss_percent=50.0,
                take_profit_percent=50.0,
            )
        ],
        trading_start_timestamp=trading_start,
    )

    assert result.equity_curve
    assert result.equity_curve[0].timestamp == trading_start
    assert all(
        point.timestamp >= trading_start
        for point in result.equity_curve
    )
