from datetime import UTC, datetime, timedelta

import pytest

from app.ai.regime import MarketRegime
from app.ai.regime_policy import RegimePolicyDecision
from app.market_data.models import Candle
from app.signals.models import TradeSignal
from app.strategies import atr_regime_policies
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


def make_signal(direction: str = "SELL") -> TradeSignal:
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


@pytest.mark.parametrize(
    "strategy_name",
    [
        "atr_regime_contrarian",
        "atr_regime_allow_ranges",
        "atr_regime_sell_bias",
    ],
)
def test_policy_strategies_are_registered(strategy_name):
    assert strategy_name in list_available_strategy_names()


def test_empty_history_is_rejected():
    with pytest.raises(
        ValueError,
        match="At least one candle is required.",
    ):
        atr_regime_policies.generate_atr_contrarian_signal(
            []
        )


def test_hold_signal_is_preserved(monkeypatch):
    monkeypatch.setattr(
        atr_regime_policies,
        "generate_atr_breakout_signal",
        lambda candles: make_signal("HOLD"),
    )

    signal = (
        atr_regime_policies
        .generate_atr_sell_bias_signal(
            make_candles()
        )
    )

    assert signal.direction == "HOLD"
    assert signal.strategy_name == "atr_regime_sell_bias"


def test_insufficient_regime_history_rejects_trade(
    monkeypatch,
):
    monkeypatch.setattr(
        atr_regime_policies,
        "generate_atr_breakout_signal",
        lambda candles: make_signal("SELL"),
    )

    signal = (
        atr_regime_policies
        .generate_atr_contrarian_signal(
            make_candles(49)
        )
    )

    assert signal.direction == "HOLD"
    assert "At least 50 candles" in signal.reason


@pytest.mark.parametrize(
    (
        "generator",
        "expected_policy",
        "strategy_name",
    ),
    [
        (
            atr_regime_policies
            .generate_atr_contrarian_signal,
            "CONTRARIAN",
            "atr_regime_contrarian",
        ),
        (
            atr_regime_policies
            .generate_atr_allow_ranges_signal,
            "ALLOW_RANGES",
            "atr_regime_allow_ranges",
        ),
        (
            atr_regime_policies
            .generate_atr_sell_bias_signal,
            "SELL_BIAS",
            "atr_regime_sell_bias",
        ),
    ],
)
def test_generator_uses_expected_policy(
    monkeypatch,
    generator,
    expected_policy,
    strategy_name,
):
    captured = {}

    monkeypatch.setattr(
        atr_regime_policies,
        "generate_atr_breakout_signal",
        lambda candles: make_signal("SELL"),
    )

    monkeypatch.setattr(
        atr_regime_policies,
        "detect_market_regime",
        lambda **kwargs: make_regime(),
    )

    def fake_policy_evaluation(**kwargs):
        captured["policy_name"] = kwargs["policy_name"]

        return RegimePolicyDecision(
            approved=True,
            policy_name=kwargs["policy_name"],
            signal_direction="SELL",
            regime_trend="TRENDING_UP",
            regime_volatility="NORMAL",
            reason="Approved.",
        )

    monkeypatch.setattr(
        atr_regime_policies,
        "evaluate_regime_policy",
        fake_policy_evaluation,
    )

    signal = generator(make_candles())

    assert captured["policy_name"] == expected_policy
    assert signal.direction == "SELL"
    assert signal.strategy_name == strategy_name


def test_rejected_policy_returns_hold(monkeypatch):
    monkeypatch.setattr(
        atr_regime_policies,
        "generate_atr_breakout_signal",
        lambda candles: make_signal("SELL"),
    )

    monkeypatch.setattr(
        atr_regime_policies,
        "detect_market_regime",
        lambda **kwargs: make_regime(),
    )

    monkeypatch.setattr(
        atr_regime_policies,
        "evaluate_regime_policy",
        lambda **kwargs: RegimePolicyDecision(
            approved=False,
            policy_name="SELL_BIAS",
            signal_direction="SELL",
            regime_trend="TRENDING_UP",
            regime_volatility="NORMAL",
            reason="Rejected for test.",
        ),
    )

    signal = (
        atr_regime_policies
        .generate_atr_sell_bias_signal(
            make_candles()
        )
    )

    assert signal.direction == "HOLD"
    assert "rejected the ATR signal" in signal.reason
