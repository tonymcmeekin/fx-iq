"""Build the credential-free evidence snapshot supplied to analysts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from app.ai_briefing.models import EvidenceItem, SanitizedEvidenceSnapshot

EXCLUDED_FIELDS = [
    "broker credentials and tokens",
    "broker account identifiers",
    "operator annotation text",
    "raw candles and tick data",
    "environment variables",
    "order submission interfaces",
]


def build_sanitized_snapshot(
    *,
    cockpit: dict[str, Any],
    alerts: dict[str, Any],
    portfolio: dict[str, Any],
    outcomes: dict[str, Any],
    annotations: dict[str, Any],
    now_utc: datetime | None = None,
) -> SanitizedEvidenceSnapshot:
    """Select aggregate, non-secret facts and immutable evidence IDs."""
    resolved_now = now_utc or datetime.now(UTC)
    if resolved_now.tzinfo is None:
        raise ValueError("Evidence snapshot time must be timezone-aware.")

    items = [
        EvidenceItem(
            evidence_id=f"cockpit:{cockpit['current_software_commit']}",
            evidence_type="COCKPIT",
            facts={
                "status": cockpit.get("status"),
                "next_action": cockpit.get("next_action"),
                "last_completed_session_date": cockpit.get("last_completed_session_date"),
                "next_session_date": cockpit.get("next_session_date"),
                "pending_markets": [row["market"] for row in cockpit.get("pending_entries", [])],
                "open_markets": [row["market"] for row in cockpit.get("open_positions", [])],
                "observations_recorded": int(cockpit.get("observations_recorded", 0)),
                "outcomes_populated": int(cockpit.get("observation_outcomes_populated", 0)),
                "broker_orders_sent": int(cockpit.get("broker_orders_sent", 0)),
                "blocking_issue_count": len(cockpit.get("blocking_issues", [])),
                "warning_count": len(cockpit.get("warnings", [])),
                "markets_aligned": bool(cockpit.get("markets_aligned", False)),
                "software_commit": cockpit["current_software_commit"],
                "policy_fingerprint": cockpit["current_policy_fingerprint"],
            },
        ),
        EvidenceItem(
            evidence_id=f"portfolio:{portfolio['generated_at_utc']}",
            evidence_type="PORTFOLIO",
            facts={
                "status": portfolio.get("status"),
                "pending_entry_count": int(portfolio.get("pending_entry_count", 0)),
                "open_position_count": int(portfolio.get("open_position_count", 0)),
                "candidate_gross_risk_percent": portfolio.get("candidate_gross_risk_percent"),
                "correlation_pair_count": int(portfolio.get("correlation_pair_count", 0)),
                "available_correlation_pair_count": int(
                    portfolio.get("available_correlation_pair_count", 0)
                ),
                "minimum_aligned_returns_required": int(
                    portfolio.get("minimum_aligned_returns_required", 0)
                ),
                "maximum_aligned_returns_observed": max(
                    [
                        int(row.get("aligned_return_count", 0))
                        for row in portfolio.get("correlations", [])
                    ],
                    default=0,
                ),
            },
        ),
        EvidenceItem(
            evidence_id=f"outcomes:{outcomes['generated_at_utc']}",
            evidence_type="OUTCOMES",
            facts={
                "status": outcomes.get("status"),
                "outcome_count": int(outcomes.get("outcome_count", 0)),
                "minimum_overall_sample": int(outcomes.get("minimum_overall_sample", 0)),
                "available_group_count": int(outcomes.get("available_group_count", 0)),
                "performance_metrics_available": outcomes.get("status") == "AVAILABLE",
                "integrity_status": outcomes.get("integrity_status"),
            },
        ),
    ]
    items.extend(
        EvidenceItem(
            evidence_id=f"alert:{alert['alert_id']}",
            evidence_type="ALERT",
            facts={
                "alert_type": alert.get("alert_type"),
                "severity": alert.get("severity"),
                "market": alert.get("market"),
                "session_date": alert.get("session_date"),
                "requires_operator_action": bool(alert.get("requires_operator_action", False)),
            },
        )
        for alert in alerts.get("alerts", [])
    )
    items.extend(
        EvidenceItem(
            evidence_id=f"annotation:{annotation['annotation_id']}",
            evidence_type="ANNOTATION",
            facts={
                "sequence": int(annotation["sequence"]),
                "subject_type": annotation["subject_type"],
                "subject_id": annotation["subject_id"],
                "category": annotation["category"],
                "created_at_utc": annotation["created_at_utc"],
            },
        )
        for annotation in annotations.get("annotations", [])
    )
    return SanitizedEvidenceSnapshot(
        generated_at_utc=resolved_now.astimezone(UTC),
        evidence_items=items,
        excluded_fields=EXCLUDED_FIELDS,
    )


def snapshot_fingerprint(snapshot: SanitizedEvidenceSnapshot) -> str:
    payload = snapshot.model_dump(mode="json", exclude={"generated_at_utc"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
