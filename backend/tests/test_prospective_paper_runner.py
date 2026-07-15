from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from scripts.run_prospective_paper_session import (
    BACKEND_DIRECTORY,
    CANDLE_STORE_DIRECTORY,
    JOURNAL_PATH,
    LEDGER_PATH,
    PROTOCOL_PATH,
    STATE_PATH,
    GuardedRunnerError,
    execute,
    main,
    redact_error,
    resolve_session_date,
)

NOW = datetime(
    2026,
    7,
    16,
    23,
    15,
    tzinfo=UTC,
)

POLICY_FINGERPRINT = "test-policy-fingerprint"


def successful_result():
    return {
        "status": "COMPLETED",
        "session_date": "2026-07-16",
        "policy_fingerprint": (POLICY_FINGERPRINT),
        "recovered_existing_journal": False,
        "runtime_state_updated": True,
        "pending_entries_total": 1,
        "open_positions_total": 0,
        "candidate_balance": 10000.0,
        "shadow_balance": 10000.0,
        "broker_orders_sent": 0,
    }


def safe_dependencies(
    *,
    calls=None,
):
    def session_runner(**kwargs):
        if calls is not None:
            calls.append(kwargs)

        return successful_result()

    return {
        "session_runner": session_runner,
        "policy_verifier": (lambda: POLICY_FINGERPRINT),
        "commit_reader": (
            lambda: (
                "aa716ac",
                False,
            )
        ),
        "now_provider": (lambda: NOW),
    }


def test_explicit_practice_gate_is_required():
    with pytest.raises(
        GuardedRunnerError,
        match="--use-oanda-practice",
    ):
        execute(
            [],
            environment={
                "OANDA_API_TOKEN": ("test-token"),
            },
            **safe_dependencies(),
        )


def test_token_is_required_after_gate():
    with pytest.raises(
        GuardedRunnerError,
        match="OANDA_API_TOKEN",
    ):
        execute(
            [
                "--use-oanda-practice",
            ],
            environment={},
            **safe_dependencies(),
        )


def test_live_environment_is_rejected_before_runner():
    called = False

    def session_runner(**kwargs):
        nonlocal called
        called = True
        return successful_result()

    dependencies = safe_dependencies()
    dependencies["session_runner"] = session_runner

    with pytest.raises(
        GuardedRunnerError,
        match="practice environment",
    ):
        execute(
            [
                "--use-oanda-practice",
            ],
            environment={
                "OANDA_API_TOKEN": ("test-token"),
                "OANDA_ENVIRONMENT": "live",
            },
            **dependencies,
        )

    assert called is False


def test_dirty_source_tree_is_rejected():
    dependencies = safe_dependencies()
    dependencies["commit_reader"] = lambda: (
        "aa716ac",
        True,
    )

    with pytest.raises(
        GuardedRunnerError,
        match="Tracked source files",
    ):
        execute(
            [
                "--use-oanda-practice",
            ],
            environment={
                "OANDA_API_TOKEN": ("test-token"),
            },
            **dependencies,
        )


def test_invalid_candle_count_is_rejected():
    with pytest.raises(
        GuardedRunnerError,
        match="between 21 and 5000",
    ):
        execute(
            [
                "--use-oanda-practice",
                "--candle-count",
                "20",
            ],
            environment={
                "OANDA_API_TOKEN": ("test-token"),
            },
            **safe_dependencies(),
        )


def test_invalid_session_date_is_rejected():
    with pytest.raises(
        GuardedRunnerError,
        match="YYYY-MM-DD",
    ):
        execute(
            [
                "--use-oanda-practice",
                "--session-date",
                "16-07-2026",
            ],
            environment={
                "OANDA_API_TOKEN": ("test-token"),
            },
            **safe_dependencies(),
        )


def test_default_session_date_uses_utc_date():
    resolved = resolve_session_date(
        None,
        current_time=NOW,
    )

    assert resolved == date(
        2026,
        7,
        16,
    )


def test_runner_uses_fixed_paths_and_practice_only():
    calls = []

    summary = execute(
        [
            "--use-oanda-practice",
            "--session-date",
            "2026-07-16",
            "--candle-count",
            "125",
        ],
        environment={
            "OANDA_API_TOKEN": ("secret-test-token"),
            "OANDA_ENVIRONMENT": ("practice"),
        },
        **safe_dependencies(calls=calls),
    )

    assert len(calls) == 1

    call = calls[0]

    assert call["api_token"] == "secret-test-token"

    assert call["environment"] == "practice"

    assert call["session_date"] == date(
        2026,
        7,
        16,
    )

    assert call["session_time_utc"] == NOW

    assert call["candle_count"] == 125

    assert call["software_commit"] == "aa716ac"

    assert call["ledger_path"] == LEDGER_PATH

    assert call["state_path"] == STATE_PATH

    assert call["journal_path"] == JOURNAL_PATH

    assert call["protocol_path"] == PROTOCOL_PATH

    assert call["candle_store_directory"] == CANDLE_STORE_DIRECTORY

    assert summary["broker_orders_sent"] == 0

    assert summary["software_commit"] == "aa716ac"

    assert "secret-test-token" not in str(summary)


def test_runtime_paths_are_inside_backend():
    for path in (
        LEDGER_PATH,
        STATE_PATH,
        JOURNAL_PATH,
        PROTOCOL_PATH,
        CANDLE_STORE_DIRECTORY,
    ):
        assert isinstance(
            path,
            Path,
        )

        assert path.is_relative_to(BACKEND_DIRECTORY)


def test_nonzero_broker_order_result_is_rejected():
    def unsafe_runner(**kwargs):
        del kwargs

        result = successful_result()
        result["broker_orders_sent"] = 1

        return result

    dependencies = safe_dependencies()
    dependencies["session_runner"] = unsafe_runner

    with pytest.raises(
        GuardedRunnerError,
        match="records broker orders",
    ):
        execute(
            [
                "--use-oanda-practice",
            ],
            environment={
                "OANDA_API_TOKEN": ("test-token"),
            },
            **dependencies,
        )


def test_error_redaction_removes_token():
    token = "highly-secret-token"

    error = RuntimeError(f"Request failed using {token}.")

    message = redact_error(
        error,
        environment={
            "OANDA_API_TOKEN": token,
        },
    )

    assert token not in message
    assert "[REDACTED]" in message


def test_main_prints_safe_json_only(
    monkeypatch,
    capsys,
):
    from scripts import (
        run_prospective_paper_session as runner,
    )

    monkeypatch.setattr(
        runner,
        "execute",
        lambda argv=None: {
            "status": "COMPLETED",
            "session_date": ("2026-07-16"),
            "broker_orders_sent": 0,
        },
    )

    exit_code = main(
        [
            "--use-oanda-practice",
        ]
    )

    output = capsys.readouterr()

    assert exit_code == 0
    assert '"status": "COMPLETED"' in (output.out)
    assert output.err == ""


def test_runner_tests_make_no_network_calls(
    monkeypatch,
):
    from app.market_data import oanda

    def forbidden_network_call(**kwargs):
        raise AssertionError(f"Unexpected network call: {kwargs}")

    monkeypatch.setattr(
        oanda,
        "download_oanda_candles",
        forbidden_network_call,
    )

    calls = []

    summary = execute(
        [
            "--use-oanda-practice",
        ],
        environment={
            "OANDA_API_TOKEN": ("test-token"),
        },
        **safe_dependencies(calls=calls),
    )

    assert summary["status"] == "COMPLETED"

    assert len(calls) == 1
