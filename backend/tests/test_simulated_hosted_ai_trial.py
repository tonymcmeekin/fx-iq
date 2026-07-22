"""Offline end-to-end exercise of the optional hosted-AI contract."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.ai_briefing.simulation import run_simulated_hosted_trial
from app.main import app


def trial_reports():
    return (
        {
            "status": "HEALTHY",
            "current_software_commit": "abc1234",
            "current_policy_fingerprint": "f" * 64,
            "next_action": "WAIT_FOR_NEXT_COMPLETE_CANDLE",
            "last_completed_session_date": "2026-07-21",
            "next_session_date": "2026-07-22",
            "pending_entries": [{"market": "AUD_JPY"}],
            "open_positions": [],
            "observations_recorded": 12,
            "observation_outcomes_populated": 0,
            "broker_orders_sent": 0,
            "blocking_issues": [],
            "warnings": [],
            "markets_aligned": True,
            "oanda_account_id": "must-never-leave",
        },
        {"alerts": []},
        {
            "generated_at_utc": "2026-07-22T12:00:00Z",
            "status": "INSUFFICIENT_DATA",
            "pending_entry_count": 1,
            "open_position_count": 0,
            "candidate_gross_risk_percent": 0.25,
            "correlation_pair_count": 15,
            "available_correlation_pair_count": 0,
            "minimum_aligned_returns_required": 20,
            "correlations": [{"aligned_return_count": 4}],
        },
        {
            "generated_at_utc": "2026-07-22T12:00:00Z",
            "status": "INSUFFICIENT_DATA",
            "outcome_count": 0,
            "minimum_overall_sample": 20,
            "available_group_count": 0,
            "integrity_status": "HEALTHY",
        },
        {
            "annotations": [
                {
                    "annotation_id": "a" * 64,
                    "sequence": 1,
                    "subject_type": "ALERT",
                    "subject_id": "b" * 64,
                    "category": "REVIEW",
                    "created_at_utc": "2026-07-22T11:00:00Z",
                    "note": "must-also-never-leave",
                }
            ]
        },
    )


def test_simulated_hosted_trial_is_local_temporary_and_guarded():
    result = run_simulated_hosted_trial(
        reports=trial_reports(),
        now_utc=datetime(2026, 7, 22, 12, tzinfo=UTC),
    )

    assert result["status"] == "PASS"
    assert result["external_network_calls_made"] == 0
    assert result["persistent_runtime_files_changed"] == 0
    assert result["broker_orders_submitted"] == 0
    assert result["request_storage_enabled"] is False
    assert result["quality_gate"] == "PASS"
    assert result["governance_status"] == "REVIEW_REQUIRED"
    assert all(result["checks"].values())


def test_simulated_hosted_trial_endpoint_is_explicit_and_guarded():
    response = TestClient(app).post("/ai/simulated-hosted-trial")

    assert response.status_code == 200
    assert response.json()["status"] == "PASS"
    assert response.json()["external_network_calls_made"] == 0
    assert response.json()["persistent_runtime_files_changed"] == 0
    assert response.json()["broker_orders_submitted"] == 0
    schema = app.openapi()["paths"]["/ai/simulated-hosted-trial"]["post"]
    assert schema["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/SimulatedHostedTrialResponse")
