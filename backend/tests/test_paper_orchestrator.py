from datetime import (
    UTC,
    date,
    datetime,
    timedelta,
)

import pytest

from app.intelligence.observation_store import (
    read_observations,
)
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
        journal_path=(
            tmp_path / "transition.json"
        ),
        candle_store_directory=(
            tmp_path / "candles"
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


def test_orchestrator_records_passive_observations(
    tmp_path,
):
    observation_path = (
        tmp_path / "intelligence_observations.jsonl"
    )

    observation_candles = [
        Candle(
            symbol="EUR_GBP",
            timeframe="D",
            timestamp=(
                datetime(
                    2026,
                    5,
                    16,
                    21,
                    0,
                    tzinfo=UTC,
                )
                + timedelta(days=index)
            ),
            open=1.0000,
            high=1.0100,
            low=0.9900,
            close=1.0000,
            volume=1000,
        )
        for index in range(60)
    ]

    result = run_controlled_daily_session(
        api_token="test-token",
        session_date=SESSION_DATE,
        ledger_path=(tmp_path / "events.jsonl"),
        state_path=(tmp_path / "state.json"),
        journal_path=(tmp_path / "transition.json"),
        candle_store_directory=(tmp_path / "candles"),
        observation_store_path=observation_path,
        protocol=make_protocol(),
        collector=(
            lambda **kwargs: observation_candles
        ),
        policy_verifier=(lambda: POLICY_FINGERPRINT),
        session_time_utc=SESSION_TIME,
        software_commit="test-commit",
    )

    observations = read_observations(
        observation_path
    )

    assert result["observations_recorded"] == 1
    assert len(observations) == 1
    assert observations[0].recorded_at_utc == SESSION_TIME
    assert observations[0].recorded_at_utc.tzinfo is not None


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
        journal_path=(
            tmp_path / "transition.json"
        ),
        candle_store_directory=(
            tmp_path / "candles"
        ),
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


def test_repeated_signal_advances_existing_pending_entry(
    tmp_path,
):
    ledger_path = tmp_path / "events.jsonl"
    state_path = tmp_path / "state.json"
    journal_path = tmp_path / "transition.json"
    candle_directory = tmp_path / "candles"

    first_candles = make_candles(
        "EUR_GBP",
        breakout=True,
    )

    run_controlled_daily_session(
        api_token="test-token",
        session_date=SESSION_DATE,
        ledger_path=ledger_path,
        state_path=state_path,
        journal_path=journal_path,
        candle_store_directory=candle_directory,
        observation_store_path=None,
        protocol=make_protocol(),
        collector=(lambda **_: first_candles),
        policy_verifier=(lambda: POLICY_FINGERPRINT),
        session_time_utc=SESSION_TIME,
        software_commit="test-commit",
    )

    next_candle = Candle(
        symbol="EUR_GBP",
        timeframe="D",
        timestamp=(
            first_candles[-1].timestamp
            + timedelta(days=1)
        ),
        open=1.1900,
        high=1.2100,
        low=1.1800,
        close=1.2000,
        volume=2000,
    )

    result = run_controlled_daily_session(
        api_token="test-token",
        session_date=(
            SESSION_DATE + timedelta(days=1)
        ),
        ledger_path=ledger_path,
        state_path=state_path,
        journal_path=journal_path,
        candle_store_directory=candle_directory,
        observation_store_path=None,
        protocol=make_protocol(),
        collector=(
            lambda **_: [
                *first_candles,
                next_candle,
            ]
        ),
        policy_verifier=(lambda: POLICY_FINGERPRINT),
        session_time_utc=(
            SESSION_TIME + timedelta(days=1)
        ),
        software_commit="test-commit",
    )

    assert result["status"] == "COMPLETED"
    assert result["positions_opened"] == 1
    assert result["broker_orders_sent"] == 0


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
        journal_path=(
            tmp_path / "transition.json"
        ),
        candle_store_directory=(
            tmp_path / "candles"
        ),
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
        "journal_path": (
            tmp_path / "transition.json"
        ),
        "candle_store_directory": (
            tmp_path / "candles"
        ),
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
            journal_path=(
                tmp_path
                / "transition.json"
            ),
            candle_store_directory=(
                tmp_path
                / "candles"
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
        journal_path=(
            tmp_path / "transition.json"
        ),
        candle_store_directory=(
            tmp_path / "candles"
        ),
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


def test_completion_is_last_after_state_commit(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    state_path = (
        tmp_path / "state.json"
    )

    journal_path = (
        tmp_path / "transition.json"
    )

    result = run_controlled_daily_session(
        api_token="test-token",
        session_date=SESSION_DATE,
        ledger_path=ledger_path,
        state_path=state_path,
        journal_path=journal_path,
        candle_store_directory=(
            tmp_path / "candles"
        ),
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

    assert result["status"] == (
        "COMPLETED"
    )

    events = verify_ledger(
        ledger_path
    )

    assert events[-1][
        "event_type"
    ] == "SESSION_COMPLETED"

    assert state_path.exists()
    assert not journal_path.exists()

    state = read_runtime_state(
        state_path
    )

    assert state[
        "last_completed_session_date"
    ] == SESSION_DATE.isoformat()

    assert state[
        "broker_orders_sent"
    ] == 0


def test_completed_session_skips_collection(
    tmp_path,
):
    calls = 0

    def collector(**kwargs):
        nonlocal calls
        calls += 1

        return make_candles(
            kwargs["instrument"],
            breakout=False,
        )

    arguments = {
        "api_token": "test-token",
        "session_date": SESSION_DATE,
        "ledger_path": (
            tmp_path / "events.jsonl"
        ),
        "state_path": (
            tmp_path / "state.json"
        ),
        "journal_path": (
            tmp_path / "transition.json"
        ),
        "candle_store_directory": (
            tmp_path / "candles"
        ),
        "protocol": make_protocol(),
        "collector": collector,
        "policy_verifier": (
            lambda: POLICY_FINGERPRINT
        ),
        "session_time_utc": (
            SESSION_TIME
        ),
    }

    first = run_controlled_daily_session(
        **arguments
    )

    second = run_controlled_daily_session(
        **arguments
    )

    assert first["status"] == (
        "COMPLETED"
    )

    assert second["status"] == (
        "ALREADY_COMPLETED"
    )

    assert calls == 1


def test_passing_preflight_allows_collection(
    tmp_path,
):
    preflight_calls = []
    collector_called = False

    class PassingReport:
        passed = True

    def passing_preflight(**kwargs):
        preflight_calls.append(kwargs)
        return PassingReport()

    def fake_collector(**kwargs):
        nonlocal collector_called
        collector_called = True

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
        journal_path=(
            tmp_path / "transition.json"
        ),
        candle_store_directory=(
            tmp_path / "candles"
        ),
        protocol=make_protocol(),
        collector=fake_collector,
        policy_verifier=(
            lambda: POLICY_FINGERPRINT
        ),
        preflight_runner=passing_preflight,
        preflight_context={
            "account_id": "practice-account",
        },
        session_time_utc=SESSION_TIME,
        software_commit="test-commit",
    )

    assert result["status"] == "COMPLETED"
    assert collector_called is True
    assert preflight_calls == [
        {
            "account_id": "practice-account",
        }
    ]


def test_failing_preflight_aborts_before_collection(
    tmp_path,
):
    collector_called = False

    ledger_path = (
        tmp_path / "events.jsonl"
    )
    state_path = (
        tmp_path / "state.json"
    )
    journal_path = (
        tmp_path / "transition.json"
    )
    candle_directory = (
        tmp_path / "candles"
    )

    class FailingReport:
        passed = False

    def failing_preflight(**kwargs):
        assert kwargs == {
            "reason": "test-failure",
        }

        return FailingReport()

    def fake_collector(**kwargs):
        nonlocal collector_called
        collector_called = True

        return make_candles(
            kwargs["instrument"],
            breakout=False,
        )

    with pytest.raises(
        RuntimeError,
        match=(
            "Paper session aborted: "
            "preflight failed"
        ),
    ):
        run_controlled_daily_session(
            api_token="test-token",
            session_date=SESSION_DATE,
            ledger_path=ledger_path,
            state_path=state_path,
            journal_path=journal_path,
            candle_store_directory=(
                candle_directory
            ),
            protocol=make_protocol(),
            collector=fake_collector,
            policy_verifier=(
                lambda: POLICY_FINGERPRINT
            ),
            preflight_runner=(
                failing_preflight
            ),
            preflight_context={
                "reason": "test-failure",
            },
            session_time_utc=SESSION_TIME,
            software_commit="test-commit",
        )

    assert collector_called is False
    assert ledger_path.exists() is False
    assert journal_path.exists() is False
    assert candle_directory.exists() is False

    if state_path.exists():
        state = read_runtime_state(
            state_path
        )

        assert state["pending_entries"] == []
        assert state["open_positions"] == []
        assert state[
            "broker_orders_submitted"
        ] == 0
