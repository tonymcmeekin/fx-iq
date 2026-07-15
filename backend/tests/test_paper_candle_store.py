from datetime import (
    UTC,
    date,
    datetime,
)

import pytest

from app.market_data.models import Candle
from app.paper_trading.candle_store import (
    CandleStoreError,
    FIELDNAMES,
    candle_to_row,
    persist_prospective_candles,
    read_candle_store,
    write_candle_store,
)


START_DATE = date(
    2026,
    7,
    14,
)


def make_candle(
    timestamp: datetime,
    *,
    symbol: str = "EUR_GBP",
    close: float = 1.0,
) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe="D",
        timestamp=timestamp,
        open=1.0,
        high=max(1.1, close),
        low=min(0.9, close),
        close=close,
        volume=1000,
    )


def test_missing_store_is_empty(
    tmp_path,
):
    assert read_candle_store(
        tmp_path / "missing.csv",
        expected_symbol="EUR_GBP",
    ) == []


def test_candle_row_uses_frozen_fields():
    candle = make_candle(
        datetime(
            2026,
            7,
            14,
            21,
            0,
            tzinfo=UTC,
        )
    )

    row = candle_to_row(
        candle
    )

    assert list(row) == FIELDNAMES

    assert row[
        "timestamp"
    ] == "2026-07-14T21:00:00Z"

    assert row[
        "symbol"
    ] == "EUR_GBP"

    assert row[
        "timeframe"
    ] == "D"


def test_store_round_trip_is_atomic(
    tmp_path,
):
    store_path = (
        tmp_path / "eur_gbp.csv"
    )

    candles = [
        make_candle(
            datetime(
                2026,
                7,
                14,
                21,
                0,
                tzinfo=UTC,
            )
        ),
        make_candle(
            datetime(
                2026,
                7,
                15,
                21,
                0,
                tzinfo=UTC,
            ),
            close=1.02,
        ),
    ]

    write_candle_store(
        store_path,
        candles,
        expected_symbol="EUR_GBP",
    )

    assert read_candle_store(
        store_path,
        expected_symbol="EUR_GBP",
    ) == candles

    assert not (
        tmp_path / ".eur_gbp.csv.tmp"
    ).exists()


def test_pre_start_candles_are_not_persisted(
    tmp_path,
):
    store_path = (
        tmp_path / "eur_gbp.csv"
    )

    incoming = [
        make_candle(
            datetime(
                2026,
                7,
                13,
                21,
                0,
                tzinfo=UTC,
            )
        ),
        make_candle(
            datetime(
                2026,
                7,
                14,
                21,
                0,
                tzinfo=UTC,
            )
        ),
    ]

    result = (
        persist_prospective_candles(
            store_path,
            incoming,
            expected_symbol="EUR_GBP",
            first_eligible_market_date=(
                START_DATE
            ),
        )
    )

    stored = read_candle_store(
        store_path,
        expected_symbol="EUR_GBP",
    )

    assert len(stored) == 1

    assert stored[
        0
    ].timestamp == datetime(
        2026,
        7,
        14,
        21,
        0,
        tzinfo=UTC,
    )

    assert result[
        "incoming_complete_candles"
    ] == 2

    assert result[
        "eligible_incoming_candles"
    ] == 1

    assert result[
        "candles_added"
    ] == 1


def test_persistence_is_idempotent(
    tmp_path,
):
    store_path = (
        tmp_path / "eur_gbp.csv"
    )

    candle = make_candle(
        datetime(
            2026,
            7,
            14,
            21,
            0,
            tzinfo=UTC,
        )
    )

    first = persist_prospective_candles(
        store_path,
        [candle],
        expected_symbol="EUR_GBP",
        first_eligible_market_date=(
            START_DATE
        ),
    )

    second = persist_prospective_candles(
        store_path,
        [candle],
        expected_symbol="EUR_GBP",
        first_eligible_market_date=(
            START_DATE
        ),
    )

    assert first[
        "candles_added"
    ] == 1

    assert second[
        "candles_added"
    ] == 0

    assert second[
        "candles_total"
    ] == 1


def test_conflicting_existing_candle_is_rejected(
    tmp_path,
):
    store_path = (
        tmp_path / "eur_gbp.csv"
    )

    timestamp = datetime(
        2026,
        7,
        14,
        21,
        0,
        tzinfo=UTC,
    )

    original = make_candle(
        timestamp,
        close=1.0,
    )

    changed = make_candle(
        timestamp,
        close=1.05,
    )

    persist_prospective_candles(
        store_path,
        [original],
        expected_symbol="EUR_GBP",
        first_eligible_market_date=(
            START_DATE
        ),
    )

    with pytest.raises(
        CandleStoreError,
        match="Conflicting candle",
    ):
        persist_prospective_candles(
            store_path,
            [changed],
            expected_symbol="EUR_GBP",
            first_eligible_market_date=(
                START_DATE
            ),
        )


def test_store_rejects_wrong_symbol(
    tmp_path,
):
    with pytest.raises(
        CandleStoreError,
        match="does not match",
    ):
        persist_prospective_candles(
            tmp_path / "eur_gbp.csv",
            [
                make_candle(
                    datetime(
                        2026,
                        7,
                        14,
                        21,
                        0,
                        tzinfo=UTC,
                    ),
                    symbol="EUR_JPY",
                )
            ],
            expected_symbol="EUR_GBP",
            first_eligible_market_date=(
                START_DATE
            ),
        )


def test_corrupt_header_is_rejected(
    tmp_path,
):
    store_path = (
        tmp_path / "eur_gbp.csv"
    )

    store_path.write_text(
        "wrong,header\n1,2\n",
        encoding="utf-8",
    )

    with pytest.raises(
        CandleStoreError,
        match="header",
    ):
        read_candle_store(
            store_path,
            expected_symbol="EUR_GBP",
        )


def test_non_chronological_write_is_rejected(
    tmp_path,
):
    later = make_candle(
        datetime(
            2026,
            7,
            15,
            21,
            0,
            tzinfo=UTC,
        )
    )

    earlier = make_candle(
        datetime(
            2026,
            7,
            14,
            21,
            0,
            tzinfo=UTC,
        )
    )

    with pytest.raises(
        CandleStoreError,
        match="chronological",
    ):
        write_candle_store(
            tmp_path / "eur_gbp.csv",
            [later, earlier],
            expected_symbol="EUR_GBP",
        )


def test_tests_do_not_use_real_runtime_paths(
    tmp_path,
):
    persist_prospective_candles(
        tmp_path / "test.csv",
        [
            make_candle(
                datetime(
                    2026,
                    7,
                    14,
                    21,
                    0,
                    tzinfo=UTC,
                )
            )
        ],
        expected_symbol="EUR_GBP",
        first_eligible_market_date=(
            START_DATE
        ),
    )

    from pathlib import Path

    assert not Path(
        "paper_ledger/events.jsonl"
    ).exists()

    assert not Path(
        "paper_ledger/state.json"
    ).exists()

    assert not Path(
        "data/prospective_paper"
    ).exists()
