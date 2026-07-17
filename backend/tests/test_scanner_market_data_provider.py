from datetime import UTC, datetime, timedelta

import pytest

from app.market_data.models import Candle
from app.market_data.providers.oanda_read_only import (
    OANDA_GRANULARITY_BY_TIMEFRAME,
    OandaReadOnlyMarketDataProvider,
)
from app.scanner.engine import (
    build_provider_scan_requests,
    scan_opportunities,
)
from app.scanner.universe import DEFAULT_MARKET_UNIVERSE


class FakeMarketDataProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.network_calls_made = 0

    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int,
    ) -> list[Candle]:
        self.network_calls_made += 1

        start = datetime(2026, 1, 1, tzinfo=UTC)
        base_price = 150.0 if "JPY" in symbol else 1.1
        movement = 0.03 if "JPY" in symbol else 0.0005

        return [
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=start + timedelta(hours=index),
                open=base_price + index * movement,
                high=base_price + index * movement + movement,
                low=base_price + index * movement - movement,
                close=base_price + index * movement,
                volume=1000 + index,
            )
            for index in range(count)
        ]


def test_provider_scan_preserves_market_universe():
    provider = FakeMarketDataProvider()

    requests = build_provider_scan_requests(
        provider=provider,
        universe=DEFAULT_MARKET_UNIVERSE,
        candle_count=100,
    )

    result = scan_opportunities(
        requests=requests,
        network_calls_made=provider.network_calls_made,
    )

    assert result.evaluated_markets == 8
    assert result.network_calls_made == 8
    assert result.live_trading_allowed is False
    assert result.broker_orders_submitted == 0
    assert result.ledger_writes_performed == 0

    returned_markets = {
        (
            opportunity.symbol,
            opportunity.timeframe,
        )
        for opportunity in result.opportunities
    }

    expected_markets = {
        (
            market.symbol,
            market.timeframe,
        )
        for market in DEFAULT_MARKET_UNIVERSE
    }

    assert returned_markets == expected_markets


def test_oanda_provider_scanner_timeframe_mapping():
    assert OANDA_GRANULARITY_BY_TIMEFRAME == {
        "M15": "M15",
        "H1": "H1",
        "H4": "H4",
        "D1": "D",
    }


def test_oanda_provider_requires_token():
    with pytest.raises(
        ValueError,
        match="OANDA API token is required",
    ):
        OandaReadOnlyMarketDataProvider(api_token="")


def test_oanda_provider_rejects_unknown_timeframe():
    provider = OandaReadOnlyMarketDataProvider(
        api_token="test-token",
    )

    with pytest.raises(
        ValueError,
        match="Unsupported scanner timeframe",
    ):
        provider.get_candles(
            symbol="EUR_USD",
            timeframe="M5",
            count=100,
        )

    assert provider.network_calls_made == 0
