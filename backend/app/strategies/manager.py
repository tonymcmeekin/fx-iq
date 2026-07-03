from collections.abc import Callable

from app.market_data.models import Candle
from app.signals.models import TradeSignal
from app.strategies.ema_crossover import generate_ema_crossover_signal
from app.strategies.simple_trend import generate_simple_trend_signal

StrategyFunction = Callable[[list[Candle]], TradeSignal]

STRATEGIES: dict[str, StrategyFunction] = {
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
