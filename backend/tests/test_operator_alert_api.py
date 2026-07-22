"""Tests for notification-only operator alerts."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.analytics import router
from app.analytics.operator_alert_reporting import (
    OperatorAlertReportError,
    build_operator_alert_report,
)
from app.main import app

client = TestClient(app)


def cockpit_report() -> dict:
    return {
        "current_software_commit": "abc1234",
        "current_policy_fingerprint": "f" * 64,
        "next_session_date": "2026-07-23",
        "next_action": "RESOLVE_BLOCKING_ISSUES",
        "markets_aligned": False,
        "markets": [
            {
                "market": "AUD_JPY",
                "latest_complete_timestamp": None,
                "stored_candles": 0,
            }
        ],
        "pending_entries": [
            {
                "market": "EUR_USD",
                "signal_candle_timestamp": "2026-07-21T21:00:00Z",
            }
        ],
        "open_positions": [
            {
                "market": "GBP_USD",
                "entry_timestamp": "2026-07-20T21:00:00Z",
            }
        ],
        "blocking_issues": ["Ledger verification failed."],
        "warnings": ["More evidence is required."],
    }


def test_alert_report_covers_active_operator_conditions():
    result = build_operator_alert_report(
        cockpit_report=cockpit_report(),
        now_utc=datetime(2026, 7, 22, 12, tzinfo=UTC),
    )

    alert_types = {alert["alert_type"] for alert in result["alerts"]}

    assert result["status"] == "ATTENTION_REQUIRED"
    assert result["active_alert_count"] == 6
    assert result["critical_alert_count"] == 3
    assert result["warning_alert_count"] == 1
    assert alert_types == {
        "INTEGRITY_BLOCKER",
        "MARKET_DATA_CONFLICT",
        "MARKET_DATA_UNAVAILABLE",
        "PENDING_ENTRY_AWAITING_CANDLE",
        "PAPER_POSITION_MONITORING",
        "EVIDENCE_WARNING",
    }
    assert all(
        alert["delivery_mode"] == "NOTIFICATION_ONLY"
        and alert["order_action_permitted"] is False
        and alert["software_commit"] == "abc1234"
        and alert["policy_fingerprint"] == "f" * 64
        for alert in result["alerts"]
    )


def test_alert_ids_are_stable_until_source_evidence_changes():
    first = build_operator_alert_report(
        cockpit_report=cockpit_report(),
        now_utc=datetime(2026, 7, 22, 12, tzinfo=UTC),
    )
    second = build_operator_alert_report(
        cockpit_report=cockpit_report(),
        now_utc=datetime(2026, 7, 22, 13, tzinfo=UTC),
    )

    assert [alert["alert_id"] for alert in first["alerts"]] == [
        alert["alert_id"] for alert in second["alerts"]
    ]
    assert first["generated_at_utc"] != second["generated_at_utc"]


def test_alert_report_marks_guarded_session_eligibility():
    cockpit = cockpit_report()
    cockpit.update(
        {
            "next_action": "RUN_NEXT_GUARDED_PAPER_SESSION",
            "markets_aligned": True,
            "markets": [
                {
                    "market": "EUR_USD",
                    "latest_complete_timestamp": "2026-07-21T21:00:00Z",
                }
            ],
            "pending_entries": [],
            "open_positions": [],
            "blocking_issues": [],
            "warnings": [],
        }
    )

    result = build_operator_alert_report(cockpit_report=cockpit)

    assert result["status"] == "ACTIVE"
    assert result["active_alert_count"] == 1
    assert result["alerts"][0]["alert_type"] == "PAPER_SESSION_ELIGIBLE"
    assert result["alerts"][0]["evidence_timestamp_utc"] == (
        "2026-07-21T21:00:00Z"
    )


def test_alert_endpoint_preserves_read_only_boundaries(monkeypatch):
    monkeypatch.setattr(
        router,
        "build_operator_alert_report",
        lambda: build_operator_alert_report(cockpit_report=cockpit_report()),
    )

    response = client.get("/analytics/alerts")

    assert response.status_code == 200
    result = response.json()
    assert result["delivery_mode"] == "NOTIFICATION_ONLY"
    assert result["network_calls_made"] == 0
    assert result["files_changed"] == 0
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False


def test_alert_endpoint_returns_conflict_on_failure(monkeypatch):
    def fail():
        raise OperatorAlertReportError("Alert evidence is unavailable.")

    monkeypatch.setattr(router, "build_operator_alert_report", fail)

    response = client.get("/analytics/alerts")

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == (
        "Alert evidence is unavailable."
    )


def test_real_alert_endpoint_is_read_only():
    response = client.get("/analytics/alerts")

    assert response.status_code == 200
    result = response.json()
    assert result["delivery_mode"] == "NOTIFICATION_ONLY"
    assert result["network_calls_made"] == 0
    assert result["files_changed"] == 0
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False
