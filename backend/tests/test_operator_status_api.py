"""Tests for the read-only operator-status API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.analytics import operator_status_reporting
from app.main import app

client = TestClient(app)


def operator_report() -> dict:
    return {
        "status": "OBSERVING",
        "runtime_health": "HEALTHY",
        "performance_status": "INSUFFICIENT_DATA",
        "rolling_analytics_status": "INSUFFICIENT_DATA",
        "observation_integrity_status": "HEALTHY",
        "observations_recorded": 6,
        "observation_outcomes_populated": 0,
        "observation_integrity_warnings": [
            "No observation outcomes are populated yet.",
        ],
        "completed_sessions": 1,
        "positions_closed": 0,
        "candidate_balance": 10000.0,
        "shadow_balance": 10000.0,
        "evidence_gate_status": "NOT_READY",
        "safe_to_continue_paper_observation": True,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
        "broker_orders_sent": 0,
        "warnings": [
            "Only 1 completed prospective session is available.",
        ],
        "blocking_issues": [],
    }


def test_operator_status_endpoint_returns_report(
    monkeypatch,
):
    monkeypatch.setattr(
        operator_status_reporting,
        "build_operator_status",
        operator_report,
    )

    response = client.get("/analytics/operator-status")

    assert response.status_code == 200

    result = response.json()

    assert result["status"] == "OBSERVING"
    assert result["runtime_health"] == "HEALTHY"
    assert result["completed_sessions"] == 1
    assert result["evidence_gate_status"] == "NOT_READY"
    assert result["safe_to_continue_paper_observation"] is True
    assert result["observation_integrity_status"] == "HEALTHY"
    assert result["observations_recorded"] == 6
    assert result["observation_outcomes_populated"] == 0


def test_operator_status_preserves_safety_boundaries(
    monkeypatch,
):
    unsafe_report = operator_report()
    unsafe_report["safe_for_live_trading"] = True
    unsafe_report["protocol_live_trading_permitted"] = True

    monkeypatch.setattr(
        operator_status_reporting,
        "build_operator_status",
        lambda: unsafe_report,
    )

    response = client.get("/analytics/operator-status")
    result = response.json()

    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False
    assert result["network_calls_made"] == 0
    assert result["files_changed"] == 0
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0


def test_operator_status_accepts_no_runtime_paths(
    monkeypatch,
):
    monkeypatch.setattr(
        operator_status_reporting,
        "build_operator_status",
        operator_report,
    )

    response = client.get(
        "/analytics/operator-status",
        params={
            "ledger_path": "/tmp/other-ledger.jsonl",
            "state_path": "/tmp/other-state.json",
            "protocol_path": "/tmp/other-protocol.json",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "OBSERVING"


def test_operator_status_returns_conflict_on_failure(
    monkeypatch,
):
    def fail_report():
        raise RuntimeError("Operator status could not be produced.")

    monkeypatch.setattr(
        operator_status_reporting,
        "build_operator_status",
        fail_report,
    )

    response = client.get("/analytics/operator-status")

    assert response.status_code == 409

    detail = response.json()["detail"]

    assert detail["status"] == "ERROR"
    assert detail["error"] == "Operator status could not be produced."
    assert detail["network_calls_made"] == 0
    assert detail["files_changed"] == 0
    assert detail["ledger_writes_performed"] == 0
    assert detail["broker_orders_submitted"] == 0
    assert detail["safe_for_live_trading"] is False
    assert detail["protocol_live_trading_permitted"] is False


def test_real_operator_status_is_read_only():
    response = client.get("/analytics/operator-status")

    assert response.status_code == 200

    result = response.json()

    assert result["broker_orders_sent"] == 0
    assert result["network_calls_made"] == 0
    assert result["files_changed"] == 0
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False
