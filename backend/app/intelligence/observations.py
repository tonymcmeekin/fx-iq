"""Passive trade-observation records for future model training."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.regime import detect_market_regime
from app.features import (
    FeatureCandle,
    build_market_features,
    evaluate_setup_quality,
)
from app.market_data.models import Candle
from app.signals.models import TradeSignal

OBSERVATION_SCHEMA_VERSION = 2

TradeDirection = Literal[
    "BUY",
    "SELL",
    "HOLD",
]


class ObservationFeatures(BaseModel):
    """Stable, model-ready market features."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    candle_count: int = Field(ge=0)
    latest_close: float = Field(gt=0)
    ema_20: float | None
    ema_50: float | None
    ema_alignment: str
    trend_state: str
    volatility_state: str
    rsi_14: float | None = Field(
        default=None,
        ge=0,
        le=100,
    )
    atr_14: float | None = Field(
        default=None,
        ge=0,
    )
    atr_percent: float | None = Field(
        default=None,
        ge=0,
    )
    range_position: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    setup_quality_score: int = Field(
        ge=0,
        le=100,
    )
    setup_quality_label: str


class ObservationRegime(BaseModel):
    """Market regime recorded at observation time."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    trend: str
    volatility: str
    confidence: float = Field(
        ge=0,
        le=1,
    )
    price_change_percent: float
    volatility_ratio: float = Field(
        ge=0,
    )
    candles_analysed: int = Field(
        ge=2,
    )


class PortfolioContext(BaseModel):
    """Safe portfolio context with no broker credentials."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    pending_entries_total: int = Field(
        default=0,
        ge=0,
    )
    open_positions_total: int = Field(
        default=0,
        ge=0,
    )
    correlated_positions: int = Field(
        default=0,
        ge=0,
    )
    portfolio_risk_percent: float = Field(
        default=0.0,
        ge=0,
    )


class TradeOutcome(BaseModel):
    """Outcome fields populated only after a trade is resolved."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    profit_percent: float
    candles_held: int = Field(
        ge=0,
    )
    maximum_favourable_excursion_percent: float
    maximum_adverse_excursion_percent: float
    exit_reason: str


class TradeObservation(BaseModel):
    """Immutable observation suitable for JSONL storage."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    schema_version: int = Field(
        default=OBSERVATION_SCHEMA_VERSION,
        ge=1,
    )
    observation_id: str = Field(
        min_length=64,
        max_length=64,
    )
    recorded_at_utc: datetime
    session_date: date
    instrument: str = Field(
        min_length=1,
    )
    timeframe: str = Field(
        min_length=1,
    )
    strategy: str = Field(
        min_length=1,
    )
    direction: TradeDirection
    signal_confidence: float = Field(
        ge=0,
        le=1,
    )
    signal_generated: bool
    trade_accepted: bool
    decision_reason: str
    latest_candle_timestamp: datetime
    features: ObservationFeatures
    regime: ObservationRegime
    portfolio_context: PortfolioContext
    outcome: TradeOutcome | None = None


def _utc_datetime(
    value: datetime,
    *,
    field: str,
) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware.")

    return value.astimezone(UTC)


def _enum_value(
    value: object,
) -> str:
    raw_value = getattr(
        value,
        "value",
        value,
    )

    return str(raw_value)


def _canonical_json(
    value: dict,
) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def observation_identity_payload(
    *,
    session_date: date,
    instrument: str,
    timeframe: str,
    strategy: str,
    direction: str,
    latest_candle_timestamp: datetime,
) -> dict:
    """Return the fields that uniquely identify one evaluation."""

    timestamp = _utc_datetime(
        latest_candle_timestamp,
        field="Latest candle timestamp",
    )

    return {
        "schema_version": (OBSERVATION_SCHEMA_VERSION),
        "session_date": (session_date.isoformat()),
        "instrument": instrument,
        "timeframe": timeframe,
        "strategy": strategy,
        "direction": direction,
        "latest_candle_timestamp": (timestamp.isoformat().replace("+00:00", "Z")),
    }


def calculate_observation_id(
    *,
    session_date: date,
    instrument: str,
    timeframe: str,
    strategy: str,
    direction: str,
    latest_candle_timestamp: datetime,
) -> str:
    """Create a deterministic observation identifier."""

    payload = observation_identity_payload(
        session_date=session_date,
        instrument=instrument,
        timeframe=timeframe,
        strategy=strategy,
        direction=direction,
        latest_candle_timestamp=(latest_candle_timestamp),
    )

    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def build_trade_observation(
    *,
    session_date: date,
    recorded_at_utc: datetime,
    candles: list[Candle],
    signal: TradeSignal,
    trade_accepted: bool,
    decision_reason: str,
    portfolio_context: PortfolioContext | None = None,
) -> TradeObservation:
    """
    Build a passive observation from existing deterministic logic.

    This function does not approve, reject, size, submit, or modify
    a trade.
    """

    if not candles:
        raise ValueError("At least one candle is required.")

    recorded_at = _utc_datetime(
        recorded_at_utc,
        field="Observation timestamp",
    )

    latest = candles[-1]
    latest_timestamp = _utc_datetime(
        latest.timestamp,
        field="Latest candle timestamp",
    )

    if any(candle.symbol != latest.symbol for candle in candles):
        raise ValueError("Observation candles must use one instrument.")

    if any(candle.timeframe != latest.timeframe for candle in candles):
        raise ValueError("Observation candles must use one timeframe.")

    if signal.symbol != latest.symbol:
        raise ValueError("Signal instrument does not match candles.")

    if signal.direction not in {
        "BUY",
        "SELL",
        "HOLD",
    }:
        raise ValueError("Signal direction must be BUY, SELL, or HOLD.")

    feature_candles = [
        FeatureCandle(
            high=candle.high,
            low=candle.low,
            close=candle.close,
        )
        for candle in candles
    ]

    market_features = build_market_features(feature_candles)
    setup_quality = evaluate_setup_quality(market_features)

    regime = detect_market_regime(
        candles=candles,
        lookback=50,
    )

    features = ObservationFeatures(
        candle_count=(market_features.candle_count),
        latest_close=float(market_features.latest_close),
        ema_20=market_features.ema_20,
        ema_50=market_features.ema_50,
        ema_alignment=_enum_value(market_features.ema_alignment),
        trend_state=_enum_value(market_features.trend_state),
        volatility_state=_enum_value(market_features.volatility_state),
        rsi_14=market_features.rsi_14,
        atr_14=market_features.atr_14,
        atr_percent=(market_features.atr_percent),
        range_position=(market_features.range_position),
        setup_quality_score=(setup_quality.score),
        setup_quality_label=(_enum_value(setup_quality.label)),
    )

    observation_regime = ObservationRegime(
        trend=regime.trend,
        volatility=regime.volatility,
        confidence=regime.confidence,
        price_change_percent=(regime.price_change_percent),
        volatility_ratio=(regime.volatility_ratio),
        candles_analysed=(regime.candles_analysed),
    )

    observation_id = calculate_observation_id(
        session_date=session_date,
        instrument=latest.symbol,
        timeframe=latest.timeframe,
        strategy=signal.strategy_name,
        direction=signal.direction,
        latest_candle_timestamp=(latest_timestamp),
    )

    return TradeObservation(
        observation_id=observation_id,
        recorded_at_utc=recorded_at,
        session_date=session_date,
        instrument=latest.symbol,
        timeframe=latest.timeframe,
        strategy=signal.strategy_name,
        direction=signal.direction,
        signal_confidence=(signal.confidence),
        signal_generated=(signal.direction in {"BUY", "SELL"}),
        trade_accepted=trade_accepted,
        decision_reason=decision_reason,
        latest_candle_timestamp=(latest_timestamp),
        features=features,
        regime=observation_regime,
        portfolio_context=(portfolio_context or PortfolioContext()),
        outcome=None,
    )
