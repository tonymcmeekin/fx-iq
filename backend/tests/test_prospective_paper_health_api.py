"""Tests for the read-only prospective paper health API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.analytics import prospective_health_reporting
from app.main import app
from scripts.check_prospective_paper_health import PaperHealthError

client = TestClient(app)


def healthy_report() -> dict:
    return {
        "status": "HEALTHY",
        "ledger_events": 14,
        "completed_sessions": 1,
        "latest_completed_session": "2026-07-17",
        "candidate_balance": 10000.0,
        "shadow_balance": 10000.0,
        "broker_orders_sent": 0,
        "network_calls_made": 0,
        "files_changed": 0,
    }


def test_health_endpoint_returns_verified_report(
    monkeypatch,
):
    monkeypatch.setattr(
        prospective_health_reporting,
        "perform_health_check",
        healthy_report,
    )

    response = client.get("/analytics/prospective-paper-health")

    assert response.status_code == 200

    result = response.json()

    assert result["status"] == "HEALTHY"
    assert result["ledger_events"] == 14
    assert result["completed_sessions"] == 1
    assert result["broker_orders_sent"] == 0
    assert result["report_network_calls_made"] == 0
    assert result["report_files_changed"] == 0
    assert result["report_ledger_writes_performed"] == 0
    assert result["report_broker_orders_submitted"] == 0
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False


def test_health_endpoint_returns_conflict_when_unhealthy(
    monkeypatch,
):
    def fail_health_check():
        raise PaperHealthError("Ledger integrity check failed.")

    monkeypatch.setattr(
        prospective_health_reporting,
        "perform_health_check",
        fail_health_check,
    )

    response = client.get("/analytics/prospective-paper-health")

    assert response.status_code == 409

    detail = response.json()["detail"]

    assert detail["status"] == "UNHEALTHY"
    assert detail["error"] == "Ledger integrity check failed."
    assert detail["network_calls_made"] == 0
    assert detail["files_changed"] == 0
    assert detail["ledger_writes_performed"] == 0
    assert detail["broker_orders_submitted"] == 0
    assert detail["safe_for_live_trading"] is False
    assert detail["protocol_live_trading_permitted"] is False


def test_health_endpoint_accepts_no_runtime_paths(
    monkeypatch,
):
    monkeypatch.setattr(
        prospective_health_reporting,
        "perform_health_check",
        healthy_report,
    )

    response = client.get(
        "/analytics/prospective-paper-health",
        params={
            "ledger_path": "/tmp/other-ledger.jsonl",
            "state_path": "/tmp/other-state.json",
            "journal_path": "/tmp/other-journal.json",
        },
    )

    assert response.status_code == 200
    assert response.json()["ledger_events"] == 14


def test_health_endpoint_preserves_existing_safety_values(
    monkeypatch,
):
    report = healthy_report()
    report["safe_for_live_trading"] = True
    report["protocol_live_trading_permitted"] = True

    monkeypatch.setattr(
        prospective_health_reporting,
        "perform_health_check",
        lambda: report,
    )

    response = client.get("/analytics/prospective-paper-health")

    result = response.json()

    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False
