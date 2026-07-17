from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.paper_trading.session_receipts import (
    SessionReceiptError,
    build_session_receipt,
    calculate_receipt_hash,
    verify_session_receipt,
    write_session_receipt,
)


def receipt_arguments() -> dict:
    return {
        "session_date": "2026-07-18",
        "software_commit": "50cad94",
        "policy_fingerprint": "policy-fingerprint",
        "runtime_health": "HEALTHY",
        "operator_status": "OBSERVING",
        "evidence_gate_status": "NOT_READY",
        "candidate_balance": 10012.5,
        "shadow_balance": 10000.0,
        "completed_sessions": 2,
        "broker_orders_sent": 0,
        "created_at_utc": datetime(
            2026,
            7,
            18,
            9,
            30,
            tzinfo=UTC,
        ),
    }


def test_build_receipt_is_deterministic():
    first = build_session_receipt(
        **receipt_arguments(),
    )
    second = build_session_receipt(
        **receipt_arguments(),
    )

    assert first == second
    assert first["receipt_hash"] == calculate_receipt_hash(first)
    assert len(first["receipt_hash"]) == 64


def test_write_and_verify_receipt(
    tmp_path,
):
    receipt_path = write_session_receipt(
        tmp_path,
        **receipt_arguments(),
    )

    assert receipt_path == tmp_path / "2026-07-18.json"
    assert receipt_path.exists()

    verified = verify_session_receipt(
        receipt_path,
    )

    assert verified["session_date"] == "2026-07-18"
    assert verified["broker_orders_sent"] == 0
    assert verified["safe_for_live_trading"] is False


def test_existing_receipt_is_never_overwritten(
    tmp_path,
):
    receipt_path = write_session_receipt(
        tmp_path,
        **receipt_arguments(),
    )
    original = receipt_path.read_bytes()

    with pytest.raises(
        SessionReceiptError,
        match="already exists",
    ):
        write_session_receipt(
            tmp_path,
            **receipt_arguments(),
        )

    assert receipt_path.read_bytes() == original


def test_tampered_receipt_is_rejected(
    tmp_path,
):
    receipt_path = write_session_receipt(
        tmp_path,
        **receipt_arguments(),
    )

    receipt = json.loads(
        receipt_path.read_text(),
    )
    receipt["candidate_balance"] = 999999.0
    receipt_path.write_text(
        json.dumps(receipt),
    )

    with pytest.raises(
        SessionReceiptError,
        match="hash verification failed",
    ):
        verify_session_receipt(
            receipt_path,
        )


def test_invalid_schema_is_rejected():
    arguments = receipt_arguments()
    receipt = build_session_receipt(
        **arguments,
    )
    receipt["schema_version"] = 999
    receipt["receipt_hash"] = calculate_receipt_hash(receipt)

    with pytest.raises(
        SessionReceiptError,
        match="schema",
    ):
        from app.paper_trading.session_receipts import (
            validate_receipt_payload,
        )

        validate_receipt_payload(
            receipt,
            require_hash=True,
        )


def test_broker_orders_are_rejected():
    arguments = receipt_arguments()
    arguments["broker_orders_sent"] = 1

    with pytest.raises(
        SessionReceiptError,
        match="zero broker orders",
    ):
        build_session_receipt(
            **arguments,
        )


def test_unhealthy_runtime_is_rejected():
    arguments = receipt_arguments()
    arguments["runtime_health"] = "UNHEALTHY"

    with pytest.raises(
        SessionReceiptError,
        match="healthy runtime",
    ):
        build_session_receipt(
            **arguments,
        )


def test_naive_creation_time_is_rejected():
    arguments = receipt_arguments()
    arguments["created_at_utc"] = datetime(
        2026,
        7,
        18,
        9,
        30,
    )

    with pytest.raises(
        SessionReceiptError,
        match="timezone-aware",
    ):
        build_session_receipt(
            **arguments,
        )
