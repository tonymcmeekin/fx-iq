from typing import Literal

from pydantic import BaseModel

from app.ai.regime import MarketRegime
from app.signals.models import TradeSignal


SignalDecision = Literal[
    "APPROVED",
    "REJECTED",
]


class RegimeSignalDecision(BaseModel):
    decision: SignalDecision
    original_direction: str
    regime_trend: str
    regime_volatility: str
    confidence: float
    reason: str


def evaluate_signal_for_regime(
    signal: TradeSignal,
    regime: MarketRegime,
    minimum_confidence: float = 0.6,
    reject_low_volatility: bool = False,
) -> RegimeSignalDecision:
    if not 0 <= minimum_confidence <= 1:
        raise ValueError(
            "Minimum confidence must be between zero and one."
        )

    if signal.direction == "HOLD":
        return RegimeSignalDecision(
            decision="REJECTED",
            original_direction=signal.direction,
            regime_trend=regime.trend,
            regime_volatility=regime.volatility,
            confidence=regime.confidence,
            reason="The underlying strategy produced no trade signal.",
        )

    if signal.direction not in {"BUY", "SELL"}:
        return RegimeSignalDecision(
            decision="REJECTED",
            original_direction=signal.direction,
            regime_trend=regime.trend,
            regime_volatility=regime.volatility,
            confidence=regime.confidence,
            reason="The signal direction is not supported.",
        )

    if regime.confidence < minimum_confidence:
        return RegimeSignalDecision(
            decision="REJECTED",
            original_direction=signal.direction,
            regime_trend=regime.trend,
            regime_volatility=regime.volatility,
            confidence=regime.confidence,
            reason=(
                "The detected market regime does not meet the "
                "minimum confidence threshold."
            ),
        )

    if reject_low_volatility and regime.volatility == "LOW":
        return RegimeSignalDecision(
            decision="REJECTED",
            original_direction=signal.direction,
            regime_trend=regime.trend,
            regime_volatility=regime.volatility,
            confidence=regime.confidence,
            reason=(
                "Low volatility is not suitable for the configured "
                "breakout filter."
            ),
        )

    direction_matches_regime = (
        signal.direction == "BUY"
        and regime.trend == "TRENDING_UP"
    ) or (
        signal.direction == "SELL"
        and regime.trend == "TRENDING_DOWN"
    )

    if not direction_matches_regime:
        return RegimeSignalDecision(
            decision="REJECTED",
            original_direction=signal.direction,
            regime_trend=regime.trend,
            regime_volatility=regime.volatility,
            confidence=regime.confidence,
            reason=(
                "The signal direction does not agree with the "
                "detected market trend."
            ),
        )

    return RegimeSignalDecision(
        decision="APPROVED",
        original_direction=signal.direction,
        regime_trend=regime.trend,
        regime_volatility=regime.volatility,
        confidence=regime.confidence,
        reason=(
            "The signal direction agrees with a sufficiently "
            "confident market regime."
        ),
    )
