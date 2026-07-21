from datetime import (
    UTC,
    date,
    datetime,
    timedelta,
)

import pytest

from app.intelligence import (
    ObservationStoreError,
    append_observation,
    build_trade_observation,
    read_observations,
)
from app.market_data.models import Candle
from app.signals.models import TradeSignal


def make_observation():
    start = datetime(
        2026,
        1,
        1,
        tzinfo=UTC,
    )

    candles = []

    for index in range(80):
        close = 1.10 + index * 0.001

        candles.append(
            Candle(
                symbol="EUR_USD",
                timeframe="D",
                timestamp=(start + timedelta(days=index)),
                open=close,
                high=close + 0.0005,
                low=close - 0.0005,
                close=close,
                volume=1000,
            )
        )

    signal = TradeSignal(
        symbol="EUR_USD",
        direction="BUY",
        confidence=0.8,
        strategy_name="atr_breakout",
        reason="Test signal.",
    )

    return build_trade_observation(
        session_date=date(
            2026,
            7,
            21,
        ),
        recorded_at_utc=datetime(
            2026,
            7,
            21,
            20,
            0,
            tzinfo=UTC,
        ),
        candles=candles,
        signal=signal,
        trade_accepted=True,
        decision_reason=("Accepted by existing rules."),
    )


def test_append_and_read_observation(
    tmp_path,
):
    store_path = tmp_path / "observations.jsonl"
    observation = make_observation()

    appended = append_observation(
        store_path,
        observation,
    )
    stored = read_observations(store_path)

    assert appended == observation
    assert stored == [observation]


def test_store_is_append_only(
    tmp_path,
):
    store_path = tmp_path / "observations.jsonl"

    append_observation(
        store_path,
        make_observation(),
    )

    first_bytes = store_path.read_bytes()

    second = make_observation().model_copy(
        update={
            "observation_id": "f" * 64,
        }
    )

    append_observation(
        store_path,
        second,
    )

    final_bytes = store_path.read_bytes()

    assert final_bytes.startswith(first_bytes)
    assert len(read_observations(store_path)) == 2


def test_duplicate_observation_is_rejected(
    tmp_path,
):
    store_path = tmp_path / "observations.jsonl"
    observation = make_observation()

    append_observation(
        store_path,
        observation,
    )

    with pytest.raises(
        ObservationStoreError,
        match="Duplicate observation ID",
    ):
        append_observation(
            store_path,
            observation,
        )


def test_invalid_json_is_rejected(
    tmp_path,
):
    store_path = tmp_path / "observations.jsonl"
    store_path.write_text(
        "not-json\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ObservationStoreError,
        match="Invalid observation",
    ):
        read_observations(store_path)


def test_store_permissions_are_private(
    tmp_path,
):
    store_path = tmp_path / "observations.jsonl"

    append_observation(
        store_path,
        make_observation(),
    )

    assert (store_path.stat().st_mode & 0o777) == 0o600
