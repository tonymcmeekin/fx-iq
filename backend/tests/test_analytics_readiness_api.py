"""Tests for the read-only readiness API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.analytics import readiness_reporting
from app.main import app

client = TestClient(app)


def operator_report() -> dict:
    return {
        "status": "OBSERVING",
        "evidence_gate_status": "NOT_READY",
        "completed_sessions": 8,
        "minimum_completed_sessions_required": 20,
        "positions_closed": 14,
        "minimum_closed_trades_required": 50,
        "earliest_eligible_assessment_date": ("2027-07-14"),
        "safe_to_continue_paper_observation": True,
        "warnings": ["More evidence is required."],
        "observation_integrity_status": "HEALTHY",
        "observations_recorded": 12,
        "observation_outcomes_populated": 0,
        "observation_integrity_warnings": [
            "No observation outcomes are populated yet.",
        ],
        "blocking_issues": [],
        "protocol_failed_criteria": [],
        "protocol_unevaluable_criteria": ["Minimum duration not reached."],
        "protocol_immediate_stop_reasons": [],
    }


def test_readiness_returns_protocol_progress(
    monkeypatch,
):
    monkeypatch.setattr(
        readiness_reporting,
        "build_operator_status",
        operator_report,
    )

    response = client.get("/analytics/readiness")

    assert response.status_code == 200

    result = response.json()

    assert result["status"] == "OBSERVING"
    assert result["current_stage"] == "PROTOCOL_OBSERVATION"
    assert result["progress"]["completed_sessions"]["current"] == 8
    assert result["progress"]["completed_sessions"]["required"] == 20
    assert result["progress"]["closed_trades"]["current"] == 14
    assert result["progress"]["closed_trades"]["required"] == 50
    assert result["paper_observation_allowed"] is True
    assert result["live_trading_allowed"] is False
    assert result["observation_integrity_status"] == "HEALTHY"
    assert result["observations_recorded"] == 12
    assert result["observation_outcomes_populated"] == 0
    assert result["observation_integrity_warnings"] == [
        "No observation outcomes are populated yet.",
    ]


def test_readiness_uses_real_protocol_thresholds(
    monkeypatch,
):
    report = operator_report()
    report["minimum_completed_sessions_required"] = 30
    report["minimum_closed_trades_required"] = 80

    monkeypatch.setattr(
        readiness_reporting,
        "build_operator_status",
        lambda: report,
    )

    result = client.get("/analytics/readiness").json()

    assert result["progress"]["completed_sessions"]["required"] == 30
    assert result["progress"]["closed_trades"]["required"] == 80


def test_readiness_enters_safety_review(
    monkeypatch,
):
    report = operator_report()
    report["blocking_issues"] = ["Ledger integrity check failed."]
    report["safe_to_continue_paper_observation"] = False

    monkeypatch.setattr(
        readiness_reporting,
        "build_operator_status",
        lambda: report,
    )

    result = client.get("/analytics/readiness").json()

    assert result["current_stage"] == "SAFETY_REVIEW"
    assert result["paper_observation_allowed"] is False
    assert result["live_trading_allowed"] is False


def test_readiness_preserves_safety_boundaries(
    monkeypatch,
):
    report = operator_report()
    report["safe_for_live_trading"] = True
    report["protocol_live_trading_permitted"] = True

    monkeypatch.setattr(
        readiness_reporting,
        "build_operator_status",
        lambda: report,
    )

    result = client.get("/analytics/readiness").json()

    assert result["live_trading_allowed"] is False
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False
    assert result["network_calls_made"] == 0
    assert result["files_changed"] == 0
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0


def test_readiness_returns_conflict_on_failure(
    monkeypatch,
):
    def fail():
        raise RuntimeError("Operator report unavailable.")

    monkeypatch.setattr(
        readiness_reporting,
        "build_operator_status",
        fail,
    )

    response = client.get("/analytics/readiness")

    assert response.status_code == 409

    detail = response.json()["detail"]

    assert detail["status"] == "ERROR"
    assert detail["error"] == "Operator report unavailable."
    assert detail["safe_for_live_trading"] is False
    assert detail["protocol_live_trading_permitted"] is False


def test_real_readiness_is_read_only():
    response = client.get("/analytics/readiness")

    assert response.status_code == 200

    result = response.json()

    assert result["live_trading_allowed"] is False
    assert result["network_calls_made"] == 0
    assert result["files_changed"] == 0
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False
