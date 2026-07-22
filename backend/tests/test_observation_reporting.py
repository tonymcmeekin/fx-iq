from datetime import UTC, date, datetime

from app.intelligence.observation_store import (
    append_observation,
)
from app.intelligence.observations import (
    ObservationFeatures,
    ObservationRegime,
    PortfolioContext,
    TradeObservation,
)
from app.intelligence.reporting import (
    build_observation_report,
)
from app.paper_trading.ledger import append_event

SESSION_DATE = date(2026, 7, 22)
RECORDED_AT = datetime(
    2026,
    7,
    22,
    7,
    0,
    tzinfo=UTC,
)


def make_observation(
    *,
    observation_id: str = "a" * 64,
    session_date: date = SESSION_DATE,
) -> TradeObservation:
    return TradeObservation(
        observation_id=observation_id,
        recorded_at_utc=RECORDED_AT,
        session_date=session_date,
        instrument="AUD_JPY",
        timeframe="D",
        strategy="ATR Breakout",
        direction="BUY",
        signal_confidence=0.8,
        signal_generated=True,
        trade_accepted=True,
        decision_reason="test decision",
        latest_candle_timestamp=datetime(
            2026,
            7,
            20,
            21,
            0,
            tzinfo=UTC,
        ),
        features=ObservationFeatures(
            candle_count=60,
            latest_close=100.0,
            ema_20=99.0,
            ema_50=98.0,
            ema_alignment="BULLISH",
            trend_state="UP",
            volatility_state="NORMAL",
            rsi_14=60.0,
            atr_14=1.0,
            atr_percent=1.0,
            range_position=0.8,
            setup_quality_score=80,
            setup_quality_label="STRONG",
        ),
        regime=ObservationRegime(
            trend="TRENDING",
            volatility="NORMAL",
            confidence=0.9,
            price_change_percent=2.0,
            volatility_ratio=1.0,
            candles_analysed=50,
        ),
        portfolio_context=PortfolioContext(
            pending_entries_total=1,
            portfolio_risk_percent=0.25,
        ),
    )


def append_completed_session(
    ledger_path,
    *,
    session_date: date = SESSION_DATE,
):
    append_event(
        ledger_path,
        "SESSION_COMPLETED",
        {
            "session_date": session_date.isoformat(),
            "observations_attempted": 1,
            "observations_recorded": 1,
            "broker_orders_sent": 0,
            "market_summaries": [
                {
                    "market": "AUD_JPY",
                    "pending_entry": True,
                    "candidate_risk_percent": 0.25,
                    "shadow_risk_percent": 0.5,
                }
            ],
        },
        occurred_at_utc=(
            RECORDED_AT.isoformat()
        ),
    )


def test_observation_report_reconciles_completed_session(
    tmp_path,
):
    ledger_path = tmp_path / "events.jsonl"
    observation_path = tmp_path / "observations.jsonl"
    append_completed_session(ledger_path)
    append_observation(
        observation_path,
        make_observation(),
    )

    report = build_observation_report(
        ledger_path=ledger_path,
        observation_path=observation_path,
    )

    assert report["status"] == "HEALTHY"
    assert report["observation_count"] == 1
    assert report["accepted_observations"] == 1
    assert report["session_reconciliation"] == [
        {
            "session_date": "2026-07-22",
            "expected": 1,
            "actual": 1,
            "matches": True,
        }
    ]
    assert report[
        "accepted_candidate_risk_percent_total"
    ] == 0.25
    assert report[
        "accepted_shadow_risk_percent_total"
    ] == 0.5
    assert report["network_calls_made"] == 0
    assert report["files_changed"] == 0
    assert report["safe_for_live_trading"] is False


def test_observation_report_flags_duplicates_and_orphans(
    tmp_path,
):
    ledger_path = tmp_path / "events.jsonl"
    observation_path = tmp_path / "observations.jsonl"
    append_completed_session(ledger_path)
    orphan = make_observation(
        session_date=date(2026, 7, 23),
    )
    append_observation(
        observation_path,
        orphan,
    )
    encoded = observation_path.read_text()
    observation_path.write_text(
        encoded + encoded
    )

    report = build_observation_report(
        ledger_path=ledger_path,
        observation_path=observation_path,
    )

    assert report["status"] == "INTEGRITY_ERROR"
    assert report["duplicate_observation_ids"] == [
        "a" * 64
    ]
    assert report["orphaned_session_dates"] == [
        "2026-07-23"
    ]
    assert report["mismatched_session_dates"] == [
        "2026-07-22"
    ]
