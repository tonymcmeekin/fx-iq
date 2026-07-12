from datetime import UTC, datetime

from app.market_data.models import Candle
from app.trading.simulator import simulate_multi_candle_trade


def make_candle(
    close: float,
    high: float | None = None,
    low: float | None = None,
) -> Candle:
    return Candle(
        symbol="EUR_USD",
        timeframe="H1",
        timestamp=datetime(2026, 7, 3, tzinfo=UTC),
        open=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
        volume=1000,
    )


def test_buy_take_profit_hit():
    trade = simulate_multi_candle_trade(
        candles=[
            make_candle(100.0),
            make_candle(101.0, high=102.5, low=100.5),
        ],
        direction="BUY",
        stop_loss_percent=1.0,
        take_profit_percent=2.0,
    )

    assert trade.exit_reason == "Take-profit hit."
    assert trade.exit_price == 102.0
    assert trade.profit_percent == 2.0


def test_buy_stop_loss_hit():
    trade = simulate_multi_candle_trade(
        candles=[
            make_candle(100.0),
            make_candle(99.0, high=100.5, low=98.5),
        ],
        direction="BUY",
        stop_loss_percent=1.0,
        take_profit_percent=2.0,
    )

    assert trade.exit_reason == "Stop-loss hit."
    assert trade.exit_price == 99.0
    assert trade.profit_percent == -1.0


def test_sell_take_profit_hit():
    trade = simulate_multi_candle_trade(
        candles=[
            make_candle(100.0),
            make_candle(98.0, high=99.5, low=97.5),
        ],
        direction="SELL",
        stop_loss_percent=1.0,
        take_profit_percent=2.0,
    )

    assert trade.exit_reason == "Take-profit hit."
    assert trade.exit_price == 98.0
    assert trade.profit_percent == 2.0


def test_sell_stop_loss_hit():
    trade = simulate_multi_candle_trade(
        candles=[
            make_candle(100.0),
            make_candle(101.0, high=101.5, low=99.5),
        ],
        direction="SELL",
        stop_loss_percent=1.0,
        take_profit_percent=2.0,
    )

    assert trade.exit_reason == "Stop-loss hit."
    assert trade.exit_price == 101.0
    assert trade.profit_percent == -1.0


def test_trade_closes_at_final_candle():
    trade = simulate_multi_candle_trade(
        candles=[
            make_candle(100.0),
            make_candle(100.5, high=100.8, low=99.8),
        ],
        direction="BUY",
        stop_loss_percent=1.0,
        take_profit_percent=2.0,
    )

    assert trade.exit_reason == "Closed at final candle."
    assert trade.exit_price == 100.5
    assert trade.profit_percent == 0.5


def test_spread_is_deducted_from_trade_profit():
    trade = simulate_multi_candle_trade(
        candles=[
            make_candle(1.1000),
            make_candle(1.1110, high=1.1110, low=1.1000),
        ],
        direction="BUY",
        stop_loss_percent=10.0,
        take_profit_percent=10.0,
        spread_pips=1.0,
    )

    assert trade.gross_profit_percent == 1.0
    assert trade.trading_cost_percent == 0.009091
    assert trade.profit_percent == 0.990909
    assert trade.spread_pips == 1.0


def test_commission_is_deducted_from_trade_profit():
    trade = simulate_multi_candle_trade(
        candles=[
            make_candle(100.0),
            make_candle(101.0, high=101.0, low=100.0),
        ],
        direction="BUY",
        stop_loss_percent=10.0,
        take_profit_percent=10.0,
        commission_percent=0.1,
    )

    assert trade.gross_profit_percent == 1.0
    assert trade.trading_cost_percent == 0.1
    assert trade.profit_percent == 0.9


def test_negative_spread_is_rejected():
    try:
        simulate_multi_candle_trade(
            candles=[
                make_candle(100.0),
                make_candle(101.0),
            ],
            direction="BUY",
            spread_pips=-1.0,
        )
    except ValueError as error:
        assert str(error) == "Spread pips cannot be negative."
    else:
        raise AssertionError("Expected negative spread to be rejected.")


def test_trade_enters_at_entry_candle_open():
    entry_candle = Candle(
        symbol="EUR_USD",
        timeframe="H1",
        timestamp=datetime(2026, 7, 3, tzinfo=UTC),
        open=100.0,
        high=106.0,
        low=99.5,
        close=105.0,
        volume=1000,
    )

    exit_candle = Candle(
        symbol="EUR_USD",
        timeframe="H1",
        timestamp=datetime(2026, 7, 3, 1, tzinfo=UTC),
        open=105.0,
        high=105.5,
        low=104.5,
        close=105.0,
        volume=1000,
    )

    trade = simulate_multi_candle_trade(
        candles=[entry_candle, exit_candle],
        direction="BUY",
        stop_loss_percent=10.0,
        take_profit_percent=10.0,
    )

    assert trade.entry_price == 100.0
    assert trade.gross_profit_percent == 5.0


def test_buy_trade_uses_stop_when_stop_and_target_hit_same_candle():
    trade = simulate_multi_candle_trade(
        candles=[
            make_candle(
                100.0,
                high=103.0,
                low=98.0,
            ),
            make_candle(100.0),
        ],
        direction="BUY",
        stop_loss_percent=1.0,
        take_profit_percent=2.0,
    )

    assert trade.exit_price == 99.0
    assert trade.profit_percent == -1.0
    assert trade.candles_held == 0
    assert "both stop-loss and take-profit" in trade.exit_reason


def test_sell_trade_uses_stop_when_stop_and_target_hit_same_candle():
    trade = simulate_multi_candle_trade(
        candles=[
            make_candle(
                100.0,
                high=102.0,
                low=97.0,
            ),
            make_candle(100.0),
        ],
        direction="SELL",
        stop_loss_percent=1.0,
        take_profit_percent=2.0,
    )

    assert trade.exit_price == 101.0
    assert trade.profit_percent == -1.0
    assert trade.candles_held == 0
    assert "both stop-loss and take-profit" in trade.exit_reason


def test_invalid_pip_size_is_rejected():
    try:
        simulate_multi_candle_trade(
            candles=[
                make_candle(100.0),
                make_candle(101.0),
            ],
            direction="BUY",
            pip_size=0.0,
        )
    except ValueError as error:
        assert str(error) == "Pip size must be greater than zero."
    else:
        raise AssertionError("Expected invalid pip size to be rejected.")
