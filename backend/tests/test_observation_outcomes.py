from datetime import UTC, date, datetime

import pytest

from app.intelligence.observation_store import append_observation
from app.intelligence.observations import (
    ObservationFeatures,
    ObservationRegime,
    PortfolioContext,
    TradeObservation,
)
from app.intelligence.outcome_store import (
    ObservationOutcomeError,
    enrich_observation_outcomes,
    read_outcomes,
)
from app.market_data.models import Candle
from app.paper_trading.candle_store import write_candle_store
from app.paper_trading.ledger import append_event

SESSION_DATE = date(2026, 7, 21)
SIGNAL_TIME = datetime(2026, 7, 20, 21, tzinfo=UTC)
ENTRY_TIME = datetime(2026, 7, 21, 21, tzinfo=UTC)
EXIT_TIME = datetime(2026, 7, 22, 21, tzinfo=UTC)


def observation(*, accepted=True):
    return TradeObservation(
        observation_id="a" * 64,
        recorded_at_utc=datetime(2026, 7, 21, 7, tzinfo=UTC),
        session_date=SESSION_DATE,
        instrument="AUD_JPY",
        timeframe="D",
        strategy="ATR Breakout",
        direction="BUY",
        signal_confidence=0.8,
        signal_generated=True,
        trade_accepted=accepted,
        decision_reason="test",
        latest_candle_timestamp=SIGNAL_TIME,
        features=ObservationFeatures(
            candle_count=60,
            latest_close=100,
            ema_20=99,
            ema_50=98,
            ema_alignment="BULLISH",
            trend_state="UP",
            volatility_state="NORMAL",
            rsi_14=60,
            atr_14=1,
            atr_percent=1,
            range_position=0.8,
            setup_quality_score=80,
            setup_quality_label="STRONG",
        ),
        regime=ObservationRegime(
            trend="TRENDING_UP",
            volatility="NORMAL",
            confidence=0.9,
            price_change_percent=2,
            volatility_ratio=1,
            candles_analysed=50,
        ),
        portfolio_context=PortfolioContext(),
    )


def candidate_trade():
    return {
        "market": "AUD_JPY",
        "direction": "BUY",
        "created_session_date": SESSION_DATE.isoformat(),
        "signal_candle_timestamp": SIGNAL_TIME.isoformat(),
        "entry_timestamp": ENTRY_TIME.isoformat(),
        "exit_timestamp": EXIT_TIME.isoformat(),
        "entry_price": 100.0,
        "exit_reason": "Take-profit hit.",
        "account_return_percent": 0.5,
    }


def make_paths(tmp_path, *, accepted=True):
    ledger_path = tmp_path / "events.jsonl"
    observation_path = tmp_path / "observations.jsonl"
    outcome_path = tmp_path / "outcomes.jsonl"
    candle_directory = tmp_path / "candles"
    append_observation(
        observation_path,
        observation(accepted=accepted),
    )
    append_event(
        ledger_path,
        "PAPER_POSITION_CLOSED",
        {
            "market": "AUD_JPY",
            "candidate_trade": candidate_trade(),
            "broker_orders_submitted": 0,
        },
        event_id="close-event",
        occurred_at_utc=EXIT_TIME.isoformat(),
    )
    write_candle_store(
        candle_directory / "AUD_JPY.csv",
        [
            Candle(
                symbol="AUD_JPY",
                timeframe="D",
                timestamp=ENTRY_TIME,
                open=100,
                high=103,
                low=99,
                close=102,
                volume=1000,
            ),
            Candle(
                symbol="AUD_JPY",
                timeframe="D",
                timestamp=EXIT_TIME,
                open=102,
                high=104,
                low=101,
                close=103,
                volume=1000,
            ),
        ],
        expected_symbol="AUD_JPY",
    )
    return {
        "ledger_path": ledger_path,
        "observation_path": observation_path,
        "outcome_path": outcome_path,
        "candle_directory": candle_directory,
    }


def test_enriches_close_event_once(tmp_path):
    paths = make_paths(tmp_path)
    first = enrich_observation_outcomes(
        **paths,
        enriched_at_utc=datetime(2026, 7, 23, tzinfo=UTC),
    )
    second = enrich_observation_outcomes(
        **paths,
        enriched_at_utc=datetime(2026, 7, 23, tzinfo=UTC),
    )
    outcomes = read_outcomes(paths["outcome_path"])

    assert first["outcomes_recorded"] == 1
    assert second["outcome_duplicates"] == 1
    assert len(outcomes) == 1
    assert outcomes[0].observation_id == "a" * 64
    assert outcomes[0].candles_held == 1
    assert outcomes[0].profit_percent == 0.5
    assert outcomes[0].maximum_favourable_excursion_percent == 4.0
    assert outcomes[0].maximum_adverse_excursion_percent == -1.0


def test_rejects_link_to_rejected_observation(tmp_path):
    paths = make_paths(tmp_path, accepted=False)

    with pytest.raises(
        ObservationOutcomeError,
        match="exactly one accepted observation",
    ):
        enrich_observation_outcomes(
            **paths,
            enriched_at_utc=datetime(2026, 7, 23, tzinfo=UTC),
        )
