from datetime import UTC, datetime

from app.ai.external_validation import (
    EXPECTED_SHA256,
    EXTERNAL_MARKETS,
    build_external_validation_protocol,
)


def test_protocol_contains_three_external_markets():
    protocol = build_external_validation_protocol()

    assert len(protocol.markets) == 3

    assert {
        market.symbol
        for market in protocol.markets
    } == {
        "USD_JPY",
        "USD_CAD",
        "NZD_USD",
    }


def test_holdout_boundary_is_frozen():
    protocol = build_external_validation_protocol()

    assert protocol.holdout_start == datetime(
        2024,
        8,
        5,
        0,
        0,
        tzinfo=UTC,
    )


def test_strategy_logic_is_frozen():
    protocol = build_external_validation_protocol()

    assert protocol.strategy_logic_frozen is True
    assert (
        protocol.parameter_tuning_after_holdout_prohibited
        is True
    )
    assert protocol.holdout_may_be_opened_once is True


def test_every_market_has_checksum_and_path():
    for symbol, path in EXTERNAL_MARKETS.items():
        assert path.name.startswith("oanda_")
        assert path.suffix == ".csv"
        assert len(EXPECTED_SHA256[symbol]) == 64


def test_protocol_records_freeze_commit():
    protocol = build_external_validation_protocol()

    assert protocol.freeze_commit == "cd66c9b"
