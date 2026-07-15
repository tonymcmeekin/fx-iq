from types import SimpleNamespace

import pytest

from app.ai.regime_risk import (
    RISK_POLICY_VERSION,
    calculate_regime_risk,
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


def test_normal_trending_market_keeps_base_risk():
    decision = calculate_regime_risk(
        base_risk_percent=0.5,
        regime=regime(),
    )

    assert decision.adjusted_risk_percent == 0.5
    assert decision.risk_multiplier == 1.0


def test_high_volatility_halves_risk():
    decision = calculate_regime_risk(
        base_risk_percent=0.5,
        regime=regime(volatility="HIGH"),
    )

    assert decision.adjusted_risk_percent == 0.25
    assert decision.risk_multiplier == 0.5


def test_low_volatility_reduces_risk():
    decision = calculate_regime_risk(
        base_risk_percent=0.5,
        regime=regime(volatility="LOW"),
    )

    assert decision.adjusted_risk_percent == 0.375
    assert decision.risk_multiplier == 0.75


def test_ranging_market_reduces_risk():
    decision = calculate_regime_risk(
        base_risk_percent=0.5,
        regime=regime(trend="RANGING"),
    )

    assert decision.adjusted_risk_percent == 0.375
    assert decision.risk_multiplier == 0.75


def test_low_confidence_halves_risk():
    decision = calculate_regime_risk(
        base_risk_percent=0.5,
        regime=regime(confidence=0.4),
    )

    assert decision.adjusted_risk_percent == 0.25
    assert decision.risk_multiplier == 0.5


def test_multiple_risk_conditions_do_not_compound():
    decision = calculate_regime_risk(
        base_risk_percent=0.5,
        regime=regime(
            trend="RANGING",
            volatility="HIGH",
            confidence=0.4,
        ),
    )

    assert decision.adjusted_risk_percent == 0.25
    assert decision.risk_multiplier == 0.5


def test_policy_never_increases_base_risk():
    decision = calculate_regime_risk(
        base_risk_percent=0.2,
        regime=regime(),
    )

    assert decision.adjusted_risk_percent <= 0.2


def test_minimum_risk_floor_is_applied():
    decision = calculate_regime_risk(
        base_risk_percent=0.15,
        regime=regime(volatility="HIGH"),
    )

    assert decision.adjusted_risk_percent == 0.1


def test_rejects_zero_base_risk():
    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        calculate_regime_risk(
            base_risk_percent=0,
            regime=regime(),
        )


def test_rejects_excessive_base_risk():
    with pytest.raises(
        ValueError,
        match="cannot exceed one percent",
    ):
        calculate_regime_risk(
            base_risk_percent=1.1,
            regime=regime(),
        )


def test_rejects_invalid_confidence():
    with pytest.raises(
        ValueError,
        match="between zero and one",
    ):
        calculate_regime_risk(
            base_risk_percent=0.5,
            regime=regime(confidence=1.2),
        )


def test_records_policy_version():
    decision = calculate_regime_risk(
        base_risk_percent=0.5,
        regime=regime(),
    )

    assert decision.policy_version == RISK_POLICY_VERSION
