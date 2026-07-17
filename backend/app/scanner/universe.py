from typing import Literal

from pydantic import BaseModel, Field

MarketScenario = Literal["TRENDING_UP", "TRENDING_DOWN", "RANGING"]


class ScannerMarketDefinition(BaseModel):
    symbol: str
    timeframe: str
    scenario: MarketScenario
    start_price: float = Field(gt=0)
    movement: float = Field(gt=0)
    breakout_offset: float = Field(gt=0)


DEFAULT_MARKET_UNIVERSE: tuple[ScannerMarketDefinition, ...] = (
    ScannerMarketDefinition(
        symbol="EUR_USD",
        timeframe="H1",
        scenario="TRENDING_UP",
        start_price=1.1000,
        movement=0.0006,
        breakout_offset=0.0010,
    ),
    ScannerMarketDefinition(
        symbol="GBP_USD",
        timeframe="H4",
        scenario="TRENDING_UP",
        start_price=1.2500,
        movement=0.00045,
        breakout_offset=0.0009,
    ),
    ScannerMarketDefinition(
        symbol="USD_JPY",
        timeframe="H1",
        scenario="TRENDING_DOWN",
        start_price=154.000,
        movement=0.045,
        breakout_offset=0.090,
    ),
    ScannerMarketDefinition(
        symbol="AUD_USD",
        timeframe="M15",
        scenario="TRENDING_UP",
        start_price=0.6600,
        movement=0.00022,
        breakout_offset=0.0007,
    ),
    ScannerMarketDefinition(
        symbol="EUR_GBP",
        timeframe="H1",
        scenario="RANGING",
        start_price=0.8600,
        movement=0.00025,
        breakout_offset=0.0005,
    ),
    ScannerMarketDefinition(
        symbol="GBP_JPY",
        timeframe="H4",
        scenario="TRENDING_UP",
        start_price=198.000,
        movement=0.060,
        breakout_offset=0.120,
    ),
    ScannerMarketDefinition(
        symbol="NZD_USD",
        timeframe="H1",
        scenario="RANGING",
        start_price=0.6100,
        movement=0.00020,
        breakout_offset=0.0004,
    ),
    ScannerMarketDefinition(
        symbol="USD_CAD",
        timeframe="D1",
        scenario="TRENDING_DOWN",
        start_price=1.3800,
        movement=0.0005,
        breakout_offset=0.0010,
    ),
)
