import argparse
import csv
from collections import Counter
from datetime import datetime
from pathlib import Path


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_csv(file_path: Path) -> int:
    errors: list[str] = []
    timestamps: list[datetime] = []
    symbols: list[str] = []
    timeframes: list[str] = []

    with file_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)

        required_columns = {
            "timestamp",
            "symbol",
            "timeframe",
            "open",
            "high",
            "low",
            "close",
            "volume",
        }

        actual_columns = set(reader.fieldnames or [])
        missing_columns = required_columns - actual_columns

        if missing_columns:
            print("VALIDATION FAILED")
            print("Missing columns:", ", ".join(sorted(missing_columns)))
            return 1

        rows = list(reader)

    if not rows:
        print("VALIDATION FAILED")
        print("Dataset contains no candles.")
        return 1

    for row_number, row in enumerate(rows, start=2):
        try:
            timestamp = parse_timestamp(row["timestamp"])
            open_price = float(row["open"])
            high_price = float(row["high"])
            low_price = float(row["low"])
            close_price = float(row["close"])
            volume = float(row["volume"])
        except (TypeError, ValueError) as error:
            errors.append(
                f"Row {row_number}: invalid value ({error})"
            )
            continue

        timestamps.append(timestamp)
        symbols.append(row["symbol"])
        timeframes.append(row["timeframe"])

        if min(open_price, high_price, low_price, close_price) <= 0:
            errors.append(
                f"Row {row_number}: prices must be greater than zero"
            )

        if high_price < max(open_price, close_price, low_price):
            errors.append(
                f"Row {row_number}: high price is inconsistent"
            )

        if low_price > min(open_price, close_price, high_price):
            errors.append(
                f"Row {row_number}: low price is inconsistent"
            )

        if volume < 0:
            errors.append(
                f"Row {row_number}: volume cannot be negative"
            )

    duplicate_timestamps = [
        timestamp
        for timestamp, count in Counter(timestamps).items()
        if count > 1
    ]

    if duplicate_timestamps:
        errors.append(
            f"Duplicate timestamps found: {len(duplicate_timestamps)}"
        )

    out_of_order = sum(
        timestamps[index] <= timestamps[index - 1]
        for index in range(1, len(timestamps))
    )

    if out_of_order:
        errors.append(
            f"Out-of-order timestamps found: {out_of_order}"
        )

    gaps = [
        timestamps[index] - timestamps[index - 1]
        for index in range(1, len(timestamps))
    ]

    largest_gap = max(gaps) if gaps else None

    print("MARKET DATA QUALITY REPORT")
    print("=" * 60)
    print("File:", file_path)
    print("Candles:", len(rows))
    print("Start:", timestamps[0].isoformat())
    print("End:", timestamps[-1].isoformat())
    print("Symbols:", ", ".join(sorted(set(symbols))))
    print("Timeframes:", ", ".join(sorted(set(timeframes))))
    print("Duplicate timestamps:", len(duplicate_timestamps))
    print("Out-of-order timestamps:", out_of_order)
    print("Largest time gap:", largest_gap)
    print("Validation errors:", len(errors))

    if errors:
        print()
        print("VALIDATION FAILED")
        for error in errors[:20]:
            print("-", error)

        if len(errors) > 20:
            print(f"- Additional errors not shown: {len(errors) - 20}")

        return 1

    print()
    print("VALIDATION PASSED")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "file",
        nargs="?",
        default="data/eur_usd_daily.csv",
    )
    arguments = parser.parse_args()

    raise SystemExit(validate_csv(Path(arguments.file)))


if __name__ == "__main__":
    main()
