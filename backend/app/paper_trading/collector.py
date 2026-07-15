from collections.abc import Callable
from datetime import UTC, datetime

from app.market_data.models import Candle
from app.market_data.oanda import (
    convert_oanda_payload_to_rows,
    download_oanda_candles,
)


DownloadFunction = Callable[..., dict]


def row_to_candle(
    row: dict,
) -> Candle:
    timestamp = datetime.fromisoformat(
        str(row["timestamp"]).replace(
            "Z",
            "+00:00",
        )
    )

    if timestamp.tzinfo is None:
        raise ValueError(
            "Collected candle timestamp must be "
            "timezone-aware."
        )

    return Candle(
        symbol=str(row["symbol"]),
        timeframe=str(row["timeframe"]),
        timestamp=timestamp.astimezone(UTC),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
    )


def rows_to_candles(
    rows: list[dict],
) -> list[Candle]:
    candles = [
        row_to_candle(row)
        for row in rows
    ]

    timestamps = [
        candle.timestamp
        for candle in candles
    ]

    if timestamps != sorted(timestamps):
        raise ValueError(
            "Collected candles are not chronological."
        )

    if len(timestamps) != len(
        set(timestamps)
    ):
        raise ValueError(
            "Collected candles contain duplicate "
            "timestamps."
        )

    return candles


def merge_candles(
    existing: list[Candle],
    incoming: list[Candle],
) -> list[Candle]:
    combined: dict[
        datetime,
        Candle,
    ] = {}

    for candle in [
        *existing,
        *incoming,
    ]:
        timestamp = candle.timestamp.astimezone(
            UTC
        )

        if timestamp in combined:
            previous = combined[
                timestamp
            ]

            if previous != candle:
                raise ValueError(
                    "Conflicting candle data exists for "
                    f"{timestamp.isoformat()}."
                )

            continue

        combined[timestamp] = candle

    merged = [
        combined[timestamp]
        for timestamp in sorted(combined)
    ]

    if merged:
        symbols = {
            candle.symbol
            for candle in merged
        }

        timeframes = {
            candle.timeframe
            for candle in merged
        }

        if len(symbols) != 1:
            raise ValueError(
                "Cannot merge candles from different "
                "markets."
            )

        if timeframes != {"D"}:
            raise ValueError(
                "Prospective candles must use daily "
                "granularity."
            )

    return merged


def collect_complete_daily_candles(
    *,
    api_token: str,
    instrument: str,
    environment: str = "practice",
    count: int = 100,
    downloader: DownloadFunction = (
        download_oanda_candles
    ),
) -> list[Candle]:
    if environment != "practice":
        raise RuntimeError(
            "Prospective paper collection is restricted "
            "to the OANDA practice environment."
        )

    if not api_token.strip():
        raise ValueError(
            "OANDA API token is required."
        )

    if count < 21 or count > 5000:
        raise ValueError(
            "Collection count must be between "
            "21 and 5000."
        )

    payload = downloader(
        api_token=api_token,
        instrument=instrument,
        granularity="D",
        count=count,
        environment="practice",
    )

    rows = convert_oanda_payload_to_rows(
        payload=payload,
        instrument=instrument,
        timeframe="D",
    )

    candles = rows_to_candles(
        rows
    )

    for candle in candles:
        if candle.symbol != instrument:
            raise ValueError(
                "Collected candle symbol does not match "
                "the requested instrument."
            )

        if candle.timeframe != "D":
            raise ValueError(
                "Collected candle timeframe is not D."
            )

    return candles
