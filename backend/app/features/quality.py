from __future__ import annotations

from dataclasses import dataclass

from app.features.models import (
    MarketFeatureVector,
    TrendState,
    VolatilityState,
)


@dataclass(frozen=True)
class SetupQualityAssessment:
    score: float
    label: str
    explanation: str
    reasons: tuple[str, ...]


def evaluate_setup_quality(
    features: MarketFeatureVector,
) -> SetupQualityAssessment:
    if features.candle_count < 50:
        return SetupQualityAssessment(
            score=0.0,
            label="INSUFFICIENT_DATA",
            explanation=(
                "There are not enough completed candles to assess "
                "setup quality reliably."
            ),
            reasons=("Fewer than 50 completed candles.",),
        )

    score = 50.0
    reasons: list[str] = []

    if features.trend_state in {
        TrendState.TRENDING_UP,
        TrendState.TRENDING_DOWN,
    }:
        score += 10.0
        reasons.append(
            f"Clear market trend: {features.trend_state.value}."
        )
    elif features.trend_state is TrendState.RANGING:
        score -= 8.0
        reasons.append(
            "The market is ranging rather than trending."
        )

    if features.ema_alignment in {"BULLISH", "BEARISH"}:
        score += 8.0
        reasons.append(
            f"EMA structure is {features.ema_alignment.lower()}."
        )
    else:
        score -= 5.0
        reasons.append("EMA structure is mixed.")

    if features.volatility_state is VolatilityState.NORMAL:
        score += 8.0
        reasons.append(
            "Volatility is within the normal operating range."
        )
    elif features.volatility_state is VolatilityState.LOW:
        score -= 8.0
        reasons.append(
            "Low volatility may reduce breakout follow-through."
        )
    elif features.volatility_state is VolatilityState.HIGH:
        score -= 4.0
        reasons.append(
            "High volatility increases execution and reversal risk."
        )

    if features.ema_20_slope_percent is not None:
        slope_strength = abs(features.ema_20_slope_percent)

        if slope_strength >= 0.08:
            score += 8.0
            reasons.append("The short-term EMA slope is strong.")
        elif slope_strength >= 0.02:
            score += 4.0
            reasons.append("The short-term EMA slope is positive.")
        else:
            score -= 3.0
            reasons.append("The short-term EMA slope is weak.")

    if features.rsi_14 is not None:
        if 45.0 <= features.rsi_14 <= 55.0:
            score += 2.0
            reasons.append("RSI is balanced.")
        elif 30.0 <= features.rsi_14 < 45.0:
            score += 4.0
            reasons.append("RSI shows controlled bearish momentum.")
        elif 55.0 < features.rsi_14 <= 70.0:
            score += 4.0
            reasons.append("RSI shows controlled bullish momentum.")
        elif features.rsi_14 < 20.0:
            score -= 7.0
            reasons.append("RSI is extremely oversold.")
        elif features.rsi_14 > 80.0:
            score -= 7.0
            reasons.append("RSI is extremely overbought.")
        else:
            score -= 2.0
            reasons.append("RSI is approaching an extreme.")

    if features.range_position is not None:
        if features.range_position >= 0.75:
            score += 4.0
            reasons.append(
                "Price is trading near the top of its recent range."
            )
        elif features.range_position <= 0.25:
            score += 4.0
            reasons.append(
                "Price is trading near the bottom of its recent range."
            )
        else:
            reasons.append(
                "Price remains near the middle of its recent range."
            )

    score = round(max(0.0, min(100.0, score)), 2)

    if score >= 75.0:
        label = "STRONG"
    elif score >= 60.0:
        label = "GOOD"
    elif score >= 45.0:
        label = "MIXED"
    else:
        label = "WEAK"

    explanation = (
        f"Setup quality is {label.lower()} with a score of "
        f"{score:.2f} out of 100. "
        f"{' '.join(reasons[:3])}"
    )

    return SetupQualityAssessment(
        score=score,
        label=label,
        explanation=explanation,
        reasons=tuple(reasons),
    )
