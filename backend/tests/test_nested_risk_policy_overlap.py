import pytest

from scripts.audit_nested_risk_policy_overlap import (
    classify_overlap,
    partition_records,
    statistics,
)


REDUCED_GROUP = (
    "TRENDING_UP",
    "NORMAL",
    "BUY",
)


def make_record(
    *,
    close_location=0.9,
    trend="RANGING",
    volatility="NORMAL",
    direction="BUY",
    return_percent=0.1,
    net_pnl=10.0,
    market="EUR_USD",
    fold=3,
):
    return {
        "market": market,
        "fold": fold,
        "trend": trend,
        "volatility": volatility,
        "direction": direction,
        "directional_close_location": (
            close_location
        ),
        "return": return_percent,
        "net_pnl": net_pnl,
    }


def test_classifies_neither_rule():
    result = classify_overlap(
        record=make_record(),
        close_threshold=0.8,
        reduced_regime_groups={
            REDUCED_GROUP
        },
    )

    assert result == "neither"


def test_classifies_close_only():
    result = classify_overlap(
        record=make_record(
            close_location=0.7
        ),
        close_threshold=0.8,
        reduced_regime_groups={
            REDUCED_GROUP
        },
    )

    assert result == "close_only"


def test_classifies_regime_only():
    result = classify_overlap(
        record=make_record(
            close_location=0.9,
            trend="TRENDING_UP",
            volatility="NORMAL",
            direction="BUY",
        ),
        close_threshold=0.8,
        reduced_regime_groups={
            REDUCED_GROUP
        },
    )

    assert result == "regime_only"


def test_classifies_both_rules():
    result = classify_overlap(
        record=make_record(
            close_location=0.7,
            trend="TRENDING_UP",
            volatility="NORMAL",
            direction="BUY",
        ),
        close_threshold=0.8,
        reduced_regime_groups={
            REDUCED_GROUP
        },
    )

    assert result == "both"


def test_threshold_boundary_is_weak_close():
    result = classify_overlap(
        record=make_record(
            close_location=0.8
        ),
        close_threshold=0.8,
        reduced_regime_groups=set(),
    )

    assert result == "close_only"


def test_partition_preserves_all_records():
    records = [
        make_record(
            close_location=0.9,
        ),
        make_record(
            close_location=0.7,
        ),
        make_record(
            close_location=0.9,
            trend="TRENDING_UP",
        ),
        make_record(
            close_location=0.7,
            trend="TRENDING_UP",
        ),
    ]

    groups = partition_records(
        records=records,
        close_threshold=0.8,
        reduced_regime_groups={
            REDUCED_GROUP
        },
    )

    assert sum(
        len(group)
        for group in groups.values()
    ) == len(records)

    assert len(groups["neither"]) == 1
    assert len(groups["close_only"]) == 1
    assert len(groups["regime_only"]) == 1
    assert len(groups["both"]) == 1


def test_statistics_calculates_average_and_total():
    records = [
        make_record(
            return_percent=0.2,
            net_pnl=20.0,
        ),
        make_record(
            return_percent=-0.1,
            net_pnl=-10.0,
        ),
    ]

    result = statistics(records)

    assert result["trades"] == 2
    assert result["win_rate"] == 50.0
    assert result["total_return"] == pytest.approx(
        0.1
    )
    assert result[
        "average_return"
    ] == pytest.approx(
        0.05
    )
    assert result[
        "profit_factor"
    ] == pytest.approx(
        2.0
    )


def test_statistics_handles_empty_records():
    result = statistics([])

    assert result["trades"] == 0
    assert result["win_rate"] == 0.0
    assert result["average_return"] == 0.0
    assert result["total_return"] == 0.0
    assert result["profit_factor"] == 0.0
