import pytest

from scripts.nested_close_location_risk_walk_forward import (
    create_close_location_risk_adjuster,
    learn_close_location_threshold,
    threshold_available,
)


def test_learns_lower_tercile_threshold():
    records = [
        {
            "directional_close_location": value,
        }
        for value in [
            0.1,
            0.2,
            0.3,
            0.4,
            0.5,
            0.6,
            0.7,
        ]
    ]

    threshold = (
        learn_close_location_threshold(
            records
        )
    )

    assert threshold == pytest.approx(
        0.3
    )


def test_threshold_learning_requires_records():
    with pytest.raises(
        ValueError,
        match=(
            "without training records"
        ),
    ):
        learn_close_location_threshold(
            []
        )


def test_threshold_requires_two_completed_folds():
    records = [
        {
            "directional_close_location": 0.8,
        }
        for _ in range(200)
    ]

    assert not threshold_available(
        records,
        fold_number=2,
    )

    assert threshold_available(
        records,
        fold_number=3,
    )


def test_inactive_adjuster_retains_risk():
    adjuster = (
        create_close_location_risk_adjuster(
            None
        )
    )

    class Config:
        risk_per_trade_percent = 0.5

    assert adjuster(
        Config(),
        [],
        "BUY",
    ) == 0.5


def test_insufficient_history_retains_risk():
    adjuster = (
        create_close_location_risk_adjuster(
            0.8
        )
    )

    class Config:
        risk_per_trade_percent = 0.5

    assert adjuster(
        Config(),
        [],
        "BUY",
    ) == 0.5


def test_adjuster_never_exceeds_configured_risk():
    adjuster = (
        create_close_location_risk_adjuster(
            0.8
        )
    )

    class Config:
        risk_per_trade_percent = 0.5

    result = adjuster(
        Config(),
        [],
        "SELL",
    )

    assert 0 < result <= 0.5
