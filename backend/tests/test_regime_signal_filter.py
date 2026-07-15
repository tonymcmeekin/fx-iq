import pytest

from app.ai.regime import MarketRegime
from app.ai.signal_filter import evaluate_signal_for_regime
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
    volatility: str = "NORMAL",
    confidence: float = 0.8,
) -> MarketRegime:
    return MarketRegime(
        trend=trend,
        volatility=volatility,
        confidence=confidence,
        price_change_percent=2.5,
        volatility_ratio=1.0,
        candles_analysed=50,
    )


def test_approves_buy_signal_in_uptrend():
    decision = evaluate_signal_for_regime(
        signal=make_signal("BUY"),
        regime=make_regime("TRENDING_UP"),
    )

    assert decision.decision == "APPROVED"


def test_approves_sell_signal_in_downtrend():
    decision = evaluate_signal_for_regime(
        signal=make_signal("SELL"),
        regime=make_regime("TRENDING_DOWN"),
    )

    assert decision.decision == "APPROVED"


def test_rejects_buy_signal_in_downtrend():
    decision = evaluate_signal_for_regime(
        signal=make_signal("BUY"),
        regime=make_regime("TRENDING_DOWN"),
    )

    assert decision.decision == "REJECTED"
    assert "does not agree" in decision.reason


def test_rejects_signal_in_ranging_market():
    decision = evaluate_signal_for_regime(
        signal=make_signal("BUY"),
        regime=make_regime("RANGING"),
    )

    assert decision.decision == "REJECTED"


def test_rejects_low_confidence_regime():
    decision = evaluate_signal_for_regime(
        signal=make_signal("BUY"),
        regime=make_regime(
            "TRENDING_UP",
            confidence=0.5,
        ),
        minimum_confidence=0.6,
    )

    assert decision.decision == "REJECTED"
    assert "confidence threshold" in decision.reason


def test_can_reject_low_volatility():
    decision = evaluate_signal_for_regime(
        signal=make_signal("BUY"),
        regime=make_regime(
            "TRENDING_UP",
            volatility="LOW",
        ),
        reject_low_volatility=True,
    )

    assert decision.decision == "REJECTED"
    assert "Low volatility" in decision.reason


def test_low_volatility_is_allowed_by_default():
    decision = evaluate_signal_for_regime(
        signal=make_signal("BUY"),
        regime=make_regime(
            "TRENDING_UP",
            volatility="LOW",
        ),
    )

    assert decision.decision == "APPROVED"


def test_rejects_hold_signal():
    decision = evaluate_signal_for_regime(
        signal=make_signal("HOLD"),
        regime=make_regime("TRENDING_UP"),
    )

    assert decision.decision == "REJECTED"


@pytest.mark.parametrize(
    "minimum_confidence",
    [-0.1, 1.1],
)
def test_rejects_invalid_confidence_threshold(
    minimum_confidence,
):
    with pytest.raises(
        ValueError,
        match=(
            "Minimum confidence must be between "
            "zero and one."
        ),
    ):
        evaluate_signal_for_regime(
            signal=make_signal("BUY"),
            regime=make_regime("TRENDING_UP"),
            minimum_confidence=minimum_confidence,
        )
