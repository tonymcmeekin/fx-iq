from collections.abc import Callable

from app.market_data.models import Candle
from app.signals.models import TradeSignal
from app.strategies.atr_breakout import generate_atr_breakout_signal
from app.strategies.atr_regime_filtered import (
    generate_atr_regime_filtered_signal,
)
from app.strategies.atr_regime_policies import (
    generate_atr_allow_ranges_signal,
    generate_atr_contrarian_signal,
    generate_atr_sell_bias_signal,
)
from app.strategies.ema_crossover import generate_ema_crossover_signal
from app.strategies.simple_trend import generate_simple_trend_signal

StrategyFunction = Callable[[list[Candle]], TradeSignal]

STRATEGIES: dict[str, StrategyFunction] = {
    "atr_breakout": generate_atr_breakout_signal,
    "atr_regime_filtered": generate_atr_regime_filtered_signal,
    "atr_regime_contrarian": generate_atr_contrarian_signal,
    "atr_regime_allow_ranges": generate_atr_allow_ranges_signal,
    "atr_regime_sell_bias": generate_atr_sell_bias_signal,
    "simple_trend": generate_simple_trend_signal,
    "ema_crossover": generate_ema_crossover_signal,
}


def list_available_strategy_names() -> list[str]:
    return sorted(STRATEGIES.keys())


def run_strategy(strategy_name: str, candles: list[Candle]) -> TradeSignal:
    if strategy_name not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    strategy = STRATEGIES[strategy_name]
    return strategy(candles)
