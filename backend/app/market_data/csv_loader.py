import csv
from datetime import datetime
from pathlib import Path

from app.market_data.models import Candle


def load_candles_from_csv(file_path: Path) -> list[Candle]:
    candles: list[Candle] = []

    with file_path.open(newline="") as csvfile:
        reader = csv.DictReader(csvfile)

        for row in reader:
            candles.append(
                Candle(
                    timestamp=datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")),
                    symbol=row["symbol"],
                    timeframe=row["timeframe"],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["volume"]),
                )
            )

    return candles
