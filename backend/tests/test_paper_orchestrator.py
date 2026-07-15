from datetime import (
    UTC,
    date,
    datetime,
    timedelta,
)

import pytest

from app.market_data.models import Candle
from app.paper_trading.ledger import (
    verify_ledger,
)
from app.paper_trading.orchestrator import (
    run_controlled_daily_session,
)
from app.paper_trading.runtime_state import (
    read_runtime_state,
)


SESSION_DATE = date(
    2026,
    7,
    16,
)

SESSION_TIME = datetime(
    2026,
    7,
    16,
    23,
    15,
    tzinfo=UTC,
)

POLICY_FINGERPRINT = (
    "offline-test-fingerprint"
)


def make_protocol(
    markets=None,
):
    return {
        "mode": "SIMULATION_ONLY",
        "live_order_submission_permitted": (
            False
        ),
        "markets": (
            markets
            if markets is not None
            else ["EUR_GBP"]
        ),
        "prospective_period": {
            "first_eligible_market_date": (
                "2026-07-14"
            ),
        },
    }


def make_candles(
    symbol: str,
    *,
    breakout: bool,
) -> list[Candle]:
    start = datetime(
        2026,
        6,
        23,
        21,
        0,
        tzinfo=UTC,
    )

    candles = []

    for index in range(21):
        candles.append(
            Candle(
                symbol=symbol,
                timeframe="D",
                timestamp=(
                    start
                    + timedelta(
                        days=index
                    )
                ),
                open=1.0000,
                high=1.0100,
                low=0.9900,
                close=1.0000,
                volume=1000,
            )
        )

    if breakout:
        candles.append(
            Candle(
                symbol=symbol,
                timeframe="D",
                timestamp=(
                    start
                    + timedelta(days=21)
                ),
                open=1.0100,
                high=1.2000,
                low=1.0000,
                close=1.1900,
                volume=2000,
            )
        )
    else:
        candles.append(
            Candle(
                symbol=symbol,
                timeframe="D",
                timestamp=(
                    start
                    + timedelta(days=21)
                ),
                open=1.0000,
                high=1.0100,
                low=0.9900,
                close=1.0000,
                volume=1000,
            )
        )

    return candles


def test_orchestrator_collects_frozen_markets_in_order(
    tmp_path,
):
    calls = []

    def fake_collector(**kwargs):
        calls.append(kwargs)

        return make_candles(
            kwargs["instrument"],
            breakout=False,
        )

    result = run_controlled_daily_session(
        api_token="test-token",
        session_date=SESSION_DATE,
        ledger_path=(
            tmp_path / "events.jsonl"
        ),
        state_path=(
            tmp_path / "state.json"
        ),
        protocol=make_protocol(
            [
                "EUR_GBP",
                "EUR_JPY",
            ]
        ),
        collector=fake_collector,
        policy_verifier=(
            lambda: POLICY_FINGERPRINT
        ),
        session_time_utc=SESSION_TIME,
        software_commit="test-commit",
    )

    assert result["status"] == (
        "COMPLETED"
    )

    assert [
        call["instrument"]
        for call in calls
    ] == [
        "EUR_GBP",
        "EUR_JPY",
    ]

    for call in calls:
        assert call[
            "environment"
        ] == "practice"

        assert call[
            "count"
        ] == 100

        assert call[
            "api_token"
        ] == "test-token"


def test_actionable_signal_becomes_pending_entry(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    state_path = (
        tmp_path / "state.json"
    )

    result = run_controlled_daily_session(
        api_token="test-token",
        session_date=SESSION_DATE,
        ledger_path=ledger_path,
        state_path=state_path,
        protocol=make_protocol(),
        collector=(
            lambda **kwargs: make_candles(
                kwargs["instrument"],
                breakout=True,
            )
        ),
        policy_verifier=(
            lambda: POLICY_FINGERPRINT
        ),
        session_time_utc=SESSION_TIME,
        software_commit="test-commit",
    )

    assert result[
        "pending_entries_total"
    ] == 1

    assert result[
        "open_positions_total"
    ] == 0

    assert result[
        "broker_orders_sent"
    ] == 0

    state = read_runtime_state(
        state_path
    )

    pending = state[
        "pending_entries"
    ]["EUR_GBP"]

    assert pending[
        "direction"
    ] == "BUY"

    assert pending[
        "candidate_risk_percent"
    ] == 0.5

    assert pending[
        "shadow_risk_percent"
    ] == 0.5

    assert pending[
        "policy_fingerprint"
    ] == POLICY_FINGERPRINT


def test_hold_signal_does_not_create_pending_entry(
    tmp_path,
):
    state_path = (
        tmp_path / "state.json"
    )

    result = run_controlled_daily_session(
        api_token="test-token",
        session_date=SESSION_DATE,
        ledger_path=(
            tmp_path / "events.jsonl"
        ),
        state_path=state_path,
        protocol=make_protocol(),
        collector=(
            lambda **kwargs: make_candles(
                kwargs["instrument"],
                breakout=False,
            )
        ),
        policy_verifier=(
            lambda: POLICY_FINGERPRINT
        ),
        session_time_utc=SESSION_TIME,
    )

    assert result[
        "pending_entries_total"
    ] == 0

    assert read_runtime_state(
        state_path
    )["pending_entries"] == {}


def test_completed_session_is_idempotent(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    state_path = (
        tmp_path / "state.json"
    )

    arguments = {
        "api_token": "test-token",
        "session_date": SESSION_DATE,
        "ledger_path": ledger_path,
        "state_path": state_path,
        "protocol": make_protocol(),
        "collector": (
            lambda **kwargs: make_candles(
                kwargs["instrument"],
                breakout=True,
            )
        ),
        "policy_verifier": (
            lambda: POLICY_FINGERPRINT
        ),
        "session_time_utc": (
            SESSION_TIME
        ),
        "software_commit": (
            "test-commit"
        ),
    }

    first = (
        run_controlled_daily_session(
            **arguments
        )
    )

    events_after_first = (
        verify_ledger(
            ledger_path
        )
    )

    state_after_first = (
        read_runtime_state(
            state_path
        )
    )

    second = (
        run_controlled_daily_session(
            **arguments
        )
    )

    assert first["status"] == (
        "COMPLETED"
    )

    assert second["status"] == (
        "ALREADY_COMPLETED"
    )

    assert second[
        "runtime_state_updated"
    ] is False

    assert verify_ledger(
        ledger_path
    ) == events_after_first

    assert read_runtime_state(
        state_path
    ) == state_after_first


def test_live_environment_is_rejected_before_collection(
    tmp_path,
):
    collector_called = False

    def fake_collector(**kwargs):
        nonlocal collector_called
        collector_called = True
        return []

    with pytest.raises(
        RuntimeError,
        match="practice environment",
    ):
        run_controlled_daily_session(
            api_token="test-token",
            session_date=SESSION_DATE,
            ledger_path=(
                tmp_path
                / "events.jsonl"
            ),
            state_path=(
                tmp_path
                / "state.json"
            ),
            protocol=make_protocol(),
            environment="live",
            collector=fake_collector,
            policy_verifier=(
                lambda: POLICY_FINGERPRINT
            ),
            session_time_utc=(
                SESSION_TIME
            ),
        )

    assert collector_called is False


def test_token_is_not_written_to_runtime_files(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    state_path = (
        tmp_path / "state.json"
    )

    token = (
        "secret-oanda-test-token"
    )

    run_controlled_daily_session(
        api_token=token,
        session_date=SESSION_DATE,
        ledger_path=ledger_path,
        state_path=state_path,
        protocol=make_protocol(),
        collector=(
            lambda **kwargs: make_candles(
                kwargs["instrument"],
                breakout=False,
            )
        ),
        policy_verifier=(
            lambda: POLICY_FINGERPRINT
        ),
        session_time_utc=SESSION_TIME,
    )

    assert token not in (
        ledger_path.read_text(
            encoding="utf-8"
        )
    )

    assert token not in (
        state_path.read_text(
            encoding="utf-8"
        )
    )


def test_missing_token_is_rejected():
    with pytest.raises(
        ValueError,
        match="API token",
    ):
        run_controlled_daily_session(
            api_token="",
            session_date=SESSION_DATE,
            protocol=make_protocol(),
            collector=lambda **_: [],
            policy_verifier=(
                lambda: POLICY_FINGERPRINT
            ),
            session_time_utc=(
                SESSION_TIME
            ),
        )
