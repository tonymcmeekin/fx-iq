from app.features import (
    FeatureCandle,
    build_market_features,
    evaluate_setup_quality,
)


def make_trending_candles(
    count: int = 80,
    step: float = 0.001,
) -> list[FeatureCandle]:
    return [
        FeatureCandle(
            high=1.10 + index * step + 0.0005,
            low=1.10 + index * step - 0.0005,
            close=1.10 + index * step,
        )
        for index in range(count)
    ]


def test_setup_quality_is_bounded():
    features = build_market_features(
        make_trending_candles()
    )

    quality = evaluate_setup_quality(features)

    assert 0 <= quality.score <= 100
    assert quality.label in {
        "STRONG",
        "GOOD",
        "MIXED",
        "WEAK",
    }


def test_setup_quality_is_deterministic():
    features = build_market_features(
        make_trending_candles()
    )

    first = evaluate_setup_quality(features)
    second = evaluate_setup_quality(features)

    assert first == second


def test_setup_quality_contains_explanation_and_reasons():
    features = build_market_features(
        make_trending_candles()
    )

    quality = evaluate_setup_quality(features)

    assert quality.explanation
    assert quality.reasons
    assert str(quality.score) in quality.explanation
