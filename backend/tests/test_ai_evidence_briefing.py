"""Guardrails for the offline-first AI evidence analyst."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.ai_briefing import router
from app.ai_briefing.evidence import build_sanitized_snapshot
from app.ai_briefing.models import BriefingGenerateRequest
from app.ai_briefing.providers import (
    DeterministicEvidenceProvider,
    OpenAIResponsesProvider,
)
from app.ai_briefing.service import (
    EvidenceBriefingError,
    build_ai_governance_report,
    build_evidence_briefing,
    build_provider_readiness_report,
    generate_and_store_insight,
)
from app.ai_briefing.store import InsightStoreError, read_insights
from app.main import app
from app.operator_review.models import AnnotationRequest
from app.operator_review.service import create_operator_annotation

NOW = datetime(2026, 7, 22, 12, tzinfo=UTC)


def reports():
    cockpit = {
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
    }
    alerts = {
        "alerts": [
            {
                "alert_id": "a" * 64,
                "alert_type": "PENDING_ENTRY_AWAITING_CANDLE",
                "severity": "INFO",
                "market": "AUD_JPY",
                "session_date": "2026-07-22",
                "requires_operator_action": False,
                "message": "not selected",
            }
        ]
    }
    portfolio = {
        "generated_at_utc": "2026-07-22T12:00:00Z",
        "status": "INSUFFICIENT_DATA",
        "pending_entry_count": 1,
        "open_position_count": 0,
        "candidate_gross_risk_percent": 0.25,
        "correlation_pair_count": 15,
        "available_correlation_pair_count": 0,
        "minimum_aligned_returns_required": 20,
        "correlations": [{"aligned_return_count": 4}],
    }
    outcomes = {
        "generated_at_utc": "2026-07-22T12:00:00Z",
        "status": "INSUFFICIENT_DATA",
        "outcome_count": 0,
        "minimum_overall_sample": 20,
        "available_group_count": 0,
        "integrity_status": "HEALTHY",
    }
    annotations = {
        "annotations": [
            {
                "annotation_id": "b" * 64,
                "sequence": 1,
                "subject_type": "ALERT",
                "subject_id": "a" * 64,
                "category": "REVIEW",
                "created_at_utc": "2026-07-22T11:00:00Z",
                "note": "private operator context",
            }
        ]
    }
    return cockpit, alerts, portfolio, outcomes, annotations


def test_snapshot_excludes_credentials_notes_and_raw_text():
    snapshot = build_sanitized_snapshot(
        cockpit=reports()[0],
        alerts=reports()[1],
        portfolio=reports()[2],
        outcomes=reports()[3],
        annotations=reports()[4],
        now_utc=NOW,
    )
    encoded = snapshot.model_dump_json()

    assert "must-never-leave" not in encoded
    assert "private operator context" not in encoded
    assert "not selected" not in encoded
    assert "broker account identifiers" in encoded


def test_offline_briefing_is_sparse_safe_and_cited():
    result = build_evidence_briefing(reports=reports(), now_utc=NOW)

    assert result["provider_mode"] == "OFFLINE"
    assert result["safety"]["network_calls_made"] == 0
    assert "cannot support a performance conclusion" in result["briefing"]["headline"]
    assert "0/20" in result["briefing"]["why_waiting"][0]
    assert any("AUD_JPY" in item for item in result["briefing"]["what_changed"])
    assert len(result["briefing"]["citations"]) == 3
    assert result["safety"]["broker_orders_submitted"] == 0


def test_hosted_adapter_sends_only_snapshot_and_requires_structured_output():
    captured = {}

    def transport(url, headers, body, timeout):
        captured.update(json.loads(body))
        assert headers["Authorization"] == "Bearer test-key"
        return {
            "output_text": json.dumps(
                DeterministicEvidenceProvider()
                .generate(
                    build_sanitized_snapshot(
                        cockpit=reports()[0],
                        alerts=reports()[1],
                        portfolio=reports()[2],
                        outcomes=reports()[3],
                        annotations=reports()[4],
                        now_utc=NOW,
                    )
                )
                .model_dump(mode="json")
            )
        }

    provider = OpenAIResponsesProvider(api_key="test-key", model="test-model", transport=transport)
    result = build_evidence_briefing(reports=reports(), provider=provider, now_utc=NOW)

    assert result["provider_mode"] == "OPENAI"
    assert result["safety"]["network_calls_made"] == 1
    assert captured["store"] is False
    assert captured["text"]["format"]["type"] == "json_schema"
    assert "must-never-leave" not in captured["input"]
    assert "private operator context" not in captured["input"]


def test_hosted_adapter_fails_closed_on_invalid_output():
    provider = OpenAIResponsesProvider(
        api_key="test-key",
        model="test-model",
        transport=lambda *args: {"output_text": "not-json"},
    )
    with pytest.raises(EvidenceBriefingError):
        build_evidence_briefing(reports=reports(), provider=provider, now_utc=NOW)


def test_explicit_generation_is_hash_chained_and_idempotent(tmp_path):
    path = tmp_path / "insights.jsonl"
    request = BriefingGenerateRequest(idempotency_key="briefing-request-1", provider_mode="OFFLINE")

    first = generate_and_store_insight(request, insight_path=path, reports=reports(), now_utc=NOW)
    repeated = generate_and_store_insight(
        request, insight_path=path, reports=reports(), now_utc=NOW
    )

    assert first["created"] is True
    assert repeated["created"] is False
    assert first["safety"]["files_changed"] == 1
    assert repeated["safety"]["files_changed"] == 0
    assert len(read_insights(path)) == 1


def test_insight_store_detects_tampering(tmp_path):
    path = tmp_path / "insights.jsonl"
    generate_and_store_insight(
        BriefingGenerateRequest(idempotency_key="briefing-request-2", provider_mode="OFFLINE"),
        insight_path=path,
        reports=reports(),
        now_utc=NOW,
    )
    payload = json.loads(path.read_text())
    payload["model"] = "tampered"
    path.write_text(json.dumps(payload) + "\n")

    with pytest.raises(InsightStoreError, match="hash mismatch"):
        read_insights(path)


def test_hosted_generation_is_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_BRIEFING_HOSTED_ENABLED", raising=False)
    with pytest.raises(EvidenceBriefingError, match="disabled"):
        generate_and_store_insight(
            BriefingGenerateRequest(
                idempotency_key="briefing-request-3",
                provider_mode="OPENAI",
                external_transmission_confirmed=True,
            ),
            insight_path=tmp_path / "insights.jsonl",
            reports=reports(),
            now_utc=NOW,
        )


def test_hosted_request_requires_explicit_external_transmission_confirmation():
    with pytest.raises(ValueError, match="external transmission confirmation"):
        BriefingGenerateRequest(
            idempotency_key="briefing-request-7",
            provider_mode="OPENAI",
        )

    offline = BriefingGenerateRequest(
        idempotency_key="briefing-request-8",
        provider_mode="OFFLINE",
    )
    assert offline.external_transmission_confirmed is False

    response = TestClient(app).post(
        "/ai/evidence-briefing",
        json={
            "idempotency_key": "briefing-request-9",
            "provider_mode": "OPENAI",
        },
    )
    assert response.status_code == 422


def test_real_briefing_endpoint_is_offline_and_read_only():
    result = TestClient(app).get("/ai/evidence-briefing")

    assert result.status_code == 200
    body = result.json()
    assert body["provider_mode"] == "OFFLINE"
    assert body["safety"]["network_calls_made"] == 0
    assert body["safety"]["files_changed"] == 0
    assert body["safety"]["broker_orders_submitted"] == 0
    assert body["safety"]["trading_action_permitted"] is False

    schema = app.openapi()["paths"]["/ai/evidence-briefing"]
    assert schema["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/EvidenceBriefingResponse")
    assert schema["post"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/InsightAppendResponse")


def test_insight_endpoints_preserve_audit_separation(monkeypatch, tmp_path):
    stored = generate_and_store_insight(
        BriefingGenerateRequest(idempotency_key="briefing-request-4", provider_mode="OFFLINE"),
        insight_path=tmp_path / "insights.jsonl",
        reports=reports(),
        now_utc=NOW,
    )
    monkeypatch.setattr(router, "generate_and_store_insight", lambda request: stored)
    monkeypatch.setattr(
        router,
        "list_insights",
        lambda: {
            "status": "HEALTHY",
            "insight_count": 1,
            "insights": [stored["insight"]],
            "safety": {
                "input_sanitized": True,
                "credentials_included": False,
                "annotation_text_included": False,
                "raw_market_data_included": False,
                "trading_action_permitted": False,
                "network_calls_made": 0,
                "files_changed": 0,
                "ledger_writes_performed": 0,
                "broker_orders_submitted": 0,
                "safe_for_live_trading": False,
                "protocol_live_trading_permitted": False,
            },
        },
    )
    client = TestClient(app)

    created = client.post(
        "/ai/evidence-briefing",
        json={"idempotency_key": "briefing-request-4", "provider_mode": "OFFLINE"},
    )
    listed = client.get("/ai/evidence-insights")

    assert created.status_code == 200
    assert created.json()["safety"]["network_calls_made"] == 0
    assert created.json()["safety"]["ledger_writes_performed"] == 0
    assert created.json()["safety"]["broker_orders_submitted"] == 0
    assert listed.status_code == 200
    assert listed.json()["insight_count"] == 1
    assert listed.json()["safety"]["files_changed"] == 0


def test_human_annotation_links_to_verified_ai_insight(tmp_path):
    insight_path = tmp_path / "insights.jsonl"
    generated = generate_and_store_insight(
        BriefingGenerateRequest(idempotency_key="briefing-request-5", provider_mode="OFFLINE"),
        insight_path=insight_path,
        reports=reports(),
        now_utc=NOW,
    )

    reviewed = create_operator_annotation(
        AnnotationRequest(
            idempotency_key="insight-review-1",
            subject_type="AI_INSIGHT",
            subject_id=generated["insight"]["insight_id"],
            category="REVIEW",
            note="Reviewed; continue collecting evidence without changing policy.",
        ),
        annotation_path=tmp_path / "annotations.jsonl",
        insight_path=insight_path,
        cockpit_report={
            "current_software_commit": "abc1234",
            "current_policy_fingerprint": "f" * 64,
            "session_lineage": [],
        },
        alert_report={"alerts": []},
        now_utc=NOW,
    )

    assert reviewed["annotation"]["subject_type"] == "AI_INSIGHT"
    assert reviewed["annotation"]["subject_id"] == generated["insight"]["insight_id"]
    assert reviewed["annotation"]["subject_session_date"] == "2026-07-22"
    assert reviewed["broker_orders_submitted"] == 0

    governance = build_ai_governance_report(
        insight_path=insight_path,
        annotation_path=tmp_path / "annotations.jsonl",
    )
    assert governance["status"] == "HEALTHY"
    assert governance["reviewed_insight_count"] == 1
    assert governance["unreviewed_insight_count"] == 0
    assert governance["hosted_insight_count"] == 0
    assert governance["safety"]["broker_orders_submitted"] == 0


def test_governance_requires_review_for_saved_insight(tmp_path):
    insight_path = tmp_path / "insights.jsonl"
    generated = generate_and_store_insight(
        BriefingGenerateRequest(idempotency_key="briefing-request-6", provider_mode="OFFLINE"),
        insight_path=insight_path,
        reports=reports(),
        now_utc=NOW,
    )

    governance = build_ai_governance_report(
        insight_path=insight_path,
        annotation_path=tmp_path / "annotations.jsonl",
    )

    assert governance["status"] == "REVIEW_REQUIRED"
    assert governance["unreviewed_insight_ids"] == [generated["insight"]["insight_id"]]
    assert governance["reviewed_insight_count"] == 0
    assert governance["orphaned_review_count"] == 0


def test_empty_governance_is_healthy_and_read_only(tmp_path):
    governance = build_ai_governance_report(
        insight_path=tmp_path / "insights.jsonl",
        annotation_path=tmp_path / "annotations.jsonl",
    )

    assert governance["status"] == "HEALTHY"
    assert governance["insight_count"] == 0
    assert governance["safety"]["network_calls_made"] == 0
    assert governance["safety"]["files_changed"] == 0


def test_provider_preflight_is_disabled_and_secret_free_by_default():
    result = build_provider_readiness_report(environment={})

    assert result["status"] == "DISABLED"
    assert result["offline_provider_ready"] is True
    assert result["hosted_provider_requested"] is False
    assert result["api_key_configured"] is False
    assert result["request_storage_enabled"] is False
    assert result["safety"]["network_calls_made"] == 0


def test_provider_preflight_reports_presence_without_exposing_key():
    result = build_provider_readiness_report(
        environment={
            "AI_BRIEFING_HOSTED_ENABLED": "true",
            "AI_BRIEFING_OPENAI_MODEL": "configured-model",
            "OPENAI_API_KEY": "super-secret-key",
        }
    )

    assert result["status"] == "READY"
    assert result["configured_model"] == "configured-model"
    assert result["api_key_configured"] is True
    assert result["blocking_reasons"] == []
    assert "super-secret-key" not in json.dumps(result)
