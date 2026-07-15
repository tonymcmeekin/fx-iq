from app.ai.regime import detect_market_regime
from app.ai.signal_filter import evaluate_signal_for_regime
from app.market_data.models import Candle
from app.signals.models import TradeSignal
from app.strategies.atr_breakout import (
    generate_atr_breakout_signal,
)


STRATEGY_NAME = "atr_regime_filtered"
REGIME_LOOKBACK = 50
MINIMUM_REGIME_CONFIDENCE = 0.6


def generate_atr_regime_filtered_signal(
    candles: list[Candle],
) -> TradeSignal:
    if not candles:
        raise ValueError("At least one candle is required.")

    base_signal = generate_atr_breakout_signal(candles)

    if base_signal.direction == "HOLD":
        return TradeSignal(
            symbol=base_signal.symbol,
            direction="HOLD",
            confidence=base_signal.confidence,
            strategy_name=STRATEGY_NAME,
            reason=(
                "ATR breakout produced no trade. "
                f"{base_signal.reason}"
            ),
        )

    if len(candles) < REGIME_LOOKBACK:
        return TradeSignal(
            symbol=base_signal.symbol,
            direction="HOLD",
            confidence=0.0,
            strategy_name=STRATEGY_NAME,
            reason=(
                f"At least {REGIME_LOOKBACK} candles are required "
                "for regime confirmation."
            ),
        )

    regime = detect_market_regime(
        candles=candles,
        lookback=REGIME_LOOKBACK,
    )

    decision = evaluate_signal_for_regime(
        signal=base_signal,
        regime=regime,
        minimum_confidence=MINIMUM_REGIME_CONFIDENCE,
    )

    if decision.decision == "REJECTED":
        return TradeSignal(
            symbol=base_signal.symbol,
            direction="HOLD",
            confidence=decision.confidence,
            strategy_name=STRATEGY_NAME,
            reason=(
                "ATR signal rejected by the regime gate. "
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
        strategy_name=STRATEGY_NAME,
        reason=(
            "ATR signal approved by the regime gate. "
            f"Trend={regime.trend}; "
            f"volatility={regime.volatility}; "
            f"regime confidence={regime.confidence}."
        ),
    )
