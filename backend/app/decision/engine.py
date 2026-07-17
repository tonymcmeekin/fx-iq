from app.ai.regime import MarketRegime, detect_market_regime
from app.ai.regime_risk import calculate_regime_risk
from app.ai.signal_filter import evaluate_signal_for_regime
from app.decision.models import (
    DecisionComponentScores,
    DecisionEvaluationRequest,
    DecisionEvaluationResponse,
    DecisionRiskAssessment,
)
from app.signals.models import TradeSignal
from app.strategies.manager import run_strategy

SIGNAL_QUALITY_WEIGHT = 0.25
TREND_ALIGNMENT_WEIGHT = 0.25
REGIME_CONFIDENCE_WEIGHT = 0.20
VOLATILITY_WEIGHT = 0.10
RISK_REWARD_WEIGHT = 0.20

ALLOW_THRESHOLD = 70.0
WATCH_THRESHOLD = 50.0
REGIME_LOOKBACK = 50


def _clamp_score(value: float) -> float:
    return round(min(max(value, 0.0), 100.0), 2)


def _direction_matches_regime(
    direction: str,
    regime: MarketRegime,
) -> bool:
    return (direction == "BUY" and regime.trend == "TRENDING_UP") or (
        direction == "SELL" and regime.trend == "TRENDING_DOWN"
    )


def _risk_reward_ratio(
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
) -> tuple[float, list[str]]:
    blocking_reasons: list[str] = []

    if direction == "BUY":
        if stop_loss >= entry_price:
            blocking_reasons.append("A BUY stop-loss must be below the entry price.")
        if take_profit <= entry_price:
            blocking_reasons.append("A BUY take-profit must be above the entry price.")

        risk_distance = entry_price - stop_loss
        reward_distance = take_profit - entry_price

    elif direction == "SELL":
        if stop_loss <= entry_price:
            blocking_reasons.append("A SELL stop-loss must be above the entry price.")
        if take_profit >= entry_price:
            blocking_reasons.append("A SELL take-profit must be below the entry price.")

        risk_distance = stop_loss - entry_price
        reward_distance = entry_price - take_profit

    else:
        return 0.0, blocking_reasons

    if risk_distance <= 0 or reward_distance <= 0:
        return 0.0, blocking_reasons

    return reward_distance / risk_distance, blocking_reasons


def _trend_alignment_score(
    signal: TradeSignal,
    regime: MarketRegime,
) -> float:
    if _direction_matches_regime(signal.direction, regime):
        return 100.0

    if regime.trend == "RANGING":
        return 30.0

    return 0.0


def _volatility_score(regime: MarketRegime) -> float:
    return {
        "NORMAL": 100.0,
        "LOW": 65.0,
        "HIGH": 55.0,
    }[regime.volatility]


def _build_explanation(
    decision: str,
    signal: TradeSignal,
    regime: MarketRegime,
    risk_reward_ratio: float,
    blocking_reasons: list[str],
) -> str:
    if blocking_reasons:
        return f"The {signal.direction} setup was rejected because {blocking_reasons[0]}"

    if decision == "ALLOW":
        return (
            f"The {signal.direction} setup is supported by the "
            f"{regime.trend} regime, a confidence-qualified signal, "
            f"and a {risk_reward_ratio:.2f}:1 risk/reward ratio."
        )

    if decision == "WATCH":
        return (
            f"The {signal.direction} setup has some supporting evidence, "
            "but its combined score is not strong enough for paper-trade "
            "approval."
        )

    return f"The {signal.direction} setup does not satisfy the deterministic decision requirements."


def evaluate_trade_decision(
    request: DecisionEvaluationRequest,
) -> DecisionEvaluationResponse:
    signal = run_strategy(
        strategy_name=request.strategy_name,
        candles=request.candles,
    )

    entry_price = (
        request.entry_price if request.entry_price is not None else request.candles[-1].close
    )

    regime = detect_market_regime(
        candles=request.candles,
        lookback=REGIME_LOOKBACK,
    )

    regime_gate = evaluate_signal_for_regime(
        signal=signal,
        regime=regime,
        minimum_confidence=request.minimum_regime_confidence,
    )

    risk_decision = calculate_regime_risk(
        base_risk_percent=request.base_risk_percent,
        regime=regime,
    )

    blocking_reasons: list[str] = []
    warnings: list[str] = []

    if signal.direction == "HOLD":
        blocking_reasons.append("The strategy produced HOLD rather than an actionable signal.")
    elif signal.direction not in {"BUY", "SELL"}:
        blocking_reasons.append("The strategy produced an unsupported direction.")

    risk_reward_ratio, geometry_blocks = _risk_reward_ratio(
        direction=signal.direction,
        entry_price=entry_price,
        stop_loss=request.stop_loss,
        take_profit=request.take_profit,
    )
    blocking_reasons.extend(geometry_blocks)

    if signal.direction in {"BUY", "SELL"} and risk_reward_ratio < request.minimum_risk_reward:
        blocking_reasons.append("The proposed risk/reward ratio is below the configured minimum.")

    if regime_gate.decision == "REJECTED":
        blocking_reasons.append(regime_gate.reason)

    if regime.volatility == "HIGH":
        warnings.append("High volatility has reduced the permitted risk allocation.")
    elif regime.volatility == "LOW":
        warnings.append("Low volatility may weaken breakout follow-through.")

    if risk_decision.risk_multiplier < 1:
        warnings.extend(risk_decision.reasons)

    component_scores = DecisionComponentScores(
        signal_quality=_clamp_score(signal.confidence * 100),
        trend_alignment=_clamp_score(_trend_alignment_score(signal, regime)),
        regime_confidence=_clamp_score(regime.confidence * 100),
        volatility_suitability=_clamp_score(_volatility_score(regime)),
        risk_reward=_clamp_score(risk_reward_ratio / 3.0 * 100),
    )

    confidence_score = _clamp_score(
        component_scores.signal_quality * SIGNAL_QUALITY_WEIGHT
        + component_scores.trend_alignment * TREND_ALIGNMENT_WEIGHT
        + component_scores.regime_confidence * REGIME_CONFIDENCE_WEIGHT
        + component_scores.volatility_suitability * VOLATILITY_WEIGHT
        + component_scores.risk_reward * RISK_REWARD_WEIGHT
    )

    if blocking_reasons:
        decision = "REJECT"
    elif confidence_score >= ALLOW_THRESHOLD:
        decision = "ALLOW"
    elif confidence_score >= WATCH_THRESHOLD:
        decision = "WATCH"
    else:
        decision = "REJECT"

    return DecisionEvaluationResponse(
        symbol=signal.symbol,
        strategy_name=request.strategy_name,
        direction=signal.direction,
        decision=decision,
        approved_for_paper_trade=decision == "ALLOW",
        confidence_score=confidence_score,
        market_regime=regime.trend,
        regime_volatility=regime.volatility,
        component_scores=component_scores,
        risk_assessment=DecisionRiskAssessment(
            requested_risk_percent=(risk_decision.base_risk_percent),
            adjusted_risk_percent=(risk_decision.adjusted_risk_percent),
            risk_multiplier=risk_decision.risk_multiplier,
            risk_reward_ratio=round(risk_reward_ratio, 4),
            policy_version=risk_decision.policy_version,
            reasons=risk_decision.reasons,
        ),
        blocking_reasons=blocking_reasons,
        warnings=list(dict.fromkeys(warnings)),
        explanation=_build_explanation(
            decision=decision,
            signal=signal,
            regime=regime,
            risk_reward_ratio=risk_reward_ratio,
            blocking_reasons=blocking_reasons,
        ),
    )
