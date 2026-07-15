import pytest

from app.ai.regime import MarketRegime
from app.ai.regime_policy import evaluate_regime_policy
from app.signals.models import TradeSignal


def make_signal(direction: str) -> TradeSignal:
    return TradeSignal(
        symbol="EUR_USD",
        direction=direction,
        confidence=0.8,
        strategy_name="atr_breakout",
        reason="Test signal.",
    )


def make_regime(
    trend: str,
    confidence: float = 0.8,
) -> MarketRegime:
    return MarketRegime(
        trend=trend,
        volatility="NORMAL",
        confidence=confidence,
        price_change_percent=2.5,
        volatility_ratio=1.0,
        candles_analysed=50,
    )


def test_no_filter_accepts_buy():
    decision = evaluate_regime_policy(
        make_signal("BUY"),
        make_regime("TRENDING_DOWN"),
        "NO_FILTER",
    )

    assert decision.approved is True


def test_trend_policy_accepts_matching_buy():
    decision = evaluate_regime_policy(
        make_signal("BUY"),
        make_regime("TRENDING_UP"),
        "TREND_FOLLOWING",
    )

    assert decision.approved is True


def test_trend_policy_rejects_counter_trend_buy():
    decision = evaluate_regime_policy(
        make_signal("BUY"),
        make_regime("TRENDING_DOWN"),
        "TREND_FOLLOWING",
    )

    assert decision.approved is False


def test_contrarian_policy_accepts_sell_in_uptrend():
    decision = evaluate_regime_policy(
        make_signal("SELL"),
        make_regime("TRENDING_UP"),
        "CONTRARIAN",
    )

    assert decision.approved is True


def test_allow_ranges_accepts_ranging_signal():
    decision = evaluate_regime_policy(
        make_signal("BUY"),
        make_regime("RANGING"),
        "ALLOW_RANGES",
    )

    assert decision.approved is True


def test_sell_bias_accepts_sell():
    decision = evaluate_regime_policy(
        make_signal("SELL"),
        make_regime("RANGING"),
        "SELL_BIAS",
    )

    assert decision.approved is True


def test_sell_bias_rejects_buy():
    decision = evaluate_regime_policy(
        make_signal("BUY"),
        make_regime("TRENDING_UP"),
        "SELL_BIAS",
    )

    assert decision.approved is False


def test_non_actionable_signal_is_rejected():
    decision = evaluate_regime_policy(
        make_signal("HOLD"),
        make_regime("TRENDING_UP"),
        "NO_FILTER",
    )

    assert decision.approved is False


def test_low_confidence_is_rejected_for_filtered_policy():
    decision = evaluate_regime_policy(
        make_signal("BUY"),
        make_regime(
            "TRENDING_UP",
            confidence=0.5,
        ),
        "TREND_FOLLOWING",
        minimum_confidence=0.6,
    )

    assert decision.approved is False


def test_no_filter_ignores_regime_confidence():
    decision = evaluate_regime_policy(
        make_signal("BUY"),
        make_regime(
            "TRENDING_DOWN",
            confidence=0.1,
        ),
        "NO_FILTER",
        minimum_confidence=0.9,
    )

    assert decision.approved is True


@pytest.mark.parametrize(
    "minimum_confidence",
    [-0.1, 1.1],
)
def test_invalid_minimum_confidence_is_rejected(
    minimum_confidence,
):
    with pytest.raises(
        ValueError,
        match=(
            "Minimum confidence must be between "
            "zero and one."
        ),
    ):
        evaluate_regime_policy(
            make_signal("BUY"),
            make_regime("TRENDING_UP"),
            "TREND_FOLLOWING",
            minimum_confidence=minimum_confidence,
        )
