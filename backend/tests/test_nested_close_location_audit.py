from scripts.audit_nested_close_location_rejections import (
    account_return,
    classify,
    learn_threshold,
    statistics,
)


def records():
    return [
        {
            "directional_close_location": 0.70,
            "account_return": -0.50,
            "net_pnl": -50.0,
        },
        {
            "directional_close_location": 0.80,
            "account_return": 0.25,
            "net_pnl": 25.0,
        },
        {
            "directional_close_location": 0.90,
            "account_return": 0.50,
            "net_pnl": 50.0,
        },
    ]


def test_account_return_supports_expected_key():
    assert account_return(
        {
            "account_return": 0.25,
        }
    ) == 0.25


def test_threshold_is_inside_observed_range():
    threshold = learn_threshold(
        records()
    )

    assert 0.70 <= threshold <= 0.90


def test_classify_splits_at_threshold():
    accepted, rejected = classify(
        records(),
        threshold=0.80,
    )

    assert len(accepted) == 1
    assert len(rejected) == 2


def test_statistics_calculates_total_return():
    result = statistics(
        records()
    )

    assert result["trades"] == 3
    assert result["total_return"] == 0.25


def test_rejected_group_is_negative():
    _, rejected = classify(
        records(),
        threshold=0.80,
    )

    result = statistics(
        rejected
    )

    assert result["total_return"] < 0
