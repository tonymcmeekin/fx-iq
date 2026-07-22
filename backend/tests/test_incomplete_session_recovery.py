import json
from datetime import UTC, date, datetime

import pytest

from app.paper_trading.ledger import (
    append_event,
    verify_ledger,
)
from app.paper_trading.orchestrator import (
    observation_staging_path,
)
from app.paper_trading.runtime_state import (
    empty_runtime_state,
    write_runtime_state,
)
from scripts.recover_incomplete_paper_session import (
    IncompleteSessionRecoveryError,
    apply_recovery_plan,
    build_recovery_plan,
)

TARGET_DATE = date(2026, 7, 22)
OCCURRED_AT = "2026-07-22T07:00:00Z"


def append_session_event(
    ledger_path,
    event_type,
    session_date,
):
    return append_event(
        ledger_path,
        event_type,
        {
            "session_date": session_date,
            "broker_orders_sent": 0,
        },
        occurred_at_utc=OCCURRED_AT,
    )


def make_incomplete_runtime(tmp_path):
    ledger_path = tmp_path / "events.jsonl"
    state_path = tmp_path / "state.json"
    observation_path = tmp_path / "observations.jsonl"
    candle_directory = tmp_path / "candles"

    append_session_event(
        ledger_path,
        "SESSION_STARTED",
        "2026-07-21",
    )
    append_session_event(
        ledger_path,
        "SESSION_COMPLETED",
        "2026-07-21",
    )
    append_session_event(
        ledger_path,
        "SESSION_STARTED",
        TARGET_DATE.isoformat(),
    )
    append_session_event(
        ledger_path,
        "SIGNAL_EVALUATED",
        TARGET_DATE.isoformat(),
    )

    state = empty_runtime_state()
    state["last_completed_session_date"] = (
        "2026-07-21"
    )
    write_runtime_state(state_path, state)

    observation_path.write_text(
        json.dumps(
            {
                "session_date": "2026-07-21",
                "observation_id": "kept",
            }
        )
        + "\n"
        + json.dumps(
            {
                "session_date": TARGET_DATE.isoformat(),
                "observation_id": "removed",
            }
        )
        + "\n"
    )
    observation_staging_path(
        observation_path,
        TARGET_DATE,
    ).write_text(
        json.dumps(
            {
                "session_date": TARGET_DATE.isoformat(),
                "observation_id": "staged-removed",
            }
        )
        + "\n"
    )

    return {
        "ledger_path": ledger_path,
        "state_path": state_path,
        "journal_path": tmp_path / "transition.json",
        "observation_path": observation_path,
        "candle_directory": candle_directory,
        "backup_root": tmp_path / "backups",
    }


def test_recovery_plan_requires_contiguous_uncommitted_tail(
    tmp_path,
):
    paths = make_incomplete_runtime(tmp_path)

    plan = build_recovery_plan(
        session_date=TARGET_DATE,
        **{
            key: value
            for key, value in paths.items()
            if key != "backup_root"
        },
    )

    assert plan["status"] == "RECOVERY_SAFE"
    assert plan["events_to_remove"] == 2
    assert plan["observations_to_remove"] == 1
    assert plan[
        "staged_observations_to_remove"
    ] == 1
    assert plan["broker_orders_sent"] == 0


def test_apply_recovery_backs_up_and_removes_only_target_tail(
    tmp_path,
):
    paths = make_incomplete_runtime(tmp_path)

    result = apply_recovery_plan(
        session_date=TARGET_DATE,
        now_utc=datetime(
            2026,
            7,
            22,
            12,
            0,
            tzinfo=UTC,
        ),
        **paths,
        require_clean_worktree=False,
    )

    events = verify_ledger(
        paths["ledger_path"]
    )
    observations = [
        json.loads(line)
        for line in paths[
            "observation_path"
        ].read_text().splitlines()
    ]

    assert result["status"] == "RECOVERED"
    assert [
        event["payload"]["session_date"]
        for event in events
    ] == [
        "2026-07-21",
        "2026-07-21",
    ]
    assert observations == [
        {
            "session_date": "2026-07-21",
            "observation_id": "kept",
        }
    ]
    backup_directory = paths[
        "backup_root"
    ] / "2026-07-22-20260722T120000000000Z"
    assert (backup_directory / "events.jsonl").exists()
    assert (backup_directory / "state.json").exists()
    assert (
        backup_directory / "recovery_receipt.json"
    ).exists()
    assert (
        backup_directory
        / observation_staging_path(
            paths["observation_path"],
            TARGET_DATE,
        ).name
    ).exists()
    assert observation_staging_path(
        paths["observation_path"],
        TARGET_DATE,
    ).exists() is False


def test_recovery_refuses_completed_session(
    tmp_path,
):
    paths = make_incomplete_runtime(tmp_path)
    append_session_event(
        paths["ledger_path"],
        "SESSION_COMPLETED",
        TARGET_DATE.isoformat(),
    )

    with pytest.raises(
        IncompleteSessionRecoveryError,
        match="completed",
    ):
        build_recovery_plan(
            session_date=TARGET_DATE,
            **{
                key: value
                for key, value in paths.items()
                if key != "backup_root"
            },
        )


def test_recovery_refuses_recorded_broker_activity(
    tmp_path,
):
    paths = make_incomplete_runtime(tmp_path)
    append_event(
        paths["ledger_path"],
        "RISK_DECIDED",
        {
            "session_date": TARGET_DATE.isoformat(),
            "broker_order_submitted": True,
        },
        occurred_at_utc=OCCURRED_AT,
    )

    with pytest.raises(
        IncompleteSessionRecoveryError,
        match="broker activity",
    ):
        build_recovery_plan(
            session_date=TARGET_DATE,
            **{
                key: value
                for key, value in paths.items()
                if key != "backup_root"
            },
        )
