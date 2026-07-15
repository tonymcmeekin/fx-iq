from app.ai.regime import detect_market_regime
from app.ai.regime_policy import (
    RegimePolicyName,
    evaluate_regime_policy,
)
from app.market_data.models import Candle
from app.signals.models import TradeSignal
from app.strategies.atr_breakout import (
    generate_atr_breakout_signal,
)


REGIME_LOOKBACK = 50
MINIMUM_REGIME_CONFIDENCE = 0.6


def _generate_policy_signal(
    candles: list[Candle],
    policy_name: RegimePolicyName,
    strategy_name: str,
) -> TradeSignal:
    if not candles:
        raise ValueError("At least one candle is required.")

    base_signal = generate_atr_breakout_signal(candles)

    if base_signal.direction == "HOLD":
        return TradeSignal(
            symbol=base_signal.symbol,
            direction="HOLD",
            confidence=base_signal.confidence,
            strategy_name=strategy_name,
            reason=(
                "ATR breakout produced no actionable signal. "
                f"{base_signal.reason}"
            ),
        )

    if len(candles) < REGIME_LOOKBACK:
        return TradeSignal(
            symbol=base_signal.symbol,
            direction="HOLD",
            confidence=0.0,
            strategy_name=strategy_name,
            reason=(
                f"At least {REGIME_LOOKBACK} candles are required "
                "for regime-policy evaluation."
            ),
        )

    regime = detect_market_regime(
        candles=candles,
        lookback=REGIME_LOOKBACK,
    )

    decision = evaluate_regime_policy(
        signal=base_signal,
        regime=regime,
        policy_name=policy_name,
        minimum_confidence=MINIMUM_REGIME_CONFIDENCE,
    )

    if not decision.approved:
        return TradeSignal(
            symbol=base_signal.symbol,
            direction="HOLD",
            confidence=regime.confidence,
            strategy_name=strategy_name,
            reason=(
                f"{policy_name} rejected the ATR signal. "
                f"{decision.reason}"
            ),
        )

    combined_confidence = (
        base_signal.confidence + regime.confidence
    ) / 2

    return TradeSignal(
        symbol=base_signal.symbol,
        direction=base_signal.direction,
        confidence=round(
            min(max(combined_confidence, 0.0), 1.0),
            4,
        ),
        strategy_name=strategy_name,
        reason=(
            f"{policy_name} approved the ATR signal. "
            f"Trend={regime.trend}; "
            f"volatility={regime.volatility}; "
            f"regime confidence={regime.confidence}."
        ),
    )


def generate_atr_contrarian_signal(
    candles: list[Candle],
) -> TradeSignal:
    return _generate_policy_signal(
        candles=candles,
        policy_name="CONTRARIAN",
        strategy_name="atr_regime_contrarian",
    )


def generate_atr_allow_ranges_signal(
    candles: list[Candle],
) -> TradeSignal:
    return _generate_policy_signal(
        candles=candles,
        policy_name="ALLOW_RANGES",
        strategy_name="atr_regime_allow_ranges",
    )


def generate_atr_sell_bias_signal(
    candles: list[Candle],
) -> TradeSignal:
    return _generate_policy_signal(
        candles=candles,
        policy_name="SELL_BIAS",
        strategy_name="atr_regime_sell_bias",
    )
