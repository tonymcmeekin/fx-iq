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


def calculate_historical_regime_risk_percent(
    base_risk_percent: float,
    candles,
    lookback: int = 50,
) -> float:
    """
    Calculate risk using only the historical candles supplied.

    When insufficient history exists, retain the configured base
    risk rather than rejecting an otherwise valid trade.
    """
    if len(candles) < lookback:
        return base_risk_percent

    from app.ai.regime import detect_market_regime

    regime = detect_market_regime(
        candles=candles,
        lookback=lookback,
    )

    decision = calculate_regime_risk(
        base_risk_percent=base_risk_percent,
        regime=regime,
    )

    return decision.adjusted_risk_percent


def regime_risk_adjuster(
    config,
    historical_candles,
) -> float:
    """
    Portfolio-engine adapter for deterministic regime risk sizing.
    """
    return calculate_historical_regime_risk_percent(
        base_risk_percent=config.risk_per_trade_percent,
        candles=historical_candles,
    )


SELECTIVE_RISK_POLICY_VERSION = "2.0"


def calculate_selective_regime_risk(
    base_risk_percent: float,
    regime: RegimeLike,
    direction: str,
) -> RegimeRiskDecision:
    """
    Development policy derived only from pre-5 August 2024 evidence.

    Risk is reduced only for two regime/direction combinations that
    remained negative under leave-one-market-out robustness testing.

    This policy never increases configured risk.
    """
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
    normalised_direction = _normalise_label(direction)
    confidence = float(regime.confidence)

    if normalised_direction not in {"BUY", "SELL"}:
        raise ValueError(
            "Direction must be BUY or SELL."
        )

    if confidence < 0 or confidence > 1:
        raise ValueError(
            "Regime confidence must be between zero and one."
        )

    reduce_buy = (
        normalised_direction == "BUY"
        and trend == "TRENDING_UP"
        and volatility == "NORMAL"
    )

    reduce_sell = (
        normalised_direction == "SELL"
        and trend == "TRENDING_DOWN"
        and volatility == "NORMAL"
    )

    if reduce_buy:
        multiplier = 0.50
        reasons = [
            "Risk reduced because BUY trades in normal-volatility "
            "uptrends had robust negative development expectancy."
        ]
    elif reduce_sell:
        multiplier = 0.50
        reasons = [
            "Risk reduced because SELL trades in normal-volatility "
            "downtrends had robust negative development expectancy."
        ]
    else:
        multiplier = 1.00
        reasons = [
            "Configured risk retained because this regime and "
            "direction did not meet the robust-negative threshold."
        ]

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
        policy_version=SELECTIVE_RISK_POLICY_VERSION,
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
