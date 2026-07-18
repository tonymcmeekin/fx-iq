from __future__ import annotations

from collections.abc import Sequence


def percentage_change(start: float, end: float) -> float | None:
    if start == 0:
        return None

    return ((end - start) / start) * 100.0


def exponential_moving_average(
    values: Sequence[float],
    period: int,
) -> float | None:
    if period <= 0:
        raise ValueError("period must be positive")

    if len(values) < period:
        return None

    result = sum(values[:period]) / period
    multiplier = 2.0 / (period + 1.0)

    for value in values[period:]:
        result = ((value - result) * multiplier) + result

    return result


def average_true_range(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> float | None:
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError(
            "highs, lows and closes must have equal lengths"
        )

    if len(closes) < period + 1:
        return None

    true_ranges: list[float] = []

    for index in range(1, len(closes)):
        true_ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )

    atr = sum(true_ranges[:period]) / period

    for true_range in true_ranges[period:]:
        atr = (
            (atr * (period - 1)) + true_range
        ) / period

    return atr


def relative_strength_index(
    closes: Sequence[float],
    period: int = 14,
) -> float | None:
    if len(closes) < period + 1:
        return None

    changes = [
        closes[index] - closes[index - 1]
        for index in range(1, len(closes))
    ]

    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]

    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    for gain, loss in zip(
        gains[period:],
        losses[period:],
        strict=True,
    ):
        average_gain = (
            (average_gain * (period - 1)) + gain
        ) / period
        average_loss = (
            (average_loss * (period - 1)) + loss
        ) / period

    if average_loss == 0:
        return 100.0

    relative_strength = average_gain / average_loss

    return 100.0 - (
        100.0 / (1.0 + relative_strength)
    )


def range_position(
    current: float,
    recent_low: float,
    recent_high: float,
) -> float | None:
    price_range = recent_high - recent_low

    if price_range <= 0:
        return None

    return (current - recent_low) / price_range
