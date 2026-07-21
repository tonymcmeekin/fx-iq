from datetime import (
    UTC,
    date,
    datetime,
    timedelta,
)

import pytest

import app.paper_trading.session as session_module
from app.intelligence.observation_store import ObservationStoreError
from app.market_data.models import Candle
from app.paper_trading.ledger import (
    verify_ledger,
)
from app.paper_trading.session import (
    deterministic_event_id,
    directional_close_location,
    run_daily_evaluation,
    session_is_completed,
    utc_isoformat,
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
    "test-fingerprint"
)


def make_protocol(
    markets=None,
):
    resolved_markets = (
        markets
        if markets is not None
        else ["EUR_GBP"]
    )

    return {
        "mode": "SIMULATION_ONLY",
        "live_order_submission_permitted": (
            False
        ),
        "markets": resolved_markets,
        "prospective_period": {
            "first_eligible_market_date": (
                "2026-07-14"
            ),
        },
    }


def make_candles(
    symbol="EUR_GBP",
    *,
    breakout=False,
    count=21,
):
    start = datetime(
        2026,
        6,
        23,
        21,
        0,
        tzinfo=UTC,
    )
    history_start = start - timedelta(
        days=max(count - 21, 0)
    )

    candles = []

    for index in range(count):
        candles.append(
            Candle(
                symbol=symbol,
                timeframe="D",
                timestamp=(
                    history_start
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

    candles_by_timestamp = {
        candle.timestamp: candle
        for candle in candles
    }

    return sorted(
        candles_by_timestamp.values(),
        key=lambda candle: candle.timestamp,
    )


def test_utc_isoformat_requires_timezone():
    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        utc_isoformat(
            datetime(
                2026,
                7,
                16,
                23,
                15,
            )
        )


def test_deterministic_event_id_is_stable():
    first = deterministic_event_id(
        SESSION_DATE,
        "SESSION_STARTED",
    )

    second = deterministic_event_id(
        SESSION_DATE,
        "SESSION_STARTED",
    )

    assert first == second

    assert first.startswith(
        "paper-"
    )


def test_directional_close_location_buy():
    candle = Candle(
        symbol="EUR_GBP",
        timeframe="D",
        timestamp=SESSION_TIME,
        open=1.05,
        high=1.10,
        low=1.00,
        close=1.08,
        volume=100,
    )

    result = (
        directional_close_location(
            candle,
            "BUY",
        )
    )

    assert result == pytest.approx(
        0.8
    )


def test_directional_close_location_sell():
    candle = Candle(
        symbol="EUR_GBP",
        timeframe="D",
        timestamp=SESSION_TIME,
        open=1.05,
        high=1.10,
        low=1.00,
        close=1.02,
        volume=100,
    )

    result = (
        directional_close_location(
            candle,
            "SELL",
        )
    )

    assert result == pytest.approx(
        0.8
    )


def test_hold_session_is_recorded(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    result = run_daily_evaluation(
        ledger_path=ledger_path,
        session_date=SESSION_DATE,
        market_candles={
            "EUR_GBP": make_candles(),
        },
        protocol=make_protocol(),
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

    assert [
        event["event_type"]
        for event in events
    ] == [
        "SESSION_STARTED",
        "MARKET_DATA_COLLECTED",
        "SIGNAL_EVALUATED",
        "SESSION_COMPLETED",
    ]

    signal_event = events[2]

    assert signal_event[
        "payload"
    ]["direction"] == "HOLD"


def test_actionable_signal_records_risk(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    result = run_daily_evaluation(
        ledger_path=ledger_path,
        session_date=SESSION_DATE,
        market_candles={
            "EUR_GBP": make_candles(
                breakout=True
            ),
        },
        protocol=make_protocol(),
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

    event_types = [
        event["event_type"]
        for event in events
    ]

    assert event_types == [
        "SESSION_STARTED",
        "MARKET_DATA_COLLECTED",
        "SIGNAL_EVALUATED",
        "RISK_DECIDED",
        "SESSION_COMPLETED",
    ]

    signal_event = events[2]

    assert signal_event[
        "payload"
    ]["direction"] == "BUY"

    risk_event = events[3]

    assert risk_event[
        "payload"
    ][
        "candidate_risk_percent"
    ] in {
        0.25,
        0.5,
    }

    assert risk_event[
        "payload"
    ][
        "shadow_risk_percent"
    ] == 0.5

    assert risk_event[
        "payload"
    ][
        "broker_order_submitted"
    ] is False


def test_completed_session_is_idempotent(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    arguments = {
        "ledger_path": ledger_path,
        "session_date": SESSION_DATE,
        "market_candles": {
            "EUR_GBP": make_candles(),
        },
        "protocol": make_protocol(),
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

    first = run_daily_evaluation(
        **arguments
    )

    first_events = verify_ledger(
        ledger_path
    )

    second = run_daily_evaluation(
        **arguments
    )

    second_events = verify_ledger(
        ledger_path
    )

    assert first["status"] == (
        "COMPLETED"
    )

    assert second["status"] == (
        "ALREADY_COMPLETED"
    )

    assert second_events == (
        first_events
    )


def test_market_order_must_match_protocol(
    tmp_path,
):
    with pytest.raises(
        ValueError,
        match="market order",
    ):
        run_daily_evaluation(
            ledger_path=(
                tmp_path
                / "events.jsonl"
            ),
            session_date=SESSION_DATE,
            market_candles={
                "EUR_JPY": (
                    make_candles(
                        symbol="EUR_JPY"
                    )
                ),
                "EUR_GBP": (
                    make_candles()
                ),
            },
            protocol=make_protocol(
                [
                    "EUR_GBP",
                    "EUR_JPY",
                ]
            ),
            policy_verifier=(
                lambda: (
                    POLICY_FINGERPRINT
                )
            ),
            session_time_utc=(
                SESSION_TIME
            ),
        )


def test_future_candle_logs_failure(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    candles = make_candles()

    candles[-1] = candles[
        -1
    ].model_copy(
        update={
            "timestamp": (
                SESSION_TIME
                + timedelta(days=1)
            )
        }
    )

    with pytest.raises(
        ValueError,
        match="Future candle",
    ):
        run_daily_evaluation(
            ledger_path=ledger_path,
            session_date=SESSION_DATE,
            market_candles={
                "EUR_GBP": candles,
            },
            protocol=make_protocol(),
            policy_verifier=(
                lambda: (
                    POLICY_FINGERPRINT
                )
            ),
            session_time_utc=(
                SESSION_TIME
            ),
        )

    events = verify_ledger(
        ledger_path
    )

    assert [
        event["event_type"]
        for event in events
    ] == [
        "SESSION_STARTED",
        "SESSION_FAILED",
    ]

    assert events[-1][
        "payload"
    ]["broker_orders_sent"] == 0


def test_no_runtime_paths_are_used(
    tmp_path,
):
    ledger_path = (
        tmp_path / "test-ledger.jsonl"
    )

    run_daily_evaluation(
        ledger_path=ledger_path,
        session_date=SESSION_DATE,
        market_candles={
            "EUR_GBP": make_candles(),
        },
        protocol=make_protocol(),
        policy_verifier=(
            lambda: POLICY_FINGERPRINT
        ),
        session_time_utc=SESSION_TIME,
    )

    assert ledger_path.exists()

    assert not (
        tmp_path / "paper_ledger"
    ).exists()


def test_evaluation_only_does_not_complete_session(
    tmp_path,
):
    ledger_path = (
        tmp_path / "events.jsonl"
    )

    result = run_daily_evaluation(
        ledger_path=ledger_path,
        session_date=SESSION_DATE,
        market_candles={
            "EUR_GBP": make_candles(),
        },
        protocol=make_protocol(),
        policy_verifier=(
            lambda: POLICY_FINGERPRINT
        ),
        session_time_utc=SESSION_TIME,
        software_commit="test-commit",
        append_completion_event=False,
    )

    assert result["status"] == (
        "EVALUATED"
    )

    assert result[
        "completion_event_appended"
    ] is False

    assert result[
        "completion_payload"
    ]["status"] == "SUCCESS"

    assert "SESSION_COMPLETED" not in [
        event["event_type"]
        for event in verify_ledger(
            ledger_path
        )
    ]

    assert session_is_completed(
        ledger_path,
        SESSION_DATE,
    ) is False


def test_observation_path_omitted_does_not_attempt_recording(
    tmp_path,
    monkeypatch,
):
    def fail_if_called(
        *_args,
        **_kwargs,
    ):
        raise AssertionError(
            "Observation storage must not be called "
            "when no path is supplied."
        )

    monkeypatch.setattr(
        session_module,
        "append_observation",
        fail_if_called,
    )

    result = run_daily_evaluation(
        ledger_path=(
            tmp_path / "events.jsonl"
        ),
        session_date=SESSION_DATE,
        market_candles={
            "EUR_GBP": make_candles(count=60),
        },
        protocol=make_protocol(),
        policy_verifier=(
            lambda: POLICY_FINGERPRINT
        ),
        session_time_utc=SESSION_TIME,
        software_commit="test-commit",
    )

    assert result["status"] == "COMPLETED"
    assert result["observations_attempted"] == 0
    assert result["observations_recorded"] == 0
    assert result["observation_duplicates"] == 0
    assert result["observation_failures"] == 0
    assert result["observation_errors"] == []


def test_successful_observation_is_recorded(
    tmp_path,
    monkeypatch,
):
    captured = []

    def capture_observation(
        store_path,
        observation,
    ):
        captured.append(
            (
                store_path,
                observation,
            )
        )

    monkeypatch.setattr(
        session_module,
        "append_observation",
        capture_observation,
    )

    observation_path = (
        tmp_path / "observations.jsonl"
    )

    result = run_daily_evaluation(
        ledger_path=(
            tmp_path / "events.jsonl"
        ),
        session_date=SESSION_DATE,
        market_candles={
            "EUR_GBP": make_candles(count=60),
        },
        protocol=make_protocol(),
        policy_verifier=(
            lambda: POLICY_FINGERPRINT
        ),
        session_time_utc=SESSION_TIME,
        software_commit="test-commit",
        observation_store_path=(
            observation_path
        ),
    )

    assert result["status"] == "COMPLETED"
    assert result["observations_attempted"] == 1
    assert result["observations_recorded"] == 1
    assert result["observation_duplicates"] == 0
    assert result["observation_failures"] == 0
    assert result["observation_errors"] == []

    assert len(captured) == 1

    captured_path, observation = captured[0]

    assert captured_path == observation_path
    assert observation.instrument == "EUR_GBP"


def test_duplicate_observation_is_recovery_outcome(
    tmp_path,
    monkeypatch,
):
    def raise_duplicate(
        _store_path,
        _observation,
    ):
        raise ObservationStoreError(
            "Duplicate observation ID: "
            "test-observation"
        )

    monkeypatch.setattr(
        session_module,
        "append_observation",
        raise_duplicate,
    )

    result = run_daily_evaluation(
        ledger_path=(
            tmp_path / "events.jsonl"
        ),
        session_date=SESSION_DATE,
        market_candles={
            "EUR_GBP": make_candles(count=60),
        },
        protocol=make_protocol(),
        policy_verifier=(
            lambda: POLICY_FINGERPRINT
        ),
        session_time_utc=SESSION_TIME,
        software_commit="test-commit",
        observation_store_path=(
            tmp_path / "observations.jsonl"
        ),
    )

    assert result["status"] == "COMPLETED"
    assert result["observations_attempted"] == 1
    assert result["observations_recorded"] == 0
    assert result["observation_duplicates"] == 1
    assert result["observation_failures"] == 0
    assert result["observation_errors"] == []


def test_observation_failure_does_not_fail_session(
    tmp_path,
    monkeypatch,
):
    def raise_write_failure(
        _store_path,
        _observation,
    ):
        raise OSError(
            "Observation store unavailable"
        )

    monkeypatch.setattr(
        session_module,
        "append_observation",
        raise_write_failure,
    )

    ledger_path = (
        tmp_path / "events.jsonl"
    )

    result = run_daily_evaluation(
        ledger_path=ledger_path,
        session_date=SESSION_DATE,
        market_candles={
            "EUR_GBP": make_candles(count=60),
        },
        protocol=make_protocol(),
        policy_verifier=(
            lambda: POLICY_FINGERPRINT
        ),
        session_time_utc=SESSION_TIME,
        software_commit="test-commit",
        observation_store_path=(
            tmp_path / "observations.jsonl"
        ),
    )

    assert result["status"] == "COMPLETED"
    assert result["observations_attempted"] == 1
    assert result["observations_recorded"] == 0
    assert result["observation_duplicates"] == 0
    assert result["observation_failures"] == 1

    assert result["observation_errors"] == [
        {
            "market": "EUR_GBP",
            "error_type": "OSError",
            "error_message": (
                "Observation store unavailable"
            ),
        }
    ]

    events = verify_ledger(
        ledger_path
    )

    assert events[-1][
        "event_type"
    ] == "SESSION_COMPLETED"

