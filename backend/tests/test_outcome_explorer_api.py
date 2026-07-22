"""Tests for sparse-safe passive outcome exploration."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from app.analytics import router
from app.analytics.outcome_explorer_reporting import (
    OutcomeExplorerError,
    build_outcome_explorer_report,
)
from app.intelligence.observation_store import append_observation
from app.intelligence.observations import (
    ObservationFeatures,
    ObservationRegime,
    PortfolioContext,
    TradeObservation,
)
from app.intelligence.outcome_store import (
    ObservationOutcomeRecord,
    append_outcome,
)
from app.main import app
from app.paper_trading.ledger import append_event

client = TestClient(app)


def observation(index: int) -> TradeObservation:
    signal_time = datetime(2026, 1, 1, 21, tzinfo=UTC)
    return TradeObservation(
        observation_id=("a" * 63) + str(index),
        recorded_at_utc=datetime(2026, 1, 2, 7, tzinfo=UTC),
        session_date=date(2026, 1, 2),
        instrument="AUD_JPY",
        timeframe="D",
        strategy="ATR Breakout",
        direction="BUY" if index < 3 else "SELL",
        signal_confidence=0.8,
        signal_generated=True,
        trade_accepted=True,
        decision_reason="test",
        latest_candle_timestamp=signal_time,
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


def populate_outcomes(tmp_path):
    ledger_path = tmp_path / "events.jsonl"
    observation_path = tmp_path / "observations.jsonl"
    outcome_path = tmp_path / "outcomes.jsonl"
    entry_time = datetime(2026, 1, 3, 21, tzinfo=UTC)

    for index in range(5):
        source = observation(index)
        close_event_id = f"close-{index}"
        append_observation(observation_path, source)
        append_event(
            ledger_path,
            "PAPER_POSITION_CLOSED",
            {"market": "AUD_JPY", "broker_orders_submitted": 0},
            event_id=close_event_id,
        )
        append_outcome(
            outcome_path,
            ObservationOutcomeRecord(
                outcome_id=("b" * 63) + str(index),
                observation_id=source.observation_id,
                close_event_id=close_event_id,
                enriched_at_utc=datetime(2026, 1, 10, tzinfo=UTC),
                originating_session_date=source.session_date,
                close_session_date=date(2026, 1, 5 + index),
                instrument=source.instrument,
                direction=source.direction,
                signal_candle_timestamp=source.latest_candle_timestamp,
                entry_timestamp=entry_time,
                exit_timestamp=entry_time + timedelta(days=index + 1),
                profit_percent=[1.0, 0.5, -0.25, 0.75, -0.5][index],
                candles_held=index + 1,
                maximum_favourable_excursion_percent=1.5 + index,
                maximum_adverse_excursion_percent=-0.2 - index * 0.1,
                exit_reason="Take-profit hit." if index < 3 else "Stop-loss hit.",
            ),
        )

    append_event(
        ledger_path,
        "SESSION_COMPLETED",
        {"session_date": "2026-01-02"},
    )
    return ledger_path, observation_path, outcome_path


def test_outcome_explorer_joins_and_groups_verified_records(tmp_path):
    ledger_path, observation_path, outcome_path = populate_outcomes(tmp_path)

    result = build_outcome_explorer_report(
        ledger_path=ledger_path,
        observation_path=observation_path,
        outcome_path=outcome_path,
        minimum_overall_sample=5,
        minimum_group_sample=2,
        now_utc=datetime(2026, 1, 11, tzinfo=UTC),
    )

    assert result["status"] == "AVAILABLE"
    assert result["outcome_count"] == 5
    assert result["overall"]["sample_size"] == 5
    assert result["overall"]["mean_return_percent"] == 0.3
    assert result["overall"]["win_rate_percent"] == 60.0
    assert result["distribution"]["candles_held"] == {
        "minimum": 1.0,
        "p25": 2.0,
        "median": 3.0,
        "p75": 4.0,
        "maximum": 5.0,
    }
    instrument = next(
        row
        for row in result["groups"]
        if row["dimension"] == "instrument"
    )
    assert instrument["value"] == "AUD_JPY"
    assert instrument["status"] == "AVAILABLE"
    assert instrument["sample_size"] == 5


def test_outcome_explorer_withholds_sparse_metrics(tmp_path):
    result = build_outcome_explorer_report(
        ledger_path=tmp_path / "events.jsonl",
        observation_path=tmp_path / "observations.jsonl",
        outcome_path=tmp_path / "outcomes.jsonl",
    )

    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["outcome_count"] == 0
    assert result["overall"]["mean_return_percent"] is None
    assert result["distribution"]["return_percent"] is None
    assert result["groups"] == []


def test_outcome_endpoint_returns_conflict_on_failure(monkeypatch):
    def fail():
        raise OutcomeExplorerError("Outcome evidence is unavailable.")

    monkeypatch.setattr(router, "build_outcome_explorer_report", fail)

    response = client.get("/analytics/outcome-explorer")

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == (
        "Outcome evidence is unavailable."
    )


def test_real_outcome_endpoint_is_read_only():
    response = client.get("/analytics/outcome-explorer")

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["outcome_count"] == 0
    assert result["minimum_overall_sample"] == 20
    assert result["minimum_group_sample"] == 5
    assert result["network_calls_made"] == 0
    assert result["files_changed"] == 0
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False
