import json
from pathlib import Path

import pytest

from app.paper_trading.policy import (
    BASE_RISK_PERCENT,
    DIRECTIONAL_CLOSE_LOCATION_THRESHOLD,
    EXPECTED_POLICY_FINGERPRINT,
    REDUCED_RISK_PERCENT,
    calculate_policy_fingerprint,
    calculate_validated_close_location_risk,
    frozen_policy_payload,
    verify_frozen_policy,
)


PROTOCOL_PATH = Path(
    "research_protocols/"
    "prospective_paper_trading_protocol.json"
)


def test_frozen_policy_verifies():
    assert verify_frozen_policy() == (
        EXPECTED_POLICY_FINGERPRINT
    )


def test_policy_constants_match_preregistration():
    assert BASE_RISK_PERCENT == 0.5
    assert REDUCED_RISK_PERCENT == 0.25

    assert (
        DIRECTIONAL_CLOSE_LOCATION_THRESHOLD
        == 0.8174
    )


def test_risk_reduces_below_threshold():
    decision = (
        calculate_validated_close_location_risk(
            0.50
        )
    )

    assert decision.risk_reduced is True

    assert decision.adjusted_risk_percent == (
        REDUCED_RISK_PERCENT
    )


def test_risk_reduces_at_exact_threshold():
    decision = (
        calculate_validated_close_location_risk(
            DIRECTIONAL_CLOSE_LOCATION_THRESHOLD
        )
    )

    assert decision.risk_reduced is True

    assert decision.adjusted_risk_percent == (
        REDUCED_RISK_PERCENT
    )


def test_base_risk_retained_above_threshold():
    decision = (
        calculate_validated_close_location_risk(
            0.817401
        )
    )

    assert decision.risk_reduced is False

    assert decision.adjusted_risk_percent == (
        BASE_RISK_PERCENT
    )


@pytest.mark.parametrize(
    "value",
    [-0.01, 1.01],
)
def test_invalid_close_location_is_rejected(
    value,
):
    with pytest.raises(
        ValueError,
        match=(
            "Directional close location must be "
            "between zero and one"
        ),
    ):
        calculate_validated_close_location_risk(
            value
        )


def test_non_frozen_base_risk_is_rejected():
    with pytest.raises(
        ValueError,
        match="frozen base risk",
    ):
        calculate_validated_close_location_risk(
            0.90,
            base_risk_percent=0.4,
        )


def test_fingerprint_recalculates_from_protocol():
    protocol = json.loads(
        PROTOCOL_PATH.read_text()
    )

    payload = frozen_policy_payload(
        protocol
    )

    assert calculate_policy_fingerprint(
        payload
    ) == EXPECTED_POLICY_FINGERPRINT
