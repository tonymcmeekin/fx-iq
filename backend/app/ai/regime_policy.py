from typing import Literal

from pydantic import BaseModel

from app.ai.regime import MarketRegime
from app.signals.models import TradeSignal

RegimePolicyName = Literal[
    "NO_FILTER",
    "TREND_FOLLOWING",
    "CONTRARIAN",
    "ALLOW_RANGES",
    "SELL_BIAS",
]


class RegimePolicyDecision(BaseModel):
    approved: bool
    policy_name: RegimePolicyName
    signal_direction: str
    regime_trend: str
    regime_volatility: str
    reason: str


def evaluate_regime_policy(
    signal: TradeSignal,
    regime: MarketRegime,
    policy_name: RegimePolicyName,
    minimum_confidence: float = 0.6,
) -> RegimePolicyDecision:
    if not 0 <= minimum_confidence <= 1:
        raise ValueError(
            "Minimum confidence must be between zero and one."
        )

    if signal.direction not in {"BUY", "SELL"}:
        return RegimePolicyDecision(
            approved=False,
            policy_name=policy_name,
            signal_direction=signal.direction,
            regime_trend=regime.trend,
            regime_volatility=regime.volatility,
            reason="No actionable BUY or SELL signal was supplied.",
        )

    if policy_name == "NO_FILTER":
        return RegimePolicyDecision(
            approved=True,
            policy_name=policy_name,
            signal_direction=signal.direction,
            regime_trend=regime.trend,
            regime_volatility=regime.volatility,
            reason="The no-filter policy accepts every trade signal.",
        )

    if regime.confidence < minimum_confidence:
        return RegimePolicyDecision(
            approved=False,
            policy_name=policy_name,
            signal_direction=signal.direction,
            regime_trend=regime.trend,
            regime_volatility=regime.volatility,
            reason=(
                "The regime confidence is below the configured "
                "minimum."
            ),
        )

    trend_aligned = (
        signal.direction == "BUY"
        and regime.trend == "TRENDING_UP"
    ) or (
        signal.direction == "SELL"
        and regime.trend == "TRENDING_DOWN"
    )

    counter_trend = (
        signal.direction == "BUY"
        and regime.trend == "TRENDING_DOWN"
    ) or (
        signal.direction == "SELL"
        and regime.trend == "TRENDING_UP"
    )

    if policy_name == "TREND_FOLLOWING":
        approved = trend_aligned
        reason = (
            "The signal agrees with the detected trend."
            if approved
            else "The signal does not agree with the detected trend."
        )

    elif policy_name == "CONTRARIAN":
        approved = counter_trend
        reason = (
            "The signal opposes the detected trend."
            if approved
            else "The signal is not counter-trend."
        )

    elif policy_name == "ALLOW_RANGES":
        approved = (
            trend_aligned
            or regime.trend == "RANGING"
        )
        reason = (
            "The signal is trend-aligned or occurred in a range."
            if approved
            else (
                "The signal is neither trend-aligned nor in a "
                "ranging regime."
            )
        )

    elif policy_name == "SELL_BIAS":
        approved = signal.direction == "SELL"
        reason = (
            "The policy accepts SELL signals."
            if approved
            else "The policy rejects BUY signals."
        )

    else:
        raise ValueError(
            f"Unknown regime policy: {policy_name}"
        )

    return RegimePolicyDecision(
        approved=approved,
        policy_name=policy_name,
        signal_direction=signal.direction,
        regime_trend=regime.trend,
        regime_volatility=regime.volatility,
        reason=reason,
    )
