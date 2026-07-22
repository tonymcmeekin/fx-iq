"""Read-only integrity and summary reporting for passive observations."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.intelligence.observations import (
    OBSERVATION_SCHEMA_VERSION,
    TradeObservation,
)
from app.intelligence.outcome_store import read_outcomes
from app.paper_trading.ledger import verify_ledger


class ObservationReportError(RuntimeError):
    """Raised when an observation report cannot be produced safely."""


def _read_observation_records(
    path: Path,
) -> tuple[list[TradeObservation], list[str]]:
    if not path.exists():
        return [], []

    observations: list[TradeObservation] = []
    errors: list[str] = []

    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            errors.append(
                f"Blank observation line at {line_number}."
            )
            continue

        try:
            payload = json.loads(line)
            observation = TradeObservation.model_validate(
                payload
            )
        except (json.JSONDecodeError, ValueError) as error:
            errors.append(
                f"Invalid observation at line {line_number}: "
                f"{type(error).__name__}."
            )
            continue

        if observation.recorded_at_utc.tzinfo is None:
            errors.append(
                f"Timezone-naive recorded_at_utc at line {line_number}."
            )
        if observation.latest_candle_timestamp.tzinfo is None:
            errors.append(
                "Timezone-naive latest_candle_timestamp "
                f"at line {line_number}."
            )
        observations.append(observation)

    return observations, errors


def _counter_rows(
    values: list[str],
) -> list[dict[str, int | str]]:
    return [
        {
            "value": value,
            "count": count,
        }
        for value, count in sorted(
            Counter(values).items()
        )
    ]


def build_observation_report(
    *,
    ledger_path: Path,
    observation_path: Path,
    outcome_path: Path | None = None,
) -> dict[str, Any]:
    events = verify_ledger(ledger_path)
    observations, validation_errors = (
        _read_observation_records(
            observation_path
        )
    )
    outcomes = (
        read_outcomes(outcome_path)
        if outcome_path is not None
        else []
    )
    completed_events = [
        event
        for event in events
        if event["event_type"] == "SESSION_COMPLETED"
    ]
    close_events = [
        event
        for event in events
        if event["event_type"] == "PAPER_POSITION_CLOSED"
    ]
    close_event_ids = {
        event["event_id"]
        for event in close_events
    }
    outcome_close_ids = {
        outcome.close_event_id
        for outcome in outcomes
    }
    missing_outcome_close_event_ids = sorted(
        close_event_ids - outcome_close_ids
    )
    orphaned_outcome_close_event_ids = sorted(
        outcome_close_ids - close_event_ids
    )
    completed_dates = {
        event["payload"].get("session_date")
        for event in completed_events
    }
    observation_enabled_events = [
        event
        for event in completed_events
        if "observations_attempted" in event["payload"]
    ]
    enabled_by_date = {
        event["payload"]["session_date"]: event
        for event in observation_enabled_events
    }
    observations_by_date = Counter(
        observation.session_date.isoformat()
        for observation in observations
    )
    observation_ids = [
        observation.observation_id
        for observation in observations
    ]
    duplicate_ids = sorted(
        observation_id
        for observation_id, count in Counter(
            observation_ids
        ).items()
        if count > 1
    )
    orphaned_dates = sorted(
        {
            observation.session_date.isoformat()
            for observation in observations
            if observation.session_date.isoformat()
            not in completed_dates
        }
    )
    reconciliation = []

    for session_date, event in sorted(
        enabled_by_date.items()
    ):
        expected = int(
            event["payload"].get(
                "observations_attempted",
                0,
            )
        )
        actual = observations_by_date[
            session_date
        ]
        reconciliation.append(
            {
                "session_date": session_date,
                "expected": expected,
                "actual": actual,
                "matches": actual == expected,
            }
        )

    missing_dates = [
        row["session_date"]
        for row in reconciliation
        if not row["matches"]
    ]
    accepted = [
        observation
        for observation in observations
        if observation.trade_accepted
    ]
    completed_risk_rows = [
        summary
        for event in observation_enabled_events
        for summary in event["payload"].get(
            "market_summaries",
            [],
        )
        if summary.get("pending_entry")
    ]
    candidate_risk = sum(
        float(row.get("candidate_risk_percent") or 0.0)
        for row in completed_risk_rows
    )
    shadow_risk = sum(
        float(row.get("shadow_risk_percent") or 0.0)
        for row in completed_risk_rows
    )
    blocking_issues = [
        *validation_errors,
        *(
            ["Duplicate observation IDs were detected."]
            if duplicate_ids
            else []
        ),
        *(
            ["Orphaned observation session dates were detected."]
            if orphaned_dates
            else []
        ),
        *(
            ["Completed-session observation counts do not reconcile."]
            if missing_dates
            else []
        ),
        *(
            ["Paper close events are missing observation outcomes."]
            if missing_outcome_close_event_ids
            else []
        ),
        *(
            ["Observation outcomes reference unknown close events."]
            if orphaned_outcome_close_event_ids
            else []
        ),
    ]
    warnings = []
    if not observations:
        warnings.append("No passive observations are available.")
    if not outcomes:
        warnings.append("No observation outcomes are populated yet.")
    legacy_observations = sum(
        observation.schema_version
        < OBSERVATION_SCHEMA_VERSION
        for observation in observations
    )
    if legacy_observations:
        warnings.append(
            f"{legacy_observations} legacy observation records "
            "predate portfolio-aware acceptance semantics."
        )

    return {
        "status": (
            "HEALTHY"
            if not blocking_issues
            else "INTEGRITY_ERROR"
        ),
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "observation_count": len(observations),
        "completed_sessions": len(completed_events),
        "observation_enabled_sessions": len(
            observation_enabled_events
        ),
        "session_reconciliation": reconciliation,
        "duplicate_observation_ids": duplicate_ids,
        "orphaned_session_dates": orphaned_dates,
        "mismatched_session_dates": missing_dates,
        "accepted_observations": len(accepted),
        "rejected_observations": (
            len(observations) - len(accepted)
        ),
        "paper_close_events": len(close_events),
        "outcomes_populated": len(outcomes),
        "missing_outcome_close_event_ids": (
            missing_outcome_close_event_ids
        ),
        "orphaned_outcome_close_event_ids": (
            orphaned_outcome_close_event_ids
        ),
        "outcome_profit_percent_total": round(
            sum(outcome.profit_percent for outcome in outcomes),
            6,
        ),
        "outcomes_by_exit_reason": _counter_rows(
            [outcome.exit_reason for outcome in outcomes]
        ),
        "legacy_semantics_observations": (
            legacy_observations
        ),
        "by_schema_version": _counter_rows(
            [
                str(observation.schema_version)
                for observation in observations
            ]
        ),
        "by_instrument": _counter_rows(
            [observation.instrument for observation in observations]
        ),
        "by_direction": _counter_rows(
            [observation.direction for observation in observations]
        ),
        "by_regime_trend": _counter_rows(
            [observation.regime.trend for observation in observations]
        ),
        "by_regime_volatility": _counter_rows(
            [
                observation.regime.volatility
                for observation in observations
            ]
        ),
        "by_setup_quality": _counter_rows(
            [
                observation.features.setup_quality_label
                for observation in observations
            ]
        ),
        "accepted_candidate_risk_percent_total": round(
            candidate_risk,
            6,
        ),
        "accepted_shadow_risk_percent_total": round(
            shadow_risk,
            6,
        ),
        "network_calls_made": 0,
        "files_changed": 0,
        "broker_orders_sent": 0,
        "safe_for_live_trading": False,
    }
