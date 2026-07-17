from typing import Literal

from pydantic import BaseModel, Field

from app.market_data.models import Candle

DecisionClassification = Literal["ALLOW", "WATCH", "REJECT"]


class TradeDecision(BaseModel):
    signal: str
    approved: bool
    decision: str
    reason: str


class DecisionEvaluationRequest(BaseModel):
    strategy_name: str
    candles: list[Candle] = Field(min_length=2)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    entry_price: float | None = Field(default=None, gt=0)
    base_risk_percent: float = Field(default=0.5, gt=0, le=1)
    minimum_risk_reward: float = Field(default=1.5, gt=0)
    minimum_regime_confidence: float = Field(
        default=0.6,
        ge=0,
        le=1,
    )


class DecisionComponentScores(BaseModel):
    signal_quality: float = Field(ge=0, le=100)
    trend_alignment: float = Field(ge=0, le=100)
    regime_confidence: float = Field(ge=0, le=100)
    volatility_suitability: float = Field(ge=0, le=100)
    risk_reward: float = Field(ge=0, le=100)


class DecisionRiskAssessment(BaseModel):
    requested_risk_percent: float
    adjusted_risk_percent: float
    risk_multiplier: float
    risk_reward_ratio: float
    policy_version: str
    reasons: list[str]


class DecisionEvaluationResponse(BaseModel):
    symbol: str
    strategy_name: str
    direction: str
    decision: DecisionClassification
    approved_for_paper_trade: bool
    confidence_score: float = Field(ge=0, le=100)
    market_regime: str
    regime_volatility: str
    component_scores: DecisionComponentScores
    risk_assessment: DecisionRiskAssessment
    blocking_reasons: list[str]
    warnings: list[str]
    explanation: str

    paper_trading_only: bool = True
    live_trading_allowed: bool = False
    broker_orders_submitted: int = 0
    network_calls_made: int = 0
    ledger_writes_performed: int = 0
