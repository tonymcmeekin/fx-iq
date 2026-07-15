from types import SimpleNamespace

import pytest

from app.ai.regime_risk import (
    SELECTIVE_RISK_POLICY_VERSION,
    calculate_selective_regime_risk,
)


def regime(
    trend="TRENDING_UP",
    volatility="NORMAL",
    confidence=1.0,
):
    return SimpleNamespace(
        trend=trend,
        volatility=volatility,
        confidence=confidence,
    )


def test_reduces_buy_risk_in_normal_uptrend():
    decision = calculate_selective_regime_risk(
        base_risk_percent=0.5,
        regime=regime(
            trend="TRENDING_UP",
            volatility="NORMAL",
        ),
        direction="BUY",
    )

    assert decision.adjusted_risk_percent == 0.25
    assert decision.risk_multiplier == 0.5


def test_reduces_sell_risk_in_normal_downtrend():
    decision = calculate_selective_regime_risk(
        base_risk_percent=0.5,
        regime=regime(
            trend="TRENDING_DOWN",
            volatility="NORMAL",
        ),
        direction="SELL",
    )

    assert decision.adjusted_risk_percent == 0.25
    assert decision.risk_multiplier == 0.5


def test_does_not_reduce_sell_risk_in_high_volatility_downtrend():
    decision = calculate_selective_regime_risk(
        base_risk_percent=0.5,
        regime=regime(
            trend="TRENDING_DOWN",
            volatility="HIGH",
        ),
        direction="SELL",
    )

    assert decision.adjusted_risk_percent == 0.5
    assert decision.risk_multiplier == 1.0


def test_does_not_reduce_countertrend_buy():
    decision = calculate_selective_regime_risk(
        base_risk_percent=0.5,
        regime=regime(
            trend="TRENDING_DOWN",
            volatility="NORMAL",
        ),
        direction="BUY",
    )

    assert decision.adjusted_risk_percent == 0.5


def test_does_not_increase_risk():
    decision = calculate_selective_regime_risk(
        base_risk_percent=0.4,
        regime=regime(
            trend="RANGING",
            volatility="HIGH",
        ),
        direction="SELL",
    )

    assert decision.adjusted_risk_percent <= 0.4


def test_rejects_invalid_direction():
    with pytest.raises(
        ValueError,
        match="Direction must be BUY or SELL",
    ):
        calculate_selective_regime_risk(
            base_risk_percent=0.5,
            regime=regime(),
            direction="HOLD",
        )


def test_records_selective_policy_version():
    decision = calculate_selective_regime_risk(
        base_risk_percent=0.5,
        regime=regime(),
        direction="BUY",
    )

    assert (
        decision.policy_version
        == SELECTIVE_RISK_POLICY_VERSION
    )
