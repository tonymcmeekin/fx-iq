"""Tests for deterministic readiness explanations."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.analytics import (
    readiness_explanation_reporting,
)
from app.main import app

client = TestClient(app)


def readiness_report() -> dict:
    return {
        "status": "OBSERVING",
        "current_stage": "PROTOCOL_OBSERVATION",
        "paper_observation_allowed": True,
        "blocking_issues": [],
        "warnings": ["More evidence is required."],
        "failed_criteria": ["sample_size_gate"],
        "unevaluable_criteria": ["profit_factor_gate"],
        "immediate_stop_reasons": [],
        "next_actions": ["Complete additional paper sessions."],
        "progress": {
            "completed_sessions": {
                "current": 1,
                "required": 20,
                "remaining": 19,
                "requirement_met": False,
            },
            "closed_trades": {
                "current": 0,
                "required": 50,
                "remaining": 50,
                "requirement_met": False,
            },
            "calendar_requirement": {
                "earliest_eligible_assessment_date": ("2027-07-14"),
                "requirement_met": False,
            },
        },
    }


def test_explanation_returns_operator_briefing(
    monkeypatch,
):
    monkeypatch.setattr(
        readiness_explanation_reporting,
        "build_readiness_report",
        readiness_report,
    )

    response = client.get("/analytics/readiness-explanation")

    assert response.status_code == 200

    result = response.json()

    assert result["headline"] == "Trade IQ readiness briefing"
    assert "prospective paper observation" in result["status_summary"].lower()
    assert "19 additional sessions" in result["requirement_summary"]
    assert "50 additional closed trades" in result["requirement_summary"]
    assert "2027-07-14" in result["progress_summary"][2]


def test_explanation_reports_evidence_state(
    monkeypatch,
):
    monkeypatch.setattr(
        readiness_explanation_reporting,
        "build_readiness_report",
        readiness_report,
    )

    result = client.get("/analytics/readiness-explanation").json()

    assert result["evidence_summary"] == (
        "1 protocol criteria have failed and 1 remain unevaluable."
    )


def test_explanation_enters_safety_review(
    monkeypatch,
):
    report = readiness_report()
    report["current_stage"] = "SAFETY_REVIEW"
    report["paper_observation_allowed"] = False
    report["blocking_issues"] = ["Ledger integrity failure."]

    monkeypatch.setattr(
        readiness_explanation_reporting,
        "build_readiness_report",
        lambda: report,
    )

    result = client.get("/analytics/readiness-explanation").json()

    assert "safety review" in result["status_summary"].lower()
    assert result["paper_observation_allowed"] is False


def test_explanation_preserves_safety_boundaries(
    monkeypatch,
):
    report = readiness_report()
    report["safe_for_live_trading"] = True
    report["protocol_live_trading_permitted"] = True
    report["live_trading_allowed"] = True

    monkeypatch.setattr(
        readiness_explanation_reporting,
        "build_readiness_report",
        lambda: report,
    )

    result = client.get("/analytics/readiness-explanation").json()

    assert result["live_trading_allowed"] is False
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False
    assert result["network_calls_made"] == 0
    assert result["files_changed"] == 0
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0


def test_explanation_returns_conflict_on_failure(
    monkeypatch,
):
    def fail():
        raise RuntimeError("Readiness report unavailable.")

    monkeypatch.setattr(
        readiness_explanation_reporting,
        "build_readiness_report",
        fail,
    )

    response = client.get("/analytics/readiness-explanation")

    assert response.status_code == 409

    detail = response.json()["detail"]

    assert detail["status"] == "ERROR"
    assert detail["error"] == "Readiness report unavailable."
    assert detail["safe_for_live_trading"] is False
    assert detail["protocol_live_trading_permitted"] is False


def test_real_explanation_is_read_only():
    response = client.get("/analytics/readiness-explanation")

    assert response.status_code == 200

    result = response.json()

    assert result["live_trading_allowed"] is False
    assert result["network_calls_made"] == 0
    assert result["files_changed"] == 0
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False
    assert "live trading" in result["safety_statement"].lower()


def test_explanation_is_deterministic(
    monkeypatch,
):
    monkeypatch.setattr(
        readiness_explanation_reporting,
        "build_readiness_report",
        readiness_report,
    )

    first = client.get("/analytics/readiness-explanation").json()
    second = client.get("/analytics/readiness-explanation").json()

    assert first == second
