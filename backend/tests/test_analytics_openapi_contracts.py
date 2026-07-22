"""Tests for typed analytics API contracts."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_analytics_success_responses_use_named_models():
    schema = app.openapi()

    expected_models = {
        "/analytics/evidence-cockpit": "EvidenceCockpitResponse",
        "/analytics/strategy-attribution": ("StrategyAttributionResponse"),
        "/analytics/prospective-paper-health": ("ProspectivePaperHealthResponse"),
        "/analytics/operator-status": ("OperatorStatusResponse"),
        "/analytics/overview": "AnalyticsOverviewResponse",
        "/analytics/readiness": ("AnalyticsReadinessResponse"),
    }

    for path, model_name in expected_models.items():
        response_schema = schema["paths"][path]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]

        assert response_schema["$ref"].endswith(f"/{model_name}")


def test_analytics_conflicts_document_error_model():
    schema = app.openapi()

    for path in (
        "/analytics/evidence-cockpit",
        "/analytics/strategy-attribution",
        "/analytics/prospective-paper-health",
        "/analytics/operator-status",
        "/analytics/overview",
        "/analytics/readiness",
    ):
        conflict_schema = schema["paths"][path]["get"]["responses"]["409"]["content"][
            "application/json"
        ]["schema"]

        assert conflict_schema["$ref"].endswith("/AnalyticsErrorResponse")


def test_real_analytics_responses_match_contracts():
    for path in (
        "/analytics/evidence-cockpit",
        "/analytics/strategy-attribution",
        "/analytics/prospective-paper-health",
        "/analytics/operator-status",
        "/analytics/overview",
        "/analytics/readiness",
    ):
        response = client.get(path)

        assert response.status_code == 200
        assert response.json()["safe_for_live_trading"] is False
        assert response.json()["protocol_live_trading_permitted"] is False


def test_overview_contract_contains_nested_models():
    schema = app.openapi()
    overview = schema["components"]["schemas"]["AnalyticsOverviewResponse"]

    properties = overview["properties"]

    assert properties["runtime"]["$ref"].endswith("/ProspectivePaperHealthResponse")
    assert properties["operator_status"]["$ref"].endswith("/OperatorStatusResponse")
    assert properties["strategy_attribution"]["$ref"].endswith("/StrategyAttributionResponse")


def test_operator_contract_declares_observation_integrity_fields():
    schema = app.openapi()
    operator = schema["components"]["schemas"][
        "OperatorStatusResponse"
    ]

    properties = operator["properties"]

    assert "observation_integrity_status" in properties
    assert "observations_recorded" in properties
    assert "observation_outcomes_populated" in properties
    assert "observation_integrity_warnings" in properties


def test_readiness_contract_declares_observation_integrity_fields():
    schema = app.openapi()
    readiness = schema["components"]["schemas"][
        "AnalyticsReadinessResponse"
    ]

    properties = readiness["properties"]

    assert "observation_integrity_status" in properties
    assert "observations_recorded" in properties
    assert "observation_outcomes_populated" in properties
    assert "observation_integrity_warnings" in properties
