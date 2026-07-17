import csv
import json
from pathlib import Path

import pytest

from app.paper_trading.ledger import append_event
from app.paper_trading.runtime_state import empty_runtime_state
from scripts import check_prospective_paper_health as health

MARKETS = health.EXPECTED_MARKETS
TIMESTAMP = "2026-07-15T21:00:00Z"


def write_state(
    state_path: Path,
    *,
    broker_orders_sent: int = 0,
) -> dict:
    state = empty_runtime_state()
    state.update(
        {
            "last_completed_session_date": "2026-07-17",
            "last_updated_at_utc": "2026-07-17T08:06:08Z",
            "broker_orders_sent": broker_orders_sent,
            "processed_candle_timestamps": {market: TIMESTAMP for market in MARKETS},
        }
    )

    state_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    state_path.write_text(
        json.dumps(state),
        encoding="utf-8",
    )

    return state


def write_ledger(
    ledger_path: Path,
    *,
    state: dict,
    session_date: str = "2026-07-17",
) -> None:
    append_event(
        ledger_path,
        "SESSION_STARTED",
        {
            "session_date": session_date,
        },
        event_id=f"started-{session_date}",
        occurred_at_utc="2026-07-17T08:00:00Z",
    )

    append_event(
        ledger_path,
        "SESSION_COMPLETED",
        {
            "session_date": session_date,
            "status": "SUCCESS",
            "candidate_balance": state["candidate_balance"],
            "shadow_balance": state["shadow_balance"],
            "open_positions": len(state["open_positions"]),
            "pending_entries": len(state["pending_entries"]),
            "broker_orders_sent": 0,
        },
        event_id=f"completed-{session_date}",
        occurred_at_utc="2026-07-17T08:01:00Z",
    )


def write_candles(
    candle_directory: Path,
) -> None:
    candle_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    for market in MARKETS:
        with (candle_directory / f"{market}.csv").open(
            "w",
            newline="",
            encoding="utf-8",
        ) as candle_file:
            writer = csv.DictWriter(
                candle_file,
                fieldnames=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                ],
            )

            writer.writeheader()
            writer.writerow(
                {
                    "timestamp": TIMESTAMP,
                    "open": "1.0",
                    "high": "1.2",
                    "low": "0.9",
                    "close": "1.1",
                    "volume": "100",
                }
            )


@pytest.fixture
def runtime_paths(
    tmp_path,
    monkeypatch,
):
    ledger_path = tmp_path / "paper_ledger" / "events.jsonl"
    state_path = tmp_path / "paper_ledger" / "state.json"
    journal_path = tmp_path / "paper_ledger" / "transition.json"
    candle_directory = tmp_path / "data" / "prospective_paper"

    monkeypatch.setattr(
        health,
        "LEDGER_PATH",
        ledger_path,
    )
    monkeypatch.setattr(
        health,
        "STATE_PATH",
        state_path,
    )
    monkeypatch.setattr(
        health,
        "JOURNAL_PATH",
        journal_path,
    )
    monkeypatch.setattr(
        health,
        "CANDLE_DIRECTORY",
        candle_directory,
    )

    return {
        "ledger": ledger_path,
        "state": state_path,
        "journal": journal_path,
        "candles": candle_directory,
    }


def build_healthy_runtime(
    paths,
) -> None:
    state = write_state(paths["state"])
    write_ledger(
        paths["ledger"],
        state=state,
    )
    write_candles(paths["candles"])


def test_healthy_runtime_passes(
    runtime_paths,
):
    build_healthy_runtime(runtime_paths)

    summary = health.perform_health_check()

    assert summary["status"] == "HEALTHY"
    assert summary["ledger_events"] == 2
    assert summary["broker_orders_sent"] == 0
    assert summary["network_calls_made"] == 0
    assert summary["files_changed"] == 0


def test_tampered_ledger_fails(
    runtime_paths,
):
    build_healthy_runtime(runtime_paths)

    events = [json.loads(line) for line in runtime_paths["ledger"].read_text().splitlines()]

    events[-1]["payload"]["candidate_balance"] = 9999.0

    runtime_paths["ledger"].write_text("\n".join(json.dumps(event) for event in events) + "\n")

    with pytest.raises(
        health.PaperHealthError,
        match="Ledger integrity check failed",
    ):
        health.perform_health_check()


def test_unfinished_journal_fails(
    runtime_paths,
):
    build_healthy_runtime(runtime_paths)

    runtime_paths["journal"].write_text(
        "{}",
        encoding="utf-8",
    )

    with pytest.raises(
        health.PaperHealthError,
        match="unfinished transition journal",
    ):
        health.perform_health_check()


def test_missing_candle_file_fails(
    runtime_paths,
):
    build_healthy_runtime(runtime_paths)

    (runtime_paths["candles"] / "EUR_GBP.csv").unlink()

    with pytest.raises(
        health.PaperHealthError,
        match="Missing candle files",
    ):
        health.perform_health_check()


def test_candle_checkpoint_mismatch_fails(
    runtime_paths,
):
    build_healthy_runtime(runtime_paths)

    path = runtime_paths["candles"] / "EUR_GBP.csv"

    text = path.read_text(encoding="utf-8").replace(
        TIMESTAMP,
        "2026-07-14T21:00:00Z",
    )

    path.write_text(
        text,
        encoding="utf-8",
    )

    with pytest.raises(
        health.PaperHealthError,
        match="does not match runtime state",
    ):
        health.perform_health_check()


def test_state_and_ledger_balance_mismatch_fails(
    runtime_paths,
):
    build_healthy_runtime(runtime_paths)

    state = json.loads(runtime_paths["state"].read_text())
    state["candidate_balance"] = 9000.0

    runtime_paths["state"].write_text(
        json.dumps(state),
        encoding="utf-8",
    )

    with pytest.raises(
        health.PaperHealthError,
        match="candidate_balance does not match",
    ):
        health.perform_health_check()


def test_duplicate_completed_session_fails(
    runtime_paths,
):
    build_healthy_runtime(runtime_paths)

    append_event(
        runtime_paths["ledger"],
        "SESSION_COMPLETED",
        {
            "session_date": "2026-07-17",
            "status": "SUCCESS",
            "candidate_balance": 10000.0,
            "shadow_balance": 10000.0,
            "open_positions": 0,
            "pending_entries": 0,
            "broker_orders_sent": 0,
        },
        event_id="duplicate-completion",
        occurred_at_utc="2026-07-17T08:02:00Z",
    )

    with pytest.raises(
        health.PaperHealthError,
        match="Duplicate completed sessions",
    ):
        health.perform_health_check()


def test_execute_returns_one_for_unhealthy_runtime(
    runtime_paths,
    capsys,
):
    result = health.execute([])

    captured = capsys.readouterr()

    assert result == 1
    assert '"status": "UNHEALTHY"' in captured.err
