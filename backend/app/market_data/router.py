from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter

from app.market_data.csv_loader import load_candles_from_csv
from app.market_data.models import Candle

router = APIRouter(
    prefix="/market-data",
    tags=["Market Data"],
)


@router.get("/sample-candles", response_model=list[Candle])
def get_sample_candles() -> list[Candle]:
    return [
        Candle(
            symbol="EUR_USD",
            timeframe="H1",
            timestamp=datetime(2026, 7, 3, 8, 0, tzinfo=UTC),
            open=1.1720,
            high=1.1742,
            low=1.1710,
            close=1.1735,
            volume=1200,
        ),
        Candle(
            symbol="EUR_USD",
            timeframe="H1",
            timestamp=datetime(2026, 7, 3, 9, 0, tzinfo=UTC),
            open=1.1735,
            high=1.1760,
            low=1.1728,
            close=1.1754,
            volume=1350,
        ),
    ]


@router.get("/csv-sample", response_model=list[Candle])
def get_csv_sample_candles() -> list[Candle]:
    file_path = Path("data/eur_usd_sample.csv")
    return load_candles_from_csv(file_path)
