"""Tests for the read-only evidence cockpit API."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.analytics import router
from app.analytics.evidence_cockpit_reporting import (
    EvidenceCockpitError,
    build_evidence_cockpit,
)
from app.main import app
from app.paper_trading.ledger import append_event
from app.paper_trading.runtime_state import (
    add_pending_entry,
    build_pending_entry,
    empty_runtime_state,
    write_runtime_state,
)
from app.paper_trading.session_receipts import write_session_receipt

client = TestClient(app)


def test_cockpit_assembles_verified_lineage_and_next_action(tmp_path):
    ledger_path = tmp_path / "events.jsonl"
    state_path = tmp_path / "state.json"
    receipt_directory = tmp_path / "receipts"
    session_date = "2026-07-21"
    policy_fingerprint = "f" * 64

    started = append_event(
        ledger_path,
        "SESSION_STARTED",
        {
            "session_date": session_date,
            "software_commit": "abc1234",
            "policy_fingerprint": policy_fingerprint,
        },
    )
    completed = append_event(
        ledger_path,
        "SESSION_COMPLETED",
        {"session_date": session_date},
    )

    pending = build_pending_entry(
        market="AUD_JPY",
        signal_candle_timestamp=datetime(2026, 7, 20, 21, tzinfo=UTC),
        direction="BUY",
        candidate_risk_percent=0.25,
        shadow_risk_percent=0.5,
        directional_close_location=0.75,
        policy_fingerprint=policy_fingerprint,
        created_session_date=session_date,
    )
    state = add_pending_entry(empty_runtime_state(), pending)
    write_runtime_state(state_path, state)

    write_session_receipt(
        receipt_directory,
        session_date=session_date,
        software_commit="abc1234",
        policy_fingerprint=policy_fingerprint,
        runtime_health="HEALTHY",
        operator_status="OBSERVING",
        evidence_gate_status="NOT_READY",
        candidate_balance=10000,
        shadow_balance=10000,
        completed_sessions=1,
        broker_orders_sent=0,
        created_at_utc=datetime(2026, 7, 21, 22, tzinfo=UTC),
    )

    result = build_evidence_cockpit(
        ledger_path=ledger_path,
        state_path=state_path,
        receipt_directory=receipt_directory,
        health_report={
            "status": "HEALTHY",
            "candidate_balance": 10000,
            "shadow_balance": 10000,
            "broker_orders_sent": 0,
            "last_completed_session_date": session_date,
            "markets": {
                "AUD_JPY": {
                    "latest_timestamp": "2026-07-20T21:00:00Z",
                    "rows": 100,
                },
                "EUR_USD": {
                    "latest_timestamp": "2026-07-20T21:00:00Z",
                    "rows": 100,
                },
            },
        },
        operator_report={
            "status": "OBSERVING",
            "evidence_gate_status": "NOT_READY",
            "observation_integrity_status": "HEALTHY",
            "observations_recorded": 12,
            "observation_outcomes_populated": 0,
            "blocking_issues": [],
            "warnings": ["More evidence is required."],
            "observation_integrity_warnings": [],
        },
        readiness_report={"next_actions": ["Continue paper observation."]},
        git_snapshot_reader=lambda: ("abc1234", True),
        policy_verifier=lambda: policy_fingerprint,
        now_utc=datetime(2026, 7, 22, 12, tzinfo=UTC),
    )

    assert result["status"] == "HEALTHY"
    assert result["next_action"] == "WAIT_FOR_NEXT_COMPLETE_CANDLE"
    assert result["next_session_date"] == "2026-07-22"
    assert result["markets_aligned"] is True
    assert result["pending_entries"][0]["candidate_risk_percent"] == 0.25
    assert result["session_lineage"][0]["started_event_id"] == started["event_id"]
    assert result["session_lineage"][0]["completed_event_id"] == completed["event_id"]
    assert result["session_lineage"][0]["receipt_status"] == "VERIFIED"
    assert result["software_changed_since_last_session"] is False
    assert result["policy_matches_last_session"] is True
    assert result["broker_orders_sent"] == 0
    assert result["broker_orders_submitted"] == 0
    assert result["live_order_submission_permitted"] is False
    assert result["safe_for_live_trading"] is False


def test_cockpit_blocks_when_tracked_source_is_dirty(tmp_path):
    state_path = tmp_path / "state.json"
    write_runtime_state(state_path, empty_runtime_state())

    result = build_evidence_cockpit(
        ledger_path=tmp_path / "events.jsonl",
        state_path=state_path,
        receipt_directory=tmp_path / "receipts",
        health_report={"status": "HEALTHY", "markets": {}},
        operator_report={
            "status": "OBSERVING",
            "observation_integrity_status": "HEALTHY",
        },
        readiness_report={},
        git_snapshot_reader=lambda: ("abc1234", False),
        policy_verifier=lambda: "f" * 64,
        now_utc=datetime(2026, 7, 22, 12, tzinfo=UTC),
    )

    assert result["status"] == "BLOCKED"
    assert result["next_action"] == "RESOLVE_BLOCKING_ISSUES"
    assert result["blocking_issues"] == [
        "Tracked source contains uncommitted changes."
    ]


def test_cockpit_endpoint_preserves_safety_boundaries(monkeypatch):
    monkeypatch.setattr(
        router,
        "build_evidence_cockpit",
        lambda: {
            "schema_version": 1,
            "status": "HEALTHY",
            "generated_at_utc": "2026-07-22T12:00:00+00:00",
            "current_software_commit": "abc1234",
            "tracked_source_clean": True,
            "current_policy_fingerprint": "f" * 64,
            "next_action": "RUN_NEXT_GUARDED_PAPER_SESSION",
            "markets_aligned": True,
            "software_changed_since_last_session": False,
            "policy_matches_last_session": True,
            "safe_for_live_trading": False,
            "protocol_live_trading_permitted": False,
        },
    )

    response = client.get("/analytics/evidence-cockpit")

    assert response.status_code == 200
    result = response.json()
    assert result["network_calls_made"] == 0
    assert result["files_changed"] == 0
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0
    assert result["live_order_submission_permitted"] is False
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False


def test_cockpit_endpoint_returns_conflict_on_failure(monkeypatch):
    def fail():
        raise EvidenceCockpitError("Evidence could not be verified.")

    monkeypatch.setattr(router, "build_evidence_cockpit", fail)

    response = client.get("/analytics/evidence-cockpit")

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == (
        "Evidence could not be verified."
    )


def test_real_cockpit_is_read_only():
    response = client.get("/analytics/evidence-cockpit")

    assert response.status_code == 200
    result = response.json()
    assert result["broker_orders_sent"] == 0
    assert result["network_calls_made"] == 0
    assert result["files_changed"] == 0
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False
