import csv
import math
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path


OUTPUT_FILE = Path("data/eur_usd_daily.csv")
START_DATE = datetime(2010, 1, 1, tzinfo=UTC)
CANDLE_COUNT = 4_000
RANDOM_SEED = 42


def generate_candles() -> list[dict]:
    random.seed(RANDOM_SEED)

    rows: list[dict] = []
    current_date = START_DATE
    previous_close = 1.43

    for index in range(CANDLE_COUNT):
        while current_date.weekday() >= 5:
            current_date += timedelta(days=1)

        long_cycle = math.sin(index / 180) * 0.0007
        short_cycle = math.sin(index / 23) * 0.00035
        random_move = random.gauss(0, 0.004)

        open_price = previous_close
        close_price = max(
            0.85,
            min(
                1.65,
                open_price * (1 + long_cycle + short_cycle + random_move),
            ),
        )

        intraday_range = abs(random.gauss(0.0045, 0.0018))

        high_price = max(open_price, close_price) * (1 + intraday_range)
        low_price = min(open_price, close_price) * (1 - intraday_range)

        volume = random.randint(80_000, 350_000)

        rows.append(
            {
                "timestamp": current_date.isoformat().replace("+00:00", "Z"),
                "symbol": "EUR_USD",
                "timeframe": "D1",
                "open": round(open_price, 6),
                "high": round(high_price, 6),
                "low": round(low_price, 6),
                "close": round(close_price, 6),
                "volume": volume,
            }
        )

        previous_close = close_price
        current_date += timedelta(days=1)

    return rows


def main() -> None:
    rows = generate_candles()

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "timestamp",
                "symbol",
                "timeframe",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {len(rows)} synthetic candles to {OUTPUT_FILE}")
    print("Dataset is deterministic and intended for development only.")


if __name__ == "__main__":
    main()
