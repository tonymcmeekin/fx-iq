import pytest

from scripts.nested_conjunction_risk_walk_forward import (
    create_conjunction_adjuster,
    learn_close_location_threshold,
    percentile,
    policy_available,
    result_status,
)


def test_percentile_interpolates_lower_tercile():
    values = [
        0.1,
        0.2,
        0.3,
        0.4,
        0.5,
        0.6,
        0.7,
    ]

    assert percentile(
        values,
        1 / 3,
    ) == pytest.approx(0.3)


def test_percentile_requires_values():
    with pytest.raises(
        ValueError,
        match="without values",
    ):
        percentile(
            [],
            1 / 3,
        )


def test_learns_close_location_threshold():
    records = [
        {
            "directional_close_location":
                value,
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


def test_policy_requires_two_completed_folds():
    records = [
        {
            "fold": 1,
        }
        for _ in range(200)
    ]

    assert not policy_available(
        records,
        fold_number=2,
    )

    assert policy_available(
        records,
        fold_number=3,
    )


def test_inactive_conjunction_retains_risk():
    adjuster = create_conjunction_adjuster(
        close_location_threshold=None,
        reduced_regime_groups=set(),
    )

    class Config:
        risk_per_trade_percent = 0.5

    assert adjuster(
        Config(),
        [],
        "BUY",
    ) == 0.5


def test_missing_regime_groups_retains_risk():
    adjuster = create_conjunction_adjuster(
        close_location_threshold=0.8,
        reduced_regime_groups=set(),
    )

    class Config:
        risk_per_trade_percent = 0.5

    assert adjuster(
        Config(),
        [],
        "BUY",
    ) == 0.5


def test_conjunction_adjuster_never_increases_risk():
    adjuster = create_conjunction_adjuster(
        close_location_threshold=0.8,
        reduced_regime_groups={
            (
                "TRENDING_UP",
                "NORMAL",
                "BUY",
            )
        },
    )

    class Config:
        risk_per_trade_percent = 0.5

    result = adjuster(
        Config(),
        [],
        "BUY",
    )

    assert 0 < result <= 0.5


def test_candidate_status_requires_robustness():
    status = result_status(
        markets_beating_fixed=4,
        active_folds_beating_fixed=3,
        aggregate_improvement=1.0,
        reduced_trades=30,
    )

    assert status == (
        "PROMISING_NESTED_"
        "CONJUNCTION_CANDIDATE"
    )


def test_failed_status_when_only_two_folds_win():
    status = result_status(
        markets_beating_fixed=5,
        active_folds_beating_fixed=2,
        aggregate_improvement=5.0,
        reduced_trades=30,
    )

    assert status == (
        "NESTED_CONJUNCTION_"
        "DEVELOPMENT_FAILED"
    )
