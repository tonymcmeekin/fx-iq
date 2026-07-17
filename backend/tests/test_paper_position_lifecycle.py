from datetime import (
    UTC,
    datetime,
)

import pytest

from app.market_data.models import Candle
from app.paper_trading.execution import (
    fill_pending_entry,
)
from app.paper_trading.position_lifecycle import (
    PaperExecutionError,
    determine_exit,
    evaluate_open_position,
    unrealized_pnl,
)
from app.paper_trading.runtime_state import (
    add_pending_entry,
    build_pending_entry,
    empty_runtime_state,
)

POLICY_FINGERPRINT = (
    "test-fingerprint"
)

SIGNAL_TIME = datetime(
    2026,
    7,
    14,
    21,
    0,
    tzinfo=UTC,
)

ENTRY_TIME = datetime(
    2026,
    7,
    15,
    21,
    0,
    tzinfo=UTC,
)

NEXT_TIME = datetime(
    2026,
    7,
    16,
    21,
    0,
    tzinfo=UTC,
)


def candle(
    timestamp,
    *,
    open_price=1.0,
    high=1.01,
    low=0.99,
    close=1.0,
):
    return Candle(
        symbol="EUR_GBP",
        timeframe="D",
        timestamp=timestamp,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1000,
    )


def open_state(
    *,
    candidate_risk=0.25,
):
    state = empty_runtime_state()

    pending = build_pending_entry(
        market="EUR_GBP",
        signal_candle_timestamp=(
            SIGNAL_TIME
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

    state = add_pending_entry(
        state,
        pending,
    )

    state, result = (
        fill_pending_entry(
            state,
            market="EUR_GBP",
            candles=[
                candle(
                    SIGNAL_TIME
                ),
                candle(
                    ENTRY_TIME
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

    return state


def test_buy_stop_is_detected():
    state = open_state()

    position = state[
        "open_positions"
    ]["EUR_GBP"]["candidate"]

    result = determine_exit(
        position,
        candle(
            NEXT_TIME,
            high=1.01,
            low=0.98,
            close=0.99,
        ),
    )

    assert result[
        "exit_price"
    ] == pytest.approx(
        0.985
    )

    assert result[
        "exit_reason"
    ] == "Stop-loss hit."


def test_buy_target_is_detected():
    state = open_state()

    position = state[
        "open_positions"
    ]["EUR_GBP"]["candidate"]

    result = determine_exit(
        position,
        candle(
            NEXT_TIME,
            high=1.04,
            low=0.99,
            close=1.03,
        ),
    )

    assert result[
        "exit_price"
    ] == pytest.approx(
        1.03
    )

    assert result[
        "exit_reason"
    ] == "Take-profit hit."


def test_stop_is_used_when_both_levels_touch():
    state = open_state()

    position = state[
        "open_positions"
    ]["EUR_GBP"]["candidate"]

    result = determine_exit(
        position,
        candle(
            NEXT_TIME,
            high=1.04,
            low=0.98,
            close=1.0,
        ),
    )

    assert result[
        "exit_price"
    ] == pytest.approx(
        0.985
    )

    assert result[
        "stop_hit"
    ] is True

    assert result[
        "target_hit"
    ] is True

    assert "both stop-loss" in (
        result["exit_reason"]
    )


def test_unrealized_buy_pnl():
    state = open_state()

    candidate = state[
        "open_positions"
    ]["EUR_GBP"]["candidate"]

    result = unrealized_pnl(
        candidate,
        current_price=1.01,
    )

    assert result == pytest.approx(
        16.6666666667
    )


def test_open_position_is_marked_without_balance_change():
    state = open_state()

    updated, result = (
        evaluate_open_position(
            state,
            market="EUR_GBP",
            candle=candle(
                NEXT_TIME,
                high=1.01,
                low=0.99,
                close=1.005,
            ),
        )
    )

    assert result[
        "status"
    ] == "OPEN"

    assert result[
        "candidate_unrealized_pnl"
    ] > 0

    assert result[
        "shadow_unrealized_pnl"
    ] > result[
        "candidate_unrealized_pnl"
    ]

    assert updated == state

    assert updated[
        "candidate_balance"
    ] == 10000.0

    assert updated[
        "shadow_balance"
    ] == 10000.0


def test_candidate_and_shadow_close_on_same_path():
    state = open_state()

    updated, result = (
        evaluate_open_position(
            state,
            market="EUR_GBP",
            candle=candle(
                NEXT_TIME,
                high=1.04,
                low=0.99,
                close=1.03,
            ),
        )
    )

    assert result[
        "status"
    ] == "CLOSED"

    assert result[
        "exit_price"
    ] == pytest.approx(
        1.03
    )

    assert result[
        "candidate_trade"
    ]["exit_timestamp"] == (
        result[
            "shadow_trade"
        ]["exit_timestamp"]
    )

    assert result[
        "candidate_trade"
    ]["exit_price"] == (
        result[
            "shadow_trade"
        ]["exit_price"]
    )

    assert updated[
        "open_positions"
    ] == {}


def test_candidate_profit_is_smaller_when_risk_reduced():
    state = open_state(
        candidate_risk=0.25
    )

    updated, result = (
        evaluate_open_position(
            state,
            market="EUR_GBP",
            candle=candle(
                NEXT_TIME,
                high=1.04,
                low=0.99,
                close=1.03,
            ),
        )
    )

    assert result[
        "candidate_net_pnl"
    ] < result[
        "shadow_net_pnl"
    ]

    assert updated[
        "candidate_balance"
    ] < updated[
        "shadow_balance"
    ]

    assert updated[
        "candidate_balance"
    ] > 10000.0


def test_equal_risk_produces_equal_results():
    state = open_state(
        candidate_risk=0.5
    )

    updated, result = (
        evaluate_open_position(
            state,
            market="EUR_GBP",
            candle=candle(
                NEXT_TIME,
                high=1.04,
                low=0.99,
                close=1.03,
            ),
        )
    )

    assert result[
        "candidate_net_pnl"
    ] == pytest.approx(
        result[
            "shadow_net_pnl"
        ]
    )

    assert updated[
        "candidate_balance"
    ] == pytest.approx(
        updated[
            "shadow_balance"
        ]
    )


def test_stop_loss_reduces_balances():
    state = open_state()

    updated, result = (
        evaluate_open_position(
            state,
            market="EUR_GBP",
            candle=candle(
                NEXT_TIME,
                high=1.01,
                low=0.98,
                close=0.99,
            ),
        )
    )

    assert result[
        "exit_reason"
    ] == "Stop-loss hit."

    assert updated[
        "candidate_balance"
    ] < 10000.0

    assert updated[
        "shadow_balance"
    ] < 10000.0


def test_trading_cost_is_applied_once_on_closure():
    state = open_state()

    updated, result = (
        evaluate_open_position(
            state,
            market="EUR_GBP",
            candle=candle(
                NEXT_TIME,
                high=1.04,
                low=0.99,
                close=1.03,
            ),
        )
    )

    candidate = result[
        "candidate_trade"
    ]

    assert candidate[
        "gross_pnl"
    ] > candidate[
        "net_pnl"
    ]

    assert candidate[
        "trading_cost"
    ] > 0

    assert updated[
        "candidate_balance"
    ] == pytest.approx(
        10000.0
        + candidate[
            "net_pnl"
        ]
    )


def test_peak_equity_updates_after_profit():
    state = open_state()

    updated, _ = (
        evaluate_open_position(
            state,
            market="EUR_GBP",
            candle=candle(
                NEXT_TIME,
                high=1.04,
                low=0.99,
                close=1.03,
            ),
        )
    )

    assert updated[
        "candidate_peak_equity"
    ] == updated[
        "candidate_balance"
    ]

    assert updated[
        "shadow_peak_equity"
    ] == updated[
        "shadow_balance"
    ]


def test_peak_equity_does_not_fall_after_loss():
    state = open_state()

    updated, _ = (
        evaluate_open_position(
            state,
            market="EUR_GBP",
            candle=candle(
                NEXT_TIME,
                high=1.01,
                low=0.98,
                close=0.99,
            ),
        )
    )

    assert updated[
        "candidate_peak_equity"
    ] == 10000.0

    assert updated[
        "shadow_peak_equity"
    ] == 10000.0


def test_entry_candle_can_close_position():
    state = open_state()

    updated, result = (
        evaluate_open_position(
            state,
            market="EUR_GBP",
            candle=candle(
                ENTRY_TIME,
                high=1.04,
                low=0.99,
                close=1.03,
            ),
        )
    )

    assert result[
        "status"
    ] == "CLOSED"

    assert result[
        "exit_timestamp"
    ] == "2026-07-15T21:00:00Z"

    assert updated[
        "open_positions"
    ] == {}


def test_candle_before_entry_is_rejected():
    state = open_state()

    with pytest.raises(
        PaperExecutionError,
        match="predates position entry",
    ):
        evaluate_open_position(
            state,
            market="EUR_GBP",
            candle=candle(
                SIGNAL_TIME
            ),
        )


def test_wrong_market_candle_is_rejected():
    state = open_state()

    wrong = candle(
        NEXT_TIME
    ).model_copy(
        update={
            "symbol": "EUR_JPY",
        }
    )

    with pytest.raises(
        PaperExecutionError,
        match="market",
    ):
        evaluate_open_position(
            state,
            market="EUR_GBP",
            candle=wrong,
        )


def test_no_open_position_is_noop():
    state = empty_runtime_state()

    updated, result = (
        evaluate_open_position(
            state,
            market="EUR_GBP",
            candle=candle(
                NEXT_TIME
            ),
        )
    )

    assert updated == state

    assert result == {
        "status": "NO_OPEN_POSITION",
        "market": "EUR_GBP",
    }


def test_input_state_is_not_mutated():
    state = open_state()

    original = state[
        "open_positions"
    ].copy()

    updated, _ = (
        evaluate_open_position(
            state,
            market="EUR_GBP",
            candle=candle(
                NEXT_TIME,
                high=1.04,
                low=0.99,
                close=1.03,
            ),
        )
    )

    assert state[
        "open_positions"
    ] == original

    assert "EUR_GBP" in (
        state["open_positions"]
    )

    assert updated[
        "open_positions"
    ] == {}


def test_lifecycle_does_not_modify_real_runtime_files():
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

    state = open_state()

    evaluate_open_position(
        state,
        market="EUR_GBP",
        candle=candle(
            NEXT_TIME,
            high=1.04,
            low=0.99,
            close=1.03,
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
