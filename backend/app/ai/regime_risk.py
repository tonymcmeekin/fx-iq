from typing import Protocol

from pydantic import BaseModel, Field


RISK_POLICY_VERSION = "1.0"

MINIMUM_RISK_PERCENT = 0.10
MAXIMUM_RISK_PERCENT = 1.00


class RegimeLike(Protocol):
    trend: str
    volatility: str
    confidence: float


class RegimeRiskDecision(BaseModel):
    policy_version: str
    base_risk_percent: float = Field(gt=0)
    risk_multiplier: float = Field(gt=0, le=1)
    adjusted_risk_percent: float = Field(gt=0)
    trend: str
    volatility: str
    regime_confidence: float = Field(ge=0, le=1)
    reasons: list[str]


def _normalise_label(value: object) -> str:
    raw_value = getattr(value, "value", value)
    return str(raw_value).upper()


def calculate_regime_risk(
    base_risk_percent: float,
    regime: RegimeLike,
) -> RegimeRiskDecision:
    if base_risk_percent <= 0:
        raise ValueError(
            "Base risk percent must be greater than zero."
        )

    if base_risk_percent > MAXIMUM_RISK_PERCENT:
        raise ValueError(
            "Base risk percent cannot exceed one percent."
        )

    trend = _normalise_label(regime.trend)
    volatility = _normalise_label(regime.volatility)
    confidence = float(regime.confidence)

    if confidence < 0 or confidence > 1:
        raise ValueError(
            "Regime confidence must be between zero and one."
        )

    multiplier = 1.0
    reasons = []

    if volatility == "HIGH":
        multiplier = min(multiplier, 0.50)
        reasons.append(
            "High volatility limits risk to fifty percent "
            "of the configured base risk."
        )

    elif volatility == "LOW":
        multiplier = min(multiplier, 0.75)
        reasons.append(
            "Low volatility limits risk because breakout "
            "follow-through may be weaker."
        )

    if trend == "RANGING":
        multiplier = min(multiplier, 0.75)
        reasons.append(
            "Ranging conditions limit risk because directional "
            "breakouts may be less reliable."
        )

    if confidence < 0.60:
        multiplier = min(multiplier, 0.50)
        reasons.append(
            "Low regime confidence limits risk because the "
            "market state is uncertain."
        )

    if not reasons:
        reasons.append(
            "Normal-volatility directional conditions retain "
            "the configured base risk."
        )

    adjusted_risk = base_risk_percent * multiplier

    adjusted_risk = max(
        MINIMUM_RISK_PERCENT,
        adjusted_risk,
    )

    adjusted_risk = min(
        adjusted_risk,
        base_risk_percent,
        MAXIMUM_RISK_PERCENT,
    )

    return RegimeRiskDecision(
        policy_version=RISK_POLICY_VERSION,
        base_risk_percent=round(
            base_risk_percent,
            6,
        ),
        risk_multiplier=round(
            multiplier,
            6,
        ),
        adjusted_risk_percent=round(
            adjusted_risk,
            6,
        ),
        trend=trend,
        volatility=volatility,
        regime_confidence=round(
            confidence,
            6,
        ),
        reasons=reasons,
    )
