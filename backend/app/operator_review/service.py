"""Evidence linkage and reporting for operator annotations."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.analytics.evidence_cockpit_reporting import build_evidence_cockpit
from app.analytics.operator_alert_reporting import build_operator_alert_report
from app.intelligence.observation_store import read_observations
from app.intelligence.outcome_store import read_outcomes
from app.operator_review.models import AnnotationRequest
from app.operator_review.store import append_annotation, read_annotations

BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]
DEFAULT_ANNOTATION_PATH = (
    BACKEND_DIRECTORY / "paper_ledger" / "operator_annotations.jsonl"
)
DEFAULT_OBSERVATION_PATH = (
    BACKEND_DIRECTORY / "paper_ledger" / "intelligence_observations.jsonl"
)
DEFAULT_OUTCOME_PATH = (
    BACKEND_DIRECTORY / "paper_ledger" / "intelligence_outcomes.jsonl"
)
DEFAULT_AI_INSIGHT_PATH = (
    BACKEND_DIRECTORY / "paper_ledger" / "ai_evidence_insights.jsonl"
)


class OperatorReviewError(RuntimeError):
    """Raised when an operator note cannot be linked or verified."""


def _subject_session_date(
    request: AnnotationRequest,
    *,
    cockpit: dict[str, Any],
    alerts: dict[str, Any],
    observation_path: Path,
    outcome_path: Path,
    insight_path: Path,
) -> date | None:
    if request.subject_type == "ALERT":
        match = next(
            (
                alert
                for alert in alerts["alerts"]
                if alert["alert_id"] == request.subject_id
            ),
            None,
        )
        if match is None:
            raise OperatorReviewError("Alert subject is not currently active.")
        value = match.get("session_date")
        return None if value is None else date.fromisoformat(str(value))
    if request.subject_type == "SESSION":
        if not any(
            lineage["session_date"] == request.subject_id
            for lineage in cockpit["session_lineage"]
        ):
            raise OperatorReviewError("Session subject is not verified.")
        return date.fromisoformat(request.subject_id)
    if request.subject_type == "OBSERVATION":
        match = next(
            (
                observation
                for observation in read_observations(observation_path)
                if observation.observation_id == request.subject_id
            ),
            None,
        )
        if match is None:
            raise OperatorReviewError("Observation subject is not verified.")
        return match.session_date
    if request.subject_type == "AI_INSIGHT":
        # Imported lazily to keep service initialization acyclic.
        from app.ai_briefing.store import read_insights

        match = next(
            (
                insight
                for insight in read_insights(insight_path)
                if insight.insight_id == request.subject_id
            ),
            None,
        )
        if match is None:
            raise OperatorReviewError("AI insight subject is not verified.")
        return match.created_at_utc.date()
    match = next(
        (
            outcome
            for outcome in read_outcomes(outcome_path)
            if outcome.outcome_id == request.subject_id
        ),
        None,
    )
    if match is None:
        raise OperatorReviewError("Outcome subject is not verified.")
    return match.originating_session_date


def list_operator_annotations(
    *,
    annotation_path: Path = DEFAULT_ANNOTATION_PATH,
) -> dict[str, Any]:
    """Return the verified annotation chain without mutating it."""
    try:
        annotations = read_annotations(annotation_path)
    except (OSError, RuntimeError, ValueError) as error:
        raise OperatorReviewError(str(error)) from error
    return {
        "schema_version": 1,
        "status": "HEALTHY",
        "annotation_count": len(annotations),
        "annotations": [
            annotation.model_dump(mode="json") for annotation in annotations
        ],
        "network_calls_made": 0,
        "files_changed": 0,
        "ledger_writes_performed": 0,
        "broker_orders_submitted": 0,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
    }


def create_operator_annotation(
    request: AnnotationRequest,
    *,
    annotation_path: Path = DEFAULT_ANNOTATION_PATH,
    observation_path: Path = DEFAULT_OBSERVATION_PATH,
    outcome_path: Path = DEFAULT_OUTCOME_PATH,
    insight_path: Path = DEFAULT_AI_INSIGHT_PATH,
    cockpit_report: dict[str, Any] | None = None,
    alert_report: dict[str, Any] | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Validate evidence linkage and append one immutable operator note."""
    try:
        cockpit = cockpit_report or build_evidence_cockpit()
        alerts = alert_report or build_operator_alert_report(
            cockpit_report=cockpit
        )
        session_date = _subject_session_date(
            request,
            cockpit=cockpit,
            alerts=alerts,
            observation_path=observation_path,
            outcome_path=outcome_path,
            insight_path=insight_path,
        )
        resolved_now = now_utc or datetime.now(UTC)
        annotation, created = append_annotation(
            annotation_path,
            idempotency_key=request.idempotency_key,
            created_at_utc=resolved_now,
            subject_type=request.subject_type,
            subject_id=request.subject_id,
            subject_session_date=session_date,
            category=request.category,
            note=request.note,
            software_commit=cockpit["current_software_commit"],
            policy_fingerprint=cockpit["current_policy_fingerprint"],
        )
    except (OSError, RuntimeError, ValueError) as error:
        if isinstance(error, OperatorReviewError):
            raise
        raise OperatorReviewError(str(error)) from error
    return {
        "status": "CREATED" if created else "EXISTING",
        "created": created,
        "annotation": annotation.model_dump(mode="json"),
        "network_calls_made": 0,
        "files_changed": 1 if created else 0,
        "ledger_writes_performed": 0,
        "broker_orders_submitted": 0,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
    }
