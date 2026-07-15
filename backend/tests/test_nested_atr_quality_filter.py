from scripts.nested_atr_quality_filter_walk_forward import (
    learn_thresholds,
    quality_decision,
    thresholds_available,
)


def sample_records():
    return [
        {
            "directional_close_location": 0.70,
            "channel_width_atr": 3.0,
            "momentum_20_atr": 2.0,
        },
        {
            "directional_close_location": 0.80,
            "channel_width_atr": 4.0,
            "momentum_20_atr": 3.0,
        },
        {
            "directional_close_location": 0.90,
            "channel_width_atr": 5.0,
            "momentum_20_atr": 4.0,
        },
    ]


def test_learn_thresholds_returns_expected_keys():
    thresholds = learn_thresholds(
        sample_records()
    )

    assert set(thresholds) == {
        "minimum_close_location",
        "maximum_channel_width",
        "maximum_momentum_20",
    }


def test_close_location_policy_rejects_weak_close():
    thresholds = {
        "minimum_close_location": 0.80,
        "maximum_channel_width": 4.5,
        "maximum_momentum_20": 3.5,
    }

    features = {
        "directional_close_location": 0.75,
        "channel_width_atr": 3.0,
        "momentum_20_atr": 2.0,
    }

    assert not quality_decision(
        features,
        thresholds,
        "close_location",
    )


def test_channel_width_policy_rejects_wide_channel():
    thresholds = {
        "minimum_close_location": 0.80,
        "maximum_channel_width": 4.5,
        "maximum_momentum_20": 3.5,
    }

    features = {
        "directional_close_location": 0.90,
        "channel_width_atr": 5.0,
        "momentum_20_atr": 2.0,
    }

    assert not quality_decision(
        features,
        thresholds,
        "channel_width",
    )


def test_momentum_policy_rejects_overextended_signal():
    thresholds = {
        "minimum_close_location": 0.80,
        "maximum_channel_width": 4.5,
        "maximum_momentum_20": 3.5,
    }

    features = {
        "directional_close_location": 0.90,
        "channel_width_atr": 3.0,
        "momentum_20_atr": 4.0,
    }

    assert not quality_decision(
        features,
        thresholds,
        "momentum_20",
    )


def test_combined_policy_requires_every_condition():
    thresholds = {
        "minimum_close_location": 0.80,
        "maximum_channel_width": 4.5,
        "maximum_momentum_20": 3.5,
    }

    approved = {
        "directional_close_location": 0.90,
        "channel_width_atr": 4.0,
        "momentum_20_atr": 3.0,
    }

    rejected = {
        "directional_close_location": 0.90,
        "channel_width_atr": 5.0,
        "momentum_20_atr": 3.0,
    }

    assert quality_decision(
        approved,
        thresholds,
        "combined",
    )

    assert not quality_decision(
        rejected,
        thresholds,
        "combined",
    )


def test_thresholds_require_two_folds_and_records():
    records = [{}] * 150

    assert not thresholds_available(
        records,
        fold_number=2,
    )

    assert thresholds_available(
        records,
        fold_number=3,
    )

    assert not thresholds_available(
        records[:149],
        fold_number=3,
    )
