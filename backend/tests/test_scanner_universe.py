from app.scanner.engine import (
    build_market_request,
    build_scan_requests,
    scan_opportunities,
)
from app.scanner.universe import (
    DEFAULT_MARKET_UNIVERSE,
    ScannerMarketDefinition,
)


def test_default_universe_contains_multiple_symbols():
    symbols = {
        market.symbol
        for market in DEFAULT_MARKET_UNIVERSE
    }

    assert len(DEFAULT_MARKET_UNIVERSE) == 8
    assert len(symbols) == 8


def test_default_universe_contains_multiple_timeframes():
    timeframes = {
        market.timeframe
        for market in DEFAULT_MARKET_UNIVERSE
    }

    assert timeframes == {
        "M15",
        "H1",
        "H4",
        "D1",
    }


def test_market_definition_builds_decision_request():
    market = ScannerMarketDefinition(
        symbol="TEST_USD",
        timeframe="H4",
        scenario="TRENDING_UP",
        start_price=1.0000,
        movement=0.0005,
        breakout_offset=0.0010,
    )

    request = build_market_request(market)

    assert request.candles
    assert all(
        candle.symbol == "TEST_USD"
        for candle in request.candles
    )
    assert all(
        candle.timeframe == "H4"
        for candle in request.candles
    )


def test_default_universe_builds_one_request_per_market():
    requests = build_scan_requests(
        DEFAULT_MARKET_UNIVERSE
    )

    assert len(requests) == len(
        DEFAULT_MARKET_UNIVERSE
    )


def test_default_universe_can_be_scanned():
    requests = build_scan_requests(
        DEFAULT_MARKET_UNIVERSE
    )

    result = scan_opportunities(requests)

    assert result.evaluated_markets == 8
    assert len(result.opportunities) == 8
    assert [
        opportunity.rank
        for opportunity in result.opportunities
    ] == list(range(1, 9))


def test_custom_universe_can_be_scanned():
    universe = (
        ScannerMarketDefinition(
            symbol="EUR_USD",
            timeframe="H1",
            scenario="TRENDING_UP",
            start_price=1.1000,
            movement=0.0006,
            breakout_offset=0.0010,
        ),
        ScannerMarketDefinition(
            symbol="EUR_GBP",
            timeframe="H1",
            scenario="RANGING",
            start_price=0.8600,
            movement=0.00025,
            breakout_offset=0.0005,
        ),
    )

    result = scan_opportunities(
        build_scan_requests(universe)
    )

    assert result.evaluated_markets == 2
