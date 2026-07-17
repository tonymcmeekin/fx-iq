from typing import Protocol

from app.market_data.models import Candle


class MarketDataProvider(Protocol):
    provider_name: str
    network_calls_made: int

    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int,
    ) -> list[Candle]:
        """Return completed read-only market candles."""
        ...
