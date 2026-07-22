"""Derive notification-only alerts from the verified evidence cockpit."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.analytics.evidence_cockpit_reporting import build_evidence_cockpit


class OperatorAlertReportError(RuntimeError):
    """Raised when the operator alert feed cannot be assembled safely."""


def _alert_id(
    *,
    alert_type: str,
    source_key: str,
    cockpit: dict[str, Any],
) -> str:
    identity = {
        "alert_type": alert_type,
        "source_key": source_key,
        "session_date": cockpit.get("next_session_date"),
        "software_commit": cockpit["current_software_commit"],
        "policy_fingerprint": cockpit["current_policy_fingerprint"],
    }
    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_alert(
    *,
    cockpit: dict[str, Any],
    alert_type: str,
    source_key: str,
    severity: str,
    title: str,
    message: str,
    recommended_action: str,
    detected_at_utc: str,
    market: str | None = None,
    requires_operator_action: bool = False,
    evidence_timestamp_utc: str | None = None,
) -> dict[str, Any]:
    return {
        "alert_id": _alert_id(
            alert_type=alert_type,
            source_key=source_key,
            cockpit=cockpit,
        ),
        "alert_type": alert_type,
        "severity": severity,
        "status": "ACTIVE",
        "title": title,
        "message": message,
        "detected_at_utc": detected_at_utc,
        "evidence_timestamp_utc": evidence_timestamp_utc,
        "market": market,
        "session_date": cockpit.get("next_session_date"),
        "software_commit": cockpit["current_software_commit"],
        "policy_fingerprint": cockpit["current_policy_fingerprint"],
        "recommended_action": recommended_action,
        "requires_operator_action": requires_operator_action,
        "delivery_mode": "NOTIFICATION_ONLY",
        "order_action_permitted": False,
    }


def build_operator_alert_report(
    *,
    cockpit_report: dict[str, Any] | None = None,
    cockpit_builder: Callable[[], dict[str, Any]] = build_evidence_cockpit,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Build active alerts without writing state or delivering messages."""
    try:
        cockpit = cockpit_report or cockpit_builder()
    except (OSError, RuntimeError, ValueError) as error:
        raise OperatorAlertReportError(str(error)) from error

    resolved_now = now_utc or datetime.now(UTC)
    if resolved_now.tzinfo is None:
        raise OperatorAlertReportError("Alert time must be timezone-aware.")
    detected_at_utc = resolved_now.astimezone(UTC).isoformat()
    alerts: list[dict[str, Any]] = []

    for issue in cockpit.get("blocking_issues") or []:
        alerts.append(
            _build_alert(
                cockpit=cockpit,
                alert_type="INTEGRITY_BLOCKER",
                source_key=str(issue),
                severity="CRITICAL",
                title="Paper operation blocked",
                message=str(issue),
                recommended_action=(
                    "Resolve and re-verify the blocking issue before "
                    "another paper session."
                ),
                detected_at_utc=detected_at_utc,
                requires_operator_action=True,
            )
        )

    if not cockpit.get("markets_aligned", False):
        alerts.append(
            _build_alert(
                cockpit=cockpit,
                alert_type="MARKET_DATA_CONFLICT",
                source_key="markets-not-aligned",
                severity="CRITICAL",
                title="Market data timestamps conflict",
                message="The configured markets do not share one latest complete candle timestamp.",
                recommended_action=(
                    "Do not run a paper session until market data is "
                    "aligned and re-verified."
                ),
                detected_at_utc=detected_at_utc,
                requires_operator_action=True,
            )
        )

    for market in cockpit.get("markets") or []:
        if market.get("latest_complete_timestamp") is None:
            market_name = str(market["market"])
            alerts.append(
                _build_alert(
                    cockpit=cockpit,
                    alert_type="MARKET_DATA_UNAVAILABLE",
                    source_key=market_name,
                    severity="CRITICAL",
                    title=f"{market_name} complete candle unavailable",
                    message="No verified latest complete candle timestamp is available.",
                    recommended_action=(
                        "Restore and verify the market data before "
                        "continuing paper observation."
                    ),
                    detected_at_utc=detected_at_utc,
                    market=market_name,
                    requires_operator_action=True,
                )
            )

    for entry in cockpit.get("pending_entries") or []:
        market_name = str(entry["market"])
        alerts.append(
            _build_alert(
                cockpit=cockpit,
                alert_type="PENDING_ENTRY_AWAITING_CANDLE",
                source_key=f"{market_name}:{entry.get('signal_candle_timestamp')}",
                severity="INFO",
                title=f"{market_name} paper entry is pending",
                message="The pending paper entry is waiting for a later complete candle.",
                recommended_action=(
                    "Wait for the next complete candle; do not submit "
                    "a broker order."
                ),
                detected_at_utc=detected_at_utc,
                market=market_name,
                evidence_timestamp_utc=entry.get("signal_candle_timestamp"),
            )
        )

    for position in cockpit.get("open_positions") or []:
        market_name = str(position["market"])
        alerts.append(
            _build_alert(
                cockpit=cockpit,
                alert_type="PAPER_POSITION_MONITORING",
                source_key=f"{market_name}:{position.get('entry_timestamp')}",
                severity="INFO",
                title=f"{market_name} paper position is open",
                message="An open simulated position will be evaluated on complete candles only.",
                recommended_action="Continue passive monitoring under the frozen policy.",
                detected_at_utc=detected_at_utc,
                market=market_name,
                evidence_timestamp_utc=position.get("entry_timestamp"),
            )
        )

    for warning in cockpit.get("warnings") or []:
        alerts.append(
            _build_alert(
                cockpit=cockpit,
                alert_type="EVIDENCE_WARNING",
                source_key=str(warning),
                severity="WARNING",
                title="Evidence requires attention",
                message=str(warning),
                recommended_action=(
                    "Review the evidence warning without changing the "
                    "frozen strategy."
                ),
                detected_at_utc=detected_at_utc,
            )
        )

    next_action = cockpit.get("next_action")
    if next_action == "RUN_NEXT_GUARDED_PAPER_SESSION":
        latest_timestamps = sorted(
            {
                str(market["latest_complete_timestamp"])
                for market in cockpit.get("markets") or []
                if market.get("latest_complete_timestamp") is not None
            }
        )
        evidence_timestamp = latest_timestamps[-1] if latest_timestamps else None
        alerts.append(
            _build_alert(
                cockpit=cockpit,
                alert_type="PAPER_SESSION_ELIGIBLE",
                source_key=f"eligible:{evidence_timestamp}",
                severity="INFO",
                title="Guarded paper session is eligible",
                message="Verified evidence permits the next guarded paper session.",
                recommended_action="Run only the guarded simulation-only paper session.",
                detected_at_utc=detected_at_utc,
                evidence_timestamp_utc=evidence_timestamp,
            )
        )

    severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    alerts.sort(
        key=lambda alert: (
            severity_order[alert["severity"]],
            alert["alert_type"],
            alert["alert_id"],
        )
    )

    critical_count = sum(alert["severity"] == "CRITICAL" for alert in alerts)
    warning_count = sum(alert["severity"] == "WARNING" for alert in alerts)

    return {
        "schema_version": 1,
        "status": "ATTENTION_REQUIRED" if critical_count else "ACTIVE",
        "generated_at_utc": detected_at_utc,
        "delivery_mode": "NOTIFICATION_ONLY",
        "active_alert_count": len(alerts),
        "critical_alert_count": critical_count,
        "warning_alert_count": warning_count,
        "alerts": alerts,
        "network_calls_made": 0,
        "files_changed": 0,
        "ledger_writes_performed": 0,
        "broker_orders_submitted": 0,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
    }
