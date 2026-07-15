import csv
import os
from datetime import UTC, date, datetime
from pathlib import Path

from app.market_data.models import Candle
from app.paper_trading.collector import (
    merge_candles,
)


FIELDNAMES = [
    "timestamp",
    "symbol",
    "timeframe",
    "open",
    "high",
    "low",
    "close",
    "volume",
]


class CandleStoreError(RuntimeError):
    """Raised when prospective candle storage is invalid."""


def utc_isoformat(
    value: datetime,
) -> str:
    if value.tzinfo is None:
        raise ValueError(
            "Candle timestamp must be timezone-aware."
        )

    return (
        value.astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def candle_to_row(
    candle: Candle,
) -> dict:
    if candle.timestamp.tzinfo is None:
        raise ValueError(
            "Candle timestamp must be timezone-aware."
        )

    if candle.timeframe != "D":
        raise ValueError(
            "Prospective candle timeframe must be D."
        )

    return {
        "timestamp": utc_isoformat(
            candle.timestamp
        ),
        "symbol": candle.symbol,
        "timeframe": candle.timeframe,
        "open": repr(float(candle.open)),
        "high": repr(float(candle.high)),
        "low": repr(float(candle.low)),
        "close": repr(float(candle.close)),
        "volume": repr(float(candle.volume)),
    }


def row_to_candle(
    row: dict,
) -> Candle:
    missing = (
        set(FIELDNAMES) - row.keys()
    )

    if missing:
        raise CandleStoreError(
            "Stored candle is missing fields: "
            + ", ".join(sorted(missing))
            + "."
        )

    try:
        timestamp = datetime.fromisoformat(
            str(row["timestamp"]).replace(
                "Z",
                "+00:00",
            )
        )
    except ValueError as error:
        raise CandleStoreError(
            "Stored candle timestamp is invalid."
        ) from error

    if timestamp.tzinfo is None:
        raise CandleStoreError(
            "Stored candle timestamp is timezone-naive."
        )

    try:
        candle = Candle(
            timestamp=timestamp.astimezone(UTC),
            symbol=str(row["symbol"]),
            timeframe=str(row["timeframe"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
    except (TypeError, ValueError) as error:
        raise CandleStoreError(
            "Stored candle values are invalid."
        ) from error

    if candle.timeframe != "D":
        raise CandleStoreError(
            "Stored prospective candle timeframe is not D."
        )

    return candle


def read_candle_store(
    store_path: Path,
    *,
    expected_symbol: str | None = None,
) -> list[Candle]:
    if not store_path.exists():
        return []

    candles = []

    try:
        with store_path.open(
            newline="",
            encoding="utf-8",
        ) as input_file:
            reader = csv.DictReader(
                input_file
            )

            if reader.fieldnames != FIELDNAMES:
                raise CandleStoreError(
                    "Prospective candle-store header "
                    "does not match the frozen format."
                )

            for line_number, row in enumerate(
                reader,
                start=2,
            ):
                try:
                    candle = row_to_candle(
                        row
                    )
                except CandleStoreError as error:
                    raise CandleStoreError(
                        f"Invalid stored candle at "
                        f"line {line_number}: {error}"
                    ) from error

                candles.append(
                    candle
                )

    except UnicodeDecodeError as error:
        raise CandleStoreError(
            "Prospective candle store is not valid UTF-8."
        ) from error

    timestamps = [
        candle.timestamp
        for candle in candles
    ]

    if timestamps != sorted(timestamps):
        raise CandleStoreError(
            "Stored prospective candles are not chronological."
        )

    if len(timestamps) != len(
        set(timestamps)
    ):
        raise CandleStoreError(
            "Stored prospective candles contain duplicate timestamps."
        )

    symbols = {
        candle.symbol
        for candle in candles
    }

    if len(symbols) > 1:
        raise CandleStoreError(
            "Stored prospective candles contain multiple markets."
        )

    if (
        expected_symbol is not None
        and symbols
        and symbols != {expected_symbol}
    ):
        raise CandleStoreError(
            "Stored candle market does not match "
            "the expected market."
        )

    return candles


def write_candle_store(
    store_path: Path,
    candles: list[Candle],
    *,
    expected_symbol: str,
) -> None:
    timestamps = [
        candle.timestamp.astimezone(UTC)
        for candle in candles
    ]

    if timestamps != sorted(timestamps):
        raise CandleStoreError(
            "Candles must be chronological before storage."
        )

    if len(timestamps) != len(
        set(timestamps)
    ):
        raise CandleStoreError(
            "Candles must not contain duplicate timestamps."
        )

    for candle in candles:
        if candle.symbol != expected_symbol:
            raise CandleStoreError(
                "Candle market does not match the "
                "target prospective store."
            )

        if candle.timeframe != "D":
            raise CandleStoreError(
                "Prospective candle timeframe must be D."
            )

    store_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = (
        store_path.parent
        / f".{store_path.name}.tmp"
    )

    file_descriptor = os.open(
        temporary_path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_TRUNC,
        0o600,
    )

    try:
        with os.fdopen(
            file_descriptor,
            "w",
            newline="",
            encoding="utf-8",
            closefd=False,
        ) as output_file:
            writer = csv.DictWriter(
                output_file,
                fieldnames=FIELDNAMES,
                lineterminator="\n",
            )

            writer.writeheader()

            for candle in candles:
                writer.writerow(
                    candle_to_row(
                        candle
                    )
                )

            output_file.flush()

        os.fsync(
            file_descriptor
        )
    finally:
        os.close(
            file_descriptor
        )

    os.replace(
        temporary_path,
        store_path,
    )

    directory_descriptor = os.open(
        store_path.parent,
        os.O_RDONLY,
    )

    try:
        os.fsync(
            directory_descriptor
        )
    finally:
        os.close(
            directory_descriptor
        )

    verified = read_candle_store(
        store_path,
        expected_symbol=expected_symbol,
    )

    if verified != candles:
        raise CandleStoreError(
            "Written prospective candle store "
            "could not be verified."
        )


def persist_prospective_candles(
    store_path: Path,
    incoming_candles: list[Candle],
    *,
    expected_symbol: str,
    first_eligible_market_date: date,
) -> dict:
    for candle in incoming_candles:
        if candle.symbol != expected_symbol:
            raise CandleStoreError(
                "Incoming candle market does not match "
                "the expected market."
            )

        if candle.timeframe != "D":
            raise CandleStoreError(
                "Incoming prospective candle timeframe "
                "must be D."
            )

    prospective_incoming = [
        candle
        for candle in incoming_candles
        if (
            candle.timestamp
            .astimezone(UTC)
            .date()
            >= first_eligible_market_date
        )
    ]

    existing = read_candle_store(
        store_path,
        expected_symbol=expected_symbol,
    )

    try:
        merged = merge_candles(
            existing,
            prospective_incoming,
        )
    except ValueError as error:
        raise CandleStoreError(
            str(error)
        ) from error

    added = len(merged) - len(existing)

    if added > 0:
        write_candle_store(
            store_path,
            merged,
            expected_symbol=expected_symbol,
        )

    return {
        "market": expected_symbol,
        "store_path": str(store_path),
        "existing_candles": len(existing),
        "incoming_complete_candles": len(
            incoming_candles
        ),
        "eligible_incoming_candles": len(
            prospective_incoming
        ),
        "candles_added": added,
        "candles_total": len(merged),
        "first_timestamp": (
            utc_isoformat(
                merged[0].timestamp
            )
            if merged
            else None
        ),
        "last_timestamp": (
            utc_isoformat(
                merged[-1].timestamp
            )
            if merged
            else None
        ),
    }
