from datetime import UTC, datetime

import pytest

from app.market_data.models import Candle
from app.paper_trading.collector import (
    collect_complete_daily_candles,
    merge_candles,
    rows_to_candles,
)


def complete_candle(
    timestamp: str,
    *,
    close: str = "1.1050",
) -> dict:
    return {
        "complete": True,
        "time": timestamp,
        "mid": {
            "o": "1.1000",
            "h": "1.1100",
            "l": "1.0900",
            "c": close,
        },
        "volume": 1000,
    }


def test_collection_uses_practice_daily_midpoint():
    calls = []

    def fake_downloader(**kwargs):
        calls.append(kwargs)

        return {
            "candles": [
                complete_candle(
                    "2026-07-14T21:00:00Z"
                ),
            ],
        }

    candles = (
        collect_complete_daily_candles(
            api_token="test-token",
            instrument="EUR_GBP",
            count=21,
            downloader=fake_downloader,
        )
    )

    assert calls == [
        {
            "api_token": "test-token",
            "instrument": "EUR_GBP",
            "granularity": "D",
            "count": 21,
            "environment": "practice",
        }
    ]

    assert len(candles) == 1
    assert candles[0].symbol == "EUR_GBP"
    assert candles[0].timeframe == "D"


def test_collection_rejects_live_environment():
    with pytest.raises(
        RuntimeError,
        match="practice environment",
    ):
        collect_complete_daily_candles(
            api_token="token",
            instrument="EUR_GBP",
            environment="live",
            count=21,
            downloader=lambda **_: {},
        )


def test_incomplete_candle_is_excluded():
    def fake_downloader(**kwargs):
        return {
            "candles": [
                complete_candle(
                    "2026-07-14T21:00:00Z"
                ),
                {
                    **complete_candle(
                        "2026-07-15T21:00:00Z"
                    ),
                    "complete": False,
                },
            ],
        }

    candles = (
        collect_complete_daily_candles(
            api_token="token",
            instrument="EUR_GBP",
            count=21,
            downloader=fake_downloader,
        )
    )

    assert len(candles) == 1

    assert candles[
        0
    ].timestamp == datetime(
        2026,
        7,
        14,
        21,
        0,
        tzinfo=UTC,
    )


def test_rows_must_be_chronological():
    rows = [
        {
            "timestamp": (
                "2026-07-15T21:00:00Z"
            ),
            "symbol": "EUR_GBP",
            "timeframe": "D",
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.0,
            "volume": 1,
        },
        {
            "timestamp": (
                "2026-07-14T21:00:00Z"
            ),
            "symbol": "EUR_GBP",
            "timeframe": "D",
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.0,
            "volume": 1,
        },
    ]

    with pytest.raises(
        ValueError,
        match="not chronological",
    ):
        rows_to_candles(
            rows
        )


def test_merge_is_idempotent():
    candle = Candle(
        symbol="EUR_GBP",
        timeframe="D",
        timestamp=datetime(
            2026,
            7,
            14,
            21,
            0,
            tzinfo=UTC,
        ),
        open=1.0,
        high=1.1,
        low=0.9,
        close=1.0,
        volume=100,
    )

    assert merge_candles(
        [candle],
        [candle],
    ) == [candle]


def test_conflicting_duplicate_is_rejected():
    timestamp = datetime(
        2026,
        7,
        14,
        21,
        0,
        tzinfo=UTC,
    )

    first = Candle(
        symbol="EUR_GBP",
        timeframe="D",
        timestamp=timestamp,
        open=1.0,
        high=1.1,
        low=0.9,
        close=1.0,
        volume=100,
    )

    second = first.model_copy(
        update={
            "close": 1.05,
        }
    )

    with pytest.raises(
        ValueError,
        match="Conflicting candle",
    ):
        merge_candles(
            [first],
            [second],
        )
