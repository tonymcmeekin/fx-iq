"""Tests for the read-only analytics overview API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.analytics import overview_reporting
from app.analytics.attribution_reporting import (
    AttributionReportError,
)
from app.main import app

client = TestClient(app)


def health_report() -> dict:
    return {
        "status": "HEALTHY",
        "candidate_balance": 10125.0,
        "shadow_balance": 10000.0,
        "open_positions": 1,
        "pending_entries": 2,
        "last_completed_session_date": "2026-07-17",
        "broker_orders_sent": 0,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
    }


def attribution_report() -> dict:
    return {
        "source": "verified_paper_ledger",
        "completed_trade_count": 5,
        "overall": {
            "net_profit_percent": 1.25,
            "win_rate_percent": 60.0,
        },
        "by_strategy": [
            {
                "strategy": "simple_trend",
                "net_profit_percent": -0.5,
                "total_trades": 2,
                "win_rate_percent": 50.0,
            },
            {
                "strategy": "atr_breakout",
                "net_profit_percent": 1.75,
                "total_trades": 3,
                "win_rate_percent": 66.67,
            },
        ],
        "ledger_writes_performed": 0,
        "broker_orders_submitted": 0,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
    }


def test_overview_returns_combined_verified_reports(
    monkeypatch,
):
    monkeypatch.setattr(
        overview_reporting,
        "perform_health_report",
        health_report,
    )
    monkeypatch.setattr(
        overview_reporting,
        "perform_attribution_report",
        attribution_report,
    )

    response = client.get("/analytics/overview")

    assert response.status_code == 200

    result = response.json()

    assert result["status"] == "HEALTHY"
    assert result["summary"]["candidate_balance"] == 10125.0
    assert result["summary"]["shadow_balance"] == 10000.0
    assert result["summary"]["open_positions"] == 1
    assert result["summary"]["pending_entries"] == 2
    assert result["summary"]["completed_trade_count"] == 5
    assert result["summary"]["net_profit_percent"] == 1.25
    assert result["summary"]["win_rate_percent"] == 60.0
    assert result["summary"]["best_strategy"]["strategy"] == "atr_breakout"
    assert result["runtime"]["status"] == "HEALTHY"
    assert result["strategy_attribution"]["source"] == "verified_paper_ledger"


def test_overview_preserves_safety_boundaries(
    monkeypatch,
):
    unsafe_health = health_report()
    unsafe_health["safe_for_live_trading"] = True
    unsafe_health["protocol_live_trading_permitted"] = True

    unsafe_attribution = attribution_report()
    unsafe_attribution["safe_for_live_trading"] = True
    unsafe_attribution["protocol_live_trading_permitted"] = True

    monkeypatch.setattr(
        overview_reporting,
        "perform_health_report",
        lambda: unsafe_health,
    )
    monkeypatch.setattr(
        overview_reporting,
        "perform_attribution_report",
        lambda: unsafe_attribution,
    )

    response = client.get("/analytics/overview")
    result = response.json()

    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False
    assert result["safety"]["safe_for_live_trading"] is False
    assert result["safety"]["protocol_live_trading_permitted"] is False
    assert result["safety"]["network_calls_made"] == 0
    assert result["safety"]["files_changed"] == 0
    assert result["safety"]["ledger_writes_performed"] == 0
    assert result["safety"]["broker_orders_submitted"] == 0


def test_overview_handles_no_completed_trades(
    monkeypatch,
):
    empty_attribution = attribution_report()
    empty_attribution["completed_trade_count"] = 0
    empty_attribution["by_strategy"] = []
    empty_attribution["overall"] = {
        "net_profit_percent": 0,
        "win_rate_percent": None,
    }

    monkeypatch.setattr(
        overview_reporting,
        "perform_health_report",
        health_report,
    )
    monkeypatch.setattr(
        overview_reporting,
        "perform_attribution_report",
        lambda: empty_attribution,
    )

    response = client.get("/analytics/overview")

    assert response.status_code == 200

    summary = response.json()["summary"]

    assert summary["completed_trade_count"] == 0
    assert summary["best_strategy"] is None
    assert summary["net_profit_percent"] == 0
    assert summary["win_rate_percent"] is None


def test_overview_returns_conflict_when_report_fails(
    monkeypatch,
):
    def fail_attribution():
        raise AttributionReportError("Ledger integrity check failed.")

    monkeypatch.setattr(
        overview_reporting,
        "perform_health_report",
        health_report,
    )
    monkeypatch.setattr(
        overview_reporting,
        "perform_attribution_report",
        fail_attribution,
    )

    response = client.get("/analytics/overview")

    assert response.status_code == 409

    detail = response.json()["detail"]

    assert detail["status"] == "ERROR"
    assert detail["error"] == "Ledger integrity check failed."
    assert detail["network_calls_made"] == 0
    assert detail["files_changed"] == 0
    assert detail["ledger_writes_performed"] == 0
    assert detail["broker_orders_submitted"] == 0
    assert detail["safe_for_live_trading"] is False
    assert detail["protocol_live_trading_permitted"] is False


def test_overview_accepts_no_runtime_paths(
    monkeypatch,
):
    monkeypatch.setattr(
        overview_reporting,
        "perform_health_report",
        health_report,
    )
    monkeypatch.setattr(
        overview_reporting,
        "perform_attribution_report",
        attribution_report,
    )

    response = client.get(
        "/analytics/overview",
        params={
            "ledger_path": "/tmp/other-ledger.jsonl",
            "state_path": "/tmp/other-state.json",
        },
    )

    assert response.status_code == 200
    assert response.json()["summary"]["candidate_balance"] == 10125.0
