from typing import Literal

from pydantic import BaseModel, Field

from app.decision.models import DecisionEvaluationResponse

ScannerDecision = Literal["ALLOW", "WATCH", "REJECT"]


class ScannerFeatureMetadata(BaseModel):
    candle_count: int = Field(ge=0)
    trend_state: str
    volatility_state: str
    ema_alignment: str
    price_change_percent: float | None = None
    ema_20_slope_percent: float | None = None
    atr_percent: float | None = None
    rsi_14: float | None = Field(default=None, ge=0, le=100)
    range_position: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )


class ScannerQualityMetadata(BaseModel):
    score: float = Field(ge=0, le=100)
    label: str
    explanation: str
    reasons: list[str]


class ScannerOpportunity(BaseModel):
    rank: int = Field(ge=1)
    symbol: str
    timeframe: str
    strategy_name: str
    direction: str
    decision: ScannerDecision
    confidence_score: float = Field(ge=0, le=100)
    risk_reward_ratio: float = Field(ge=0)
    market_regime: str
    regime_volatility: str
    adjusted_risk_percent: float = Field(ge=0)
    approved_for_paper_trade: bool
    warning_count: int = Field(ge=0)
    blocking_reason_count: int = Field(ge=0)
    explanation: str
    features: ScannerFeatureMetadata
    setup_quality: ScannerQualityMetadata

    paper_trading_only: bool = True
    live_trading_allowed: bool = False
    broker_orders_submitted: int = 0
    network_calls_made: int = 0
    ledger_writes_performed: int = 0


class ScannerResult(BaseModel):
    scanner_version: str
    opportunities: list[ScannerOpportunity]
    evaluated_markets: int = Field(ge=0)
    allow_count: int = Field(ge=0)
    watch_count: int = Field(ge=0)
    reject_count: int = Field(ge=0)

    paper_trading_only: bool = True
    live_trading_allowed: bool = False
    broker_orders_submitted: int = 0
    network_calls_made: int = 0
    ledger_writes_performed: int = 0


class RankedDecision(BaseModel):
    evaluation: DecisionEvaluationResponse
    decision_priority: int
