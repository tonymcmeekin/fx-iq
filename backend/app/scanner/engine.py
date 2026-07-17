from datetime import UTC, datetime, timedelta

from app.decision.engine import evaluate_trade_decision
from app.decision.models import (
    DecisionEvaluationRequest,
    DecisionEvaluationResponse,
)
from app.market_data.models import Candle
from app.scanner.models import ScannerOpportunity, ScannerResult
from app.scanner.universe import (
    DEFAULT_MARKET_UNIVERSE,
    ScannerMarketDefinition,
)

SCANNER_VERSION = "1.0"

DECISION_PRIORITY = {
    "ALLOW": 0,
    "WATCH": 1,
    "REJECT": 2,
}


def _build_trending_market(
    symbol: str,
    timeframe: str,
    start_price: float,
    step: float,
    breakout_offset: float,
) -> DecisionEvaluationRequest:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []

    for index in range(50):
        close = start_price + index * step

        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=start + timedelta(hours=index),
                open=close - abs(step) * 0.35,
                high=close + abs(step) * 0.50,
                low=close - abs(step) * 0.50,
                close=close,
                volume=1000 + index,
            )
        )

    recent_candles = candles[-20:]

    if step > 0:
        previous_extreme = max(
            candle.high for candle in recent_candles
        )
        entry_price = previous_extreme + breakout_offset
        stop_loss = entry_price - breakout_offset * 2
        take_profit = entry_price + breakout_offset * 4
        open_price = entry_price - breakout_offset * 0.4
        high_price = entry_price + breakout_offset * 0.3
        low_price = entry_price - breakout_offset * 0.5
    else:
        previous_extreme = min(
            candle.low for candle in recent_candles
        )
        entry_price = previous_extreme - breakout_offset
        stop_loss = entry_price + breakout_offset * 2
        take_profit = entry_price - breakout_offset * 4
        open_price = entry_price + breakout_offset * 0.4
        high_price = entry_price + breakout_offset * 0.5
        low_price = entry_price - breakout_offset * 0.3

    candles.append(
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=start + timedelta(hours=50),
            open=open_price,
            high=high_price,
            low=low_price,
            close=entry_price,
            volume=1500,
        )
    )

    return DecisionEvaluationRequest(
        strategy_name="atr_breakout",
        candles=candles,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        base_risk_percent=0.5,
        minimum_risk_reward=1.5,
        minimum_regime_confidence=0.6,
    )


def _build_ranging_market(
    symbol: str,
    timeframe: str,
    centre_price: float,
    movement: float,
) -> DecisionEvaluationRequest:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []

    for index in range(51):
        phase = index % 4

        if phase == 0:
            offset = 0.0
        elif phase == 1:
            offset = movement
        elif phase == 2:
            offset = 0.0
        else:
            offset = -movement

        close = centre_price + offset

        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=start + timedelta(hours=index),
                open=close,
                high=close + movement * 0.5,
                low=close - movement * 0.5,
                close=close,
                volume=900 + index,
            )
        )

    entry_price = candles[-1].close

    return DecisionEvaluationRequest(
        strategy_name="atr_breakout",
        candles=candles,
        entry_price=entry_price,
        stop_loss=entry_price - movement * 2,
        take_profit=entry_price + movement * 4,
        base_risk_percent=0.5,
        minimum_risk_reward=1.5,
        minimum_regime_confidence=0.6,
    )


def build_market_request(
    market: ScannerMarketDefinition,
) -> DecisionEvaluationRequest:
    if market.scenario == "RANGING":
        return _build_ranging_market(
            symbol=market.symbol,
            timeframe=market.timeframe,
            centre_price=market.start_price,
            movement=market.movement,
        )

    step = market.movement

    if market.scenario == "TRENDING_DOWN":
        step = -step

    return _build_trending_market(
        symbol=market.symbol,
        timeframe=market.timeframe,
        start_price=market.start_price,
        step=step,
        breakout_offset=market.breakout_offset,
    )


def build_scan_requests(
    universe: tuple[ScannerMarketDefinition, ...],
) -> list[DecisionEvaluationRequest]:
    return [
        build_market_request(market)
        for market in universe
    ]


def build_sample_scan_requests() -> list[DecisionEvaluationRequest]:
    return build_scan_requests(DEFAULT_MARKET_UNIVERSE)


def _sort_key(
    evaluation: DecisionEvaluationResponse,
) -> tuple[int, float, float, str]:
    return (
        DECISION_PRIORITY[evaluation.decision],
        -evaluation.confidence_score,
        -evaluation.risk_assessment.risk_reward_ratio,
        evaluation.symbol,
    )


def _to_opportunity(
    evaluation: DecisionEvaluationResponse,
    rank: int,
) -> ScannerOpportunity:
    return ScannerOpportunity(
        rank=rank,
        symbol=evaluation.symbol,
        strategy_name=evaluation.strategy_name,
        direction=evaluation.direction,
        decision=evaluation.decision,
        confidence_score=evaluation.confidence_score,
        risk_reward_ratio=(
            evaluation.risk_assessment.risk_reward_ratio
        ),
        market_regime=evaluation.market_regime,
        regime_volatility=evaluation.regime_volatility,
        adjusted_risk_percent=(
            evaluation.risk_assessment.adjusted_risk_percent
        ),
        approved_for_paper_trade=(
            evaluation.approved_for_paper_trade
        ),
        warning_count=len(evaluation.warnings),
        blocking_reason_count=len(evaluation.blocking_reasons),
        explanation=evaluation.explanation,
        paper_trading_only=evaluation.paper_trading_only,
        live_trading_allowed=evaluation.live_trading_allowed,
        broker_orders_submitted=(
            evaluation.broker_orders_submitted
        ),
        network_calls_made=evaluation.network_calls_made,
        ledger_writes_performed=(
            evaluation.ledger_writes_performed
        ),
    )


def scan_opportunities(
    requests: list[DecisionEvaluationRequest],
) -> ScannerResult:
    evaluations = [
        evaluate_trade_decision(request)
        for request in requests
    ]

    ranked_evaluations = sorted(
        evaluations,
        key=_sort_key,
    )

    opportunities = [
        _to_opportunity(evaluation, rank)
        for rank, evaluation in enumerate(
            ranked_evaluations,
            start=1,
        )
    ]

    return ScannerResult(
        scanner_version=SCANNER_VERSION,
        opportunities=opportunities,
        evaluated_markets=len(opportunities),
        allow_count=sum(
            opportunity.decision == "ALLOW"
            for opportunity in opportunities
        ),
        watch_count=sum(
            opportunity.decision == "WATCH"
            for opportunity in opportunities
        ),
        reject_count=sum(
            opportunity.decision == "REJECT"
            for opportunity in opportunities
        ),
    )


def scan_sample_opportunities() -> ScannerResult:
    return scan_opportunities(build_sample_scan_requests())
