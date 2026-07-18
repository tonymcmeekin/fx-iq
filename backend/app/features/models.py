from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TrendState(StrEnum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class VolatilityState(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class MarketFeatureVector:
    candle_count: int
    latest_close: float | None
    price_change_percent: float | None
    ema_20: float | None
    ema_50: float | None
    ema_alignment: str
    ema_20_slope_percent: float | None
    atr_14: float | None
    atr_percent: float | None
    rsi_14: float | None
    recent_high: float | None
    recent_low: float | None
    range_position: float | None
    trend_state: TrendState
    volatility_state: VolatilityState
