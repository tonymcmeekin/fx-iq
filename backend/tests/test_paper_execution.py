from datetime import (
    UTC,
    datetime,
)

import pytest

from app.market_data.models import Candle
from app.paper_trading.execution import (
    FROZEN_PIP_SIZE,
    PaperExecutionError,
    build_account_position,
    fill_pending_entry,
    next_complete_candle,
    stop_and_target,
    total_open_risk_amount,
)
from app.paper_trading.runtime_state import (
    add_pending_entry,
    build_pending_entry,
    empty_runtime_state,
)

POLICY_FINGERPRINT = (
    "test-fingerprint"
)

SIGNAL_TIMESTAMP = datetime(
    2026,
    7,
    14,
    21,
    0,
    tzinfo=UTC,
)

ENTRY_TIMESTAMP = datetime(
    2026,
    7,
    15,
    21,
    0,
    tzinfo=UTC,
)


def candle(
    timestamp,
    *,
    symbol="EUR_GBP",
    open_price=1.0,
):
    return Candle(
        symbol=symbol,
        timeframe="D",
        timestamp=timestamp,
        open=open_price,
        high=open_price * 1.01,
        low=open_price * 0.99,
        close=open_price,
        volume=1000,
    )


def pending(
    *,
    market="EUR_GBP",
    candidate_risk=0.25,
):
    return build_pending_entry(
        market=market,
        signal_candle_timestamp=(
            SIGNAL_TIMESTAMP
        ),
        direction="BUY",
        candidate_risk_percent=(
            candidate_risk
        ),
        shadow_risk_percent=0.5,
        directional_close_location=0.7,
        policy_fingerprint=(
            POLICY_FINGERPRINT
        ),
        created_session_date=(
            "2026-07-14"
        ),
    )


def state_with_pending(
    *,
    candidate_risk=0.25,
):
    return add_pending_entry(
        empty_runtime_state(),
        pending(
            candidate_risk=(
                candidate_risk
            )
        ),
    )


def test_next_complete_candle_is_strictly_after_signal():
    candles = [
        candle(
            SIGNAL_TIMESTAMP
        ),
        candle(
            ENTRY_TIMESTAMP
        ),
    ]

    result = next_complete_candle(
        candles,
        signal_candle_timestamp=(
            SIGNAL_TIMESTAMP
        ),
        expected_market="EUR_GBP",
    )

    assert result == candles[1]


def test_missing_next_candle_returns_none():
    result = next_complete_candle(
        [
            candle(
                SIGNAL_TIMESTAMP
            )
        ],
        signal_candle_timestamp=(
            SIGNAL_TIMESTAMP
        ),
        expected_market="EUR_GBP",
    )

    assert result is None


def test_stop_and_target_for_buy():
    stop, target = stop_and_target(
        direction="BUY",
        entry_price=1.0,
    )

    assert stop == pytest.approx(
        0.985
    )

    assert target == pytest.approx(
        1.03
    )


def test_stop_and_target_for_sell():
    stop, target = stop_and_target(
        direction="SELL",
        entry_price=1.0,
    )

    assert stop == pytest.approx(
        1.015
    )

    assert target == pytest.approx(
        0.97
    )


def test_candidate_position_uses_quarter_percent_risk():
    state = state_with_pending()

    position = build_account_position(
        state=state,
        pending_entry=(
            state["pending_entries"][
                "EUR_GBP"
            ]
        ),
        entry_candle=candle(
            ENTRY_TIMESTAMP
        ),
        account="candidate",
    )

    assert position[
        "configured_risk_percent"
    ] == 0.25

    assert position[
        "risk_amount"
    ] == pytest.approx(
        25.0
    )

    assert position[
        "position_size_units"
    ] == pytest.approx(
        1666.6666666667
    )


def test_shadow_position_uses_half_percent_risk():
    state = state_with_pending()

    position = build_account_position(
        state=state,
        pending_entry=(
            state["pending_entries"][
                "EUR_GBP"
            ]
        ),
        entry_candle=candle(
            ENTRY_TIMESTAMP
        ),
        account="shadow",
    )

    assert position[
        "configured_risk_percent"
    ] == 0.5

    assert position[
        "risk_amount"
    ] == pytest.approx(
        50.0
    )

    assert position[
        "position_size_units"
    ] == pytest.approx(
        3333.3333333333
    )


def test_frozen_pip_size_is_preserved():
    state = state_with_pending()

    position = build_account_position(
        state=state,
        pending_entry=(
            state["pending_entries"][
                "EUR_GBP"
            ]
        ),
        entry_candle=candle(
            ENTRY_TIMESTAMP
        ),
        account="candidate",
    )

    assert FROZEN_PIP_SIZE == (
        0.0001
    )

    assert position[
        "pip_size"
    ] == 0.0001

    assert position[
        "spread_pips"
    ] == 1.0

    assert position[
        "slippage_pips"
    ] == 0.5


def test_pending_entry_waits_without_next_candle():
    original = state_with_pending()

    updated, result = (
        fill_pending_entry(
            original,
            market="EUR_GBP",
            candles=[
                candle(
                    SIGNAL_TIMESTAMP
                )
            ],
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )
    )

    assert result[
        "status"
    ] == "WAITING_FOR_NEXT_CANDLE"

    assert updated == original

    assert "EUR_GBP" in (
        updated["pending_entries"]
    )


def test_fill_creates_candidate_and_shadow_pair():
    state = state_with_pending()

    updated, result = (
        fill_pending_entry(
            state,
            market="EUR_GBP",
            candles=[
                candle(
                    SIGNAL_TIMESTAMP
                ),
                candle(
                    ENTRY_TIMESTAMP
                ),
            ],
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )
    )

    assert result[
        "status"
    ] == "FILLED"

    assert result[
        "entry_timestamp"
    ] == "2026-07-15T21:00:00Z"

    assert result[
        "candidate_risk_amount"
    ] == pytest.approx(
        25.0
    )

    assert result[
        "shadow_risk_amount"
    ] == pytest.approx(
        50.0
    )

    assert result[
        "candidate_units"
    ] < result[
        "shadow_units"
    ]

    assert updated[
        "pending_entries"
    ] == {}

    pair = updated[
        "open_positions"
    ]["EUR_GBP"]

    assert pair[
        "candidate"
    ]["entry_price"] == pair[
        "shadow"
    ]["entry_price"]

    assert pair[
        "broker_orders_submitted"
    ] == 0


def test_candidate_and_shadow_sequence_is_identical():
    state = state_with_pending(
        candidate_risk=0.5
    )

    updated, result = (
        fill_pending_entry(
            state,
            market="EUR_GBP",
            candles=[
                candle(
                    SIGNAL_TIMESTAMP
                ),
                candle(
                    ENTRY_TIMESTAMP,
                    open_price=1.2,
                ),
            ],
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )
    )

    pair = updated[
        "open_positions"
    ]["EUR_GBP"]

    assert pair[
        "candidate"
    ]["entry_timestamp"] == pair[
        "shadow"
    ]["entry_timestamp"]

    assert pair[
        "candidate"
    ]["entry_price"] == pair[
        "shadow"
    ]["entry_price"]

    assert pair[
        "candidate"
    ]["direction"] == pair[
        "shadow"
    ]["direction"]

    assert result[
        "candidate_units"
    ] == pytest.approx(
        result[
            "shadow_units"
        ]
    )


def test_policy_fingerprint_mismatch_is_rejected():
    state = state_with_pending()

    with pytest.raises(
        PaperExecutionError,
        match="fingerprint mismatch",
    ):
        fill_pending_entry(
            state,
            market="EUR_GBP",
            candles=[
                candle(
                    SIGNAL_TIMESTAMP
                ),
                candle(
                    ENTRY_TIMESTAMP
                ),
            ],
            policy_fingerprint=(
                "wrong-fingerprint"
            ),
        )


def test_wrong_market_candle_is_rejected():
    state = state_with_pending()

    with pytest.raises(
        PaperExecutionError,
        match="market",
    ):
        fill_pending_entry(
            state,
            market="EUR_GBP",
            candles=[
                candle(
                    ENTRY_TIMESTAMP,
                    symbol="EUR_JPY",
                )
            ],
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )


def test_existing_open_risk_consumes_capacity():
    state = state_with_pending()

    state[
        "open_positions"
    ]["AUD_CAD"] = {
        "market": "AUD_CAD",
        "candidate": {
            "risk_amount": 40.0,
            "notional_value": 1000.0,
        },
        "shadow": {
            "risk_amount": 50.0,
            "notional_value": 1000.0,
        },
    }

    pending_entry = state[
        "pending_entries"
    ]["EUR_GBP"]

    candidate = build_account_position(
        state=state,
        pending_entry=pending_entry,
        entry_candle=candle(
            ENTRY_TIMESTAMP
        ),
        account="candidate",
    )

    assert candidate[
        "risk_amount"
    ] == pytest.approx(
        10.0
    )

    with pytest.raises(
        PaperExecutionError,
        match="shadow portfolio risk capacity",
    ):
        build_account_position(
            state=state,
            pending_entry=pending_entry,
            entry_candle=candle(
                ENTRY_TIMESTAMP
            ),
            account="shadow",
        )


def test_total_open_risk_reads_position_pairs():
    state = empty_runtime_state()

    state[
        "open_positions"
    ]["EUR_GBP"] = {
        "market": "EUR_GBP",
        "candidate": {
            "risk_amount": 20.0,
            "notional_value": 1000.0,
        },
        "shadow": {
            "risk_amount": 40.0,
            "notional_value": 2000.0,
        },
    }

    assert total_open_risk_amount(
        state,
        account="candidate",
    ) == 20.0

    assert total_open_risk_amount(
        state,
        account="shadow",
    ) == 40.0


def test_no_pending_entry_is_noop():
    state = empty_runtime_state()

    updated, result = (
        fill_pending_entry(
            state,
            market="EUR_GBP",
            candles=[],
            policy_fingerprint=(
                POLICY_FINGERPRINT
            ),
        )
    )

    assert updated == state

    assert result == {
        "status": "NO_PENDING_ENTRY",
        "market": "EUR_GBP",
    }


def test_fill_does_not_mutate_input_state():
    state = state_with_pending()

    original_pending = dict(
        state["pending_entries"]
    )

    updated, _ = fill_pending_entry(
        state,
        market="EUR_GBP",
        candles=[
            candle(
                SIGNAL_TIMESTAMP
            ),
            candle(
                ENTRY_TIMESTAMP
            ),
        ],
        policy_fingerprint=(
            POLICY_FINGERPRINT
        ),
    )

    assert state[
        "pending_entries"
    ] == original_pending

    assert state[
        "open_positions"
    ] == {}

    assert updated != state


def test_execution_does_not_modify_real_runtime_files(
    tmp_path,
):
    from pathlib import Path

    runtime_paths = (
        Path("paper_ledger/events.jsonl"),
        Path("paper_ledger/state.json"),
        Path("data/prospective_paper"),
    )

    before = {
        path: (
            path.exists(),
            path.read_bytes()
            if path.is_file()
            else None,
        )
        for path in runtime_paths
    }

    state = state_with_pending()

    fill_pending_entry(
        state,
        market="EUR_GBP",
        candles=[
            candle(
                SIGNAL_TIMESTAMP
            ),
            candle(
                ENTRY_TIMESTAMP
            ),
        ],
        policy_fingerprint=(
            POLICY_FINGERPRINT
        ),
    )

    after = {
        path: (
            path.exists(),
            path.read_bytes()
            if path.is_file()
            else None,
        )
        for path in runtime_paths
    }

    assert after == before
