"""Hash-chained audit receipts for completed practice canary rehearsals."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.broker.canary_gateway import CanaryRehearsalResult

GENESIS_HASH = "0" * 64


class CanaryAuditError(RuntimeError):
    """Raised when the local canary receipt chain is invalid."""


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _parse(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    previous = GENESIS_HASH
    seen_ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise CanaryAuditError(f"Invalid canary audit JSON at line {line_number}.") from error
        if not isinstance(record, dict):
            raise CanaryAuditError(f"Invalid canary audit record at line {line_number}.")
        schema_version = record.get("schema_version")
        if schema_version not in {1, 2, 3} or record.get("sequence") != line_number:
            raise CanaryAuditError(f"Canary audit sequence mismatch at line {line_number}.")
        if record.get("previous_hash") != previous:
            raise CanaryAuditError(f"Canary audit chain mismatch at line {line_number}.")
        rehearsal_id = record.get("rehearsal_id")
        if not isinstance(rehearsal_id, str) or not rehearsal_id:
            raise CanaryAuditError(f"Invalid rehearsal ID at line {line_number}.")
        if rehearsal_id in seen_ids:
            raise CanaryAuditError("Duplicate canary rehearsal ID detected.")
        payload = dict(record)
        record_hash = payload.pop("record_hash", None)
        if not isinstance(record_hash, str) or _hash(payload) != record_hash:
            raise CanaryAuditError(f"Canary audit hash mismatch at line {line_number}.")
        expected_invariants = {
            "status": "PRACTICE_REHEARSAL_COMPLETE",
            "environment": "practice",
            "units": 1,
            "practice_entry_orders_submitted": 1,
            "practice_close_orders_submitted": 1,
            "live_orders_submitted": 0,
            "position_verified_open": True,
            "position_verified_closed": True,
            "live_canary_build_enabled": False,
        }
        if any(record.get(key) != value for key, value in expected_invariants.items()):
            raise CanaryAuditError(f"Canary audit safety invariant failed at line {line_number}.")
        if schema_version in {2, 3}:
            try:
                budget = Decimal(str(record.get("loss_budget_gbp")))
                reserved = Decimal(str(record.get("reserved_costs_gbp")))
                stop_risk = Decimal(str(record.get("stop_loss_risk_gbp")))
                premium = Decimal(str(record.get("gslo_premium_gbp")))
                worst_case = Decimal(str(record.get("worst_case_loss_gbp")))
                remaining = Decimal(str(record.get("remaining_loss_budget_gbp")))
            except InvalidOperation as error:
                raise CanaryAuditError(
                    f"Invalid canary GBP budget at line {line_number}."
                ) from error
            v2_invariants = {
                "guaranteed_stop_loss": True,
                "account_home_currency": "GBP",
                "quote_loss_conversion_factor": "1",
            }
            if (
                any(record.get(key) != value for key, value in v2_invariants.items())
                or not all(
                    value.is_finite()
                    for value in (budget, reserved, stop_risk, premium, worst_case, remaining)
                )
                or budget <= 0
                or budget > Decimal("50")
                or any(value < 0 for value in (reserved, stop_risk, premium, worst_case, remaining))
                or worst_case != stop_risk + premium + reserved
                or worst_case > budget
                or remaining != budget - worst_case
            ):
                raise CanaryAuditError(f"Canary GBP budget invariant failed at line {line_number}.")
        if schema_version == 3:
            try:
                entry_reference = Decimal(str(record.get("entry_reference_price")))
                entry_fill = Decimal(str(record.get("entry_fill_price")))
                exit_fill = Decimal(str(record.get("exit_fill_price")))
                slippage_price = Decimal(str(record.get("entry_slippage_price")))
                slippage_gbp = Decimal(str(record.get("entry_slippage_gbp")))
                realized_pl = Decimal(str(record.get("realized_pl_gbp")))
                financing = Decimal(str(record.get("financing_gbp")))
                commission = Decimal(str(record.get("commission_gbp")))
                gslo_fee = Decimal(str(record.get("guaranteed_execution_fee_gbp")))
                net_impact = Decimal(str(record.get("net_account_impact_gbp")))
                net_units = Decimal(str(record.get("post_close_net_units")))
            except InvalidOperation as error:
                raise CanaryAuditError(
                    f"Invalid canary outcome evidence at line {line_number}."
                ) from error
            outcome_values = (
                entry_reference,
                entry_fill,
                exit_fill,
                slippage_price,
                slippage_gbp,
                realized_pl,
                financing,
                commission,
                gslo_fee,
                net_impact,
                net_units,
            )
            quote_attempts = record.get("quote_refresh_attempts")
            if (
                not all(value.is_finite() for value in outcome_values)
                or min(entry_reference, entry_fill, exit_fill) <= 0
                or slippage_gbp != slippage_price
                or not isinstance(quote_attempts, int)
                or not 1 <= quote_attempts <= 3
                or record.get("post_close_open_trade_count") != 0
                or record.get("post_close_pending_order_count") != 0
                or record.get("post_close_nonzero_position_count") != 0
                or net_units != 0
                or record.get("post_close_exposure_verified") is not True
                or record.get("account_balance_reconciled") is not True
            ):
                raise CanaryAuditError(
                    f"Canary outcome evidence invariant failed at line {line_number}."
                )
        records.append(record)
        seen_ids.add(rehearsal_id)
        previous = record_hash
    return records


def _read(descriptor: int) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks = []
    while chunk := os.read(descriptor, 65536):
        chunks.append(chunk)
    return b"".join(chunks).decode()


def read_canary_audit(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    descriptor = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        return _parse(_read(descriptor))
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def append_canary_audit(
    path: Path,
    result: CanaryRehearsalResult,
    *,
    completed_at_utc: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    resolved_time = completed_at_utc or datetime.now(UTC)
    if resolved_time.tzinfo is None:
        raise CanaryAuditError("Canary audit time must be timezone-aware.")
    result_payload = asdict(result)
    if result_payload["live_orders_submitted"] != 0:
        raise CanaryAuditError("A live-order result cannot enter the practice audit chain.")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        records = _parse(_read(descriptor))
        existing = next(
            (record for record in records if record["rehearsal_id"] == result.rehearsal_id),
            None,
        )
        if existing:
            comparable = {
                key: value
                for key, value in existing.items()
                if key
                not in {
                    "schema_version",
                    "sequence",
                    "completed_at_utc",
                    "previous_hash",
                    "record_hash",
                }
            }
            if comparable != result_payload:
                raise CanaryAuditError(
                    "Canary rehearsal ID was reused for a different completed result."
                )
            return existing, False
        payload = {
            "schema_version": 3,
            "sequence": len(records) + 1,
            "completed_at_utc": resolved_time.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            **result_payload,
            "previous_hash": records[-1]["record_hash"] if records else GENESIS_HASH,
        }
        payload["record_hash"] = _hash(payload)
        encoded = (_canonical(payload) + "\n").encode()
        os.lseek(descriptor, 0, os.SEEK_END)
        written = 0
        while written < len(encoded):
            written += os.write(descriptor, encoded[written:])
        os.fsync(descriptor)
        if _parse(_read(descriptor))[-1] != payload:
            raise CanaryAuditError("Appended canary audit record could not be verified.")
        return payload, True
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
