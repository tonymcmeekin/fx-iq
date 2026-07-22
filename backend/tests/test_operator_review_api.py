"""Tests for append-only evidence-linked operator review notes."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.operator_review import router
from app.operator_review.models import AnnotationRequest
from app.operator_review.service import (
    OperatorReviewError,
    create_operator_annotation,
)
from app.operator_review.store import (
    AnnotationStoreError,
    append_annotation,
    read_annotations,
)

client = TestClient(app)


def append_test_annotation(store_path, *, key="request-key-1", note="Review note"):
    return append_annotation(
        store_path,
        idempotency_key=key,
        created_at_utc=datetime(2026, 7, 22, 12, tzinfo=UTC),
        subject_type="ALERT",
        subject_id="alert-id",
        subject_session_date=date(2026, 7, 23),
        category="REVIEW",
        note=note,
        software_commit="abc1234",
        policy_fingerprint="f" * 64,
    )


def test_annotation_store_is_hash_chained_and_idempotent(tmp_path):
    store_path = tmp_path / "annotations.jsonl"

    first, first_created = append_test_annotation(store_path)
    repeated, repeated_created = append_test_annotation(store_path)
    second, second_created = append_test_annotation(
        store_path,
        key="request-key-2",
        note="Follow-up note",
    )
    stored = read_annotations(store_path)

    assert first_created is True
    assert repeated_created is False
    assert repeated == first
    assert second_created is True
    assert second.sequence == 2
    assert second.previous_hash == first.record_hash
    assert stored == [first, second]


def test_annotation_store_rejects_idempotency_reuse(tmp_path):
    store_path = tmp_path / "annotations.jsonl"
    append_test_annotation(store_path)

    with pytest.raises(AnnotationStoreError, match="reused"):
        append_test_annotation(store_path, note="Different note")


def test_annotation_store_detects_tampering(tmp_path):
    store_path = tmp_path / "annotations.jsonl"
    append_test_annotation(store_path)
    payload = json.loads(store_path.read_text(encoding="utf-8"))
    payload["note"] = "Tampered note"
    store_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(AnnotationStoreError, match="hash mismatch"):
        read_annotations(store_path)


def test_service_links_active_alert_to_current_lineage(tmp_path):
    request = AnnotationRequest(
        idempotency_key="request-key-3",
        subject_type="ALERT",
        subject_id="active-alert",
        category="CONTEXT",
        note="Wait for the next complete candle.",
    )

    result = create_operator_annotation(
        request,
        annotation_path=tmp_path / "annotations.jsonl",
        cockpit_report={
            "current_software_commit": "abc1234",
            "current_policy_fingerprint": "f" * 64,
            "session_lineage": [],
        },
        alert_report={
            "alerts": [
                {
                    "alert_id": "active-alert",
                    "session_date": "2026-07-23",
                }
            ]
        },
        now_utc=datetime(2026, 7, 22, 12, tzinfo=UTC),
    )

    annotation = result["annotation"]
    assert result["status"] == "CREATED"
    assert result["files_changed"] == 1
    assert annotation["subject_session_date"] == "2026-07-23"
    assert annotation["software_commit"] == "abc1234"
    assert annotation["policy_fingerprint"] == "f" * 64
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0


def test_service_rejects_unknown_subject(tmp_path):
    request = AnnotationRequest(
        idempotency_key="request-key-4",
        subject_type="ALERT",
        subject_id="missing-alert",
        category="REVIEW",
        note="Unknown subject.",
    )

    with pytest.raises(OperatorReviewError, match="not currently active"):
        create_operator_annotation(
            request,
            annotation_path=tmp_path / "annotations.jsonl",
            cockpit_report={
                "current_software_commit": "abc1234",
                "current_policy_fingerprint": "f" * 64,
                "session_lineage": [],
            },
            alert_report={"alerts": []},
        )


def test_annotation_endpoints_use_typed_contracts():
    schema = app.openapi()
    get_schema = schema["paths"]["/operator-review/annotations"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    post_schema = schema["paths"]["/operator-review/annotations"]["post"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]

    assert get_schema["$ref"].endswith("/AnnotationListResponse")
    assert post_schema["$ref"].endswith("/AnnotationAppendResponse")


def test_annotation_post_preserves_separation(monkeypatch, tmp_path):
    annotation, _ = append_test_annotation(
        tmp_path / "annotations.jsonl"
    )

    monkeypatch.setattr(
        router,
        "create_operator_annotation",
        lambda request: {
            "status": "CREATED",
            "created": True,
            "annotation": annotation.model_dump(mode="json"),
            "network_calls_made": 0,
            "files_changed": 1,
            "ledger_writes_performed": 0,
            "broker_orders_submitted": 0,
            "safe_for_live_trading": False,
            "protocol_live_trading_permitted": False,
        },
    )

    response = client.post(
        "/operator-review/annotations",
        json={
            "idempotency_key": "request-key-1",
            "subject_type": "ALERT",
            "subject_id": "alert-id",
            "category": "REVIEW",
            "note": "Review note",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["created"] is True
    assert result["files_changed"] == 1
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False


def test_annotation_endpoint_returns_conflict(monkeypatch):
    def fail(request):
        raise OperatorReviewError("Annotation subject is unavailable.")

    monkeypatch.setattr(router, "create_operator_annotation", fail)

    response = client.post(
        "/operator-review/annotations",
        json={
            "idempotency_key": "request-key-5",
            "subject_type": "ALERT",
            "subject_id": "missing",
            "category": "REVIEW",
            "note": "Review note",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == (
        "Annotation subject is unavailable."
    )


def test_real_annotation_list_is_read_only():
    response = client.get("/operator-review/annotations")

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "HEALTHY"
    assert result["network_calls_made"] == 0
    assert result["files_changed"] == 0
    assert result["ledger_writes_performed"] == 0
    assert result["broker_orders_submitted"] == 0
    assert result["safe_for_live_trading"] is False
    assert result["protocol_live_trading_permitted"] is False
