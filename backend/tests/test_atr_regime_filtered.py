from datetime import UTC, datetime, timedelta

import pytest

from app.ai.regime import MarketRegime
from app.ai.signal_filter import RegimeSignalDecision
from app.market_data.models import Candle
from app.signals.models import TradeSignal
from app.strategies import atr_regime_filtered
from app.strategies.manager import (
    list_available_strategy_names,
)


def make_candles(count: int = 50) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)

    return [
        Candle(
            symbol="EUR_USD",
            timeframe="D",
            timestamp=start + timedelta(days=index),
            open=1.10,
            high=1.11,
            low=1.09,
            close=1.10,
            volume=1000,
        )
        for index in range(count)
    ]


def make_signal(direction: str) -> TradeSignal:
    return TradeSignal(
        symbol="EUR_USD",
        direction=direction,
        confidence=0.8,
        strategy_name="atr_breakout",
        reason="Synthetic ATR signal.",
    )


def make_regime() -> MarketRegime:
    return MarketRegime(
        trend="TRENDING_UP",
        volatility="NORMAL",
        confidence=0.9,
        price_change_percent=3.0,
        volatility_ratio=1.0,
        candles_analysed=50,
    )


def test_strategy_is_registered():
    assert (
        "atr_regime_filtered"
        in list_available_strategy_names()
    )


def test_rejects_empty_history():
    with pytest.raises(
        ValueError,
        match="At least one candle is required.",
    ):
        atr_regime_filtered.generate_atr_regime_filtered_signal(
            []
        )


def test_preserves_hold_from_atr_strategy(monkeypatch):
    monkeypatch.setattr(
        atr_regime_filtered,
        "generate_atr_breakout_signal",
        lambda candles: make_signal("HOLD"),
    )

    signal = (
        atr_regime_filtered
        .generate_atr_regime_filtered_signal(
            make_candles()
        )
    )

    assert signal.direction == "HOLD"
    assert signal.strategy_name == "atr_regime_filtered"


def test_requires_regime_history_for_trade_signal(
    monkeypatch,
):
    monkeypatch.setattr(
        atr_regime_filtered,
        "generate_atr_breakout_signal",
        lambda candles: make_signal("BUY"),
    )

    signal = (
        atr_regime_filtered
        .generate_atr_regime_filtered_signal(
            make_candles(49)
        )
    )

    assert signal.direction == "HOLD"
    assert "At least 50 candles" in signal.reason


def test_approves_matching_signal(monkeypatch):
    monkeypatch.setattr(
        atr_regime_filtered,
        "generate_atr_breakout_signal",
        lambda candles: make_signal("BUY"),
    )

    monkeypatch.setattr(
        atr_regime_filtered,
        "detect_market_regime",
        lambda **kwargs: make_regime(),
    )

    monkeypatch.setattr(
        atr_regime_filtered,
        "evaluate_signal_for_regime",
        lambda **kwargs: RegimeSignalDecision(
            decision="APPROVED",
            original_direction="BUY",
            regime_trend="TRENDING_UP",
            regime_volatility="NORMAL",
            confidence=0.9,
            reason="Approved.",
        ),
    )

    signal = (
        atr_regime_filtered
        .generate_atr_regime_filtered_signal(
            make_candles()
        )
    )

    assert signal.direction == "BUY"
    assert signal.confidence == 0.85
    assert signal.strategy_name == "atr_regime_filtered"


def test_rejects_non_matching_signal(monkeypatch):
    monkeypatch.setattr(
        atr_regime_filtered,
        "generate_atr_breakout_signal",
        lambda candles: make_signal("BUY"),
    )

    monkeypatch.setattr(
        atr_regime_filtered,
        "detect_market_regime",
        lambda **kwargs: make_regime(),
    )

    monkeypatch.setattr(
        atr_regime_filtered,
        "evaluate_signal_for_regime",
        lambda **kwargs: RegimeSignalDecision(
            decision="REJECTED",
            original_direction="BUY",
            regime_trend="TRENDING_DOWN",
            regime_volatility="NORMAL",
            confidence=0.9,
            reason="Direction mismatch.",
        ),
    )

    signal = (
        atr_regime_filtered
        .generate_atr_regime_filtered_signal(
            make_candles()
        )
    )

    assert signal.direction == "HOLD"
    assert "rejected by the regime gate" in signal.reason
