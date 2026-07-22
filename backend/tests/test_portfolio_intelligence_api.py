"""Tests for read-only portfolio exposure and correlation intelligence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.analytics import router
from app.analytics.portfolio_intelligence_reporting import (
    PortfolioIntelligenceError,
    build_portfolio_intelligence_report,
)
from app.main import app
from app.market_data.models import Candle
from app.paper_trading.candle_store import write_candle_store
from app.paper_trading.runtime_state import (
    add_pending_entry,
    build_pending_entry,
    empty_runtime_state,
    write_runtime_state,
)

client = TestClient(app)


def make_candles(symbol: str, closes: list[float]) -> list[Candle]:
    start = datetime(2026, 1, 1, 21, tzinfo=UTC)
    return [
        Candle(
            symbol=symbol,
            timeframe="D",
            timestamp=start + timedelta(days=index),
            open=close,
            high=close + 0.1,
            low=close - 0.1,
            close=close,
            volume=1000,
        )
        for index, close in enumerate(closes)
    ]


def test_portfolio_report_calculates_exposure_and_correlation(tmp_path):
    state_path = tmp_path / "state.json"
    candle_directory = tmp_path / "candles"
    policy_fingerprint = "f" * 64
    pending = build_pending_entry(
        market="AUD_JPY",
        signal_candle_timestamp=datetime(2026, 1, 22, 21, tzinfo=UTC),
        direction="BUY",
        candidate_risk_percent=0.25,
        shadow_risk_percent=0.5,
        directional_close_location=0.75,
        policy_fingerprint=policy_fingerprint,
        created_session_date="2026-01-22",
    )
    write_runtime_state(
        state_path,
        add_pending_entry(empty_runtime_state(), pending),
    )

    candle_directory.mkdir()
    write_candle_store(
        candle_directory / "AUD_JPY.csv",
        make_candles("AUD_JPY", [100 + index for index in range(22)]),
        expected_symbol="AUD_JPY",
    )
    write_candle_store(
        candle_directory / "CAD_JPY.csv",
        make_candles("CAD_JPY", [80 + index * 0.8 for index in range(22)]),
        expected_symbol="CAD_JPY",
    )

    result = build_portfolio_intelligence_report(
        state_path=state_path,
        candle_directory=candle_directory,
        minimum_aligned_returns=20,
        now_utc=datetime(2026, 1, 23, 12, tzinfo=UTC),
    )

    assert result["status"] == "AVAILABLE"
    assert result["candidate_gross_risk_percent"] == 0.25
    assert result["shadow_gross_risk_percent"] == 0.5
    assert result["candidate_currency_gross_exposure_percent"] == 0.5
    assert result["candidate_currency_exposure"] == [
        {
            "currency": "AUD",
            "signed_risk_percent": 0.25,
            "side": "LONG",
            "absolute_risk_percent": 0.25,
        },
        {
            "currency": "JPY",
            "signed_risk_percent": -0.25,
            "side": "SHORT",
            "absolute_risk_percent": 0.25,
        },
    ]
    pair = result["correlations"][0]
    assert pair["status"] == "AVAILABLE"
    assert pair["aligned_return_count"] == 21
    assert pair["correlation"] is not None
    assert pair["correlation"] > 0.99
    assert pair["strength"] == "HIGH"


def test_portfolio_report_refuses_sparse_correlation(tmp_path):
    state_path = tmp_path / "state.json"
    candle_directory = tmp_path / "candles"
    write_runtime_state(state_path, empty_runtime_state())
    candle_directory.mkdir()

    for symbol in ("EUR_GBP", "EUR_JPY"):
        write_candle_store(
            candle_directory / f"{symbol}.csv",
            make_candles(symbol, [1.0, 1.1, 1.2, 1.3, 1.4]),
            expected_symbol=symbol,
        )

    result = build_portfolio_intelligence_report(
        state_path=state_path,
        candle_directory=candle_directory,
    )

    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["available_correlation_pair_count"] == 0
    assert result["correlations"][0]["aligned_return_count"] == 4
    assert result["correlations"][0]["correlation"] is None
    assert result["correlations"][0]["strength"] == "UNAVAILABLE"


def test_portfolio_endpoint_returns_conflict_on_failure(monkeypatch):
    def fail():
        raise PortfolioIntelligenceError("Portfolio evidence is unavailable.")

    monkeypatch.setattr(router, "build_portfolio_intelligence_report", fail)

    response = client.get("/analytics/portfolio-intelligence")

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == (
        "Portfolio evidence is unavailable."
    )


def test_real_portfolio_endpoint_is_read_only():
    response = client.get("/analytics/portfolio-intelligence")

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["minimum_aligned_returns_required"] == 20
    assert result["broker_orders_sent"] == 0
    assert result["network_calls_made"] == 0
    assert result["files_changed"] == 0
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False
