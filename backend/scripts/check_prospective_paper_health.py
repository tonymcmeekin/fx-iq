import argparse
import csv
import json
import math
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]

if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND_DIRECTORY),
    )

from app.paper_trading.ledger import (  # noqa: E402
    LedgerIntegrityError,
    verify_ledger,
)
from app.paper_trading.runtime_state import (  # noqa: E402
    RuntimeStateError,
    verify_runtime_state,
)

LEDGER_PATH = BACKEND_DIRECTORY / "paper_ledger" / "events.jsonl"
STATE_PATH = BACKEND_DIRECTORY / "paper_ledger" / "state.json"
JOURNAL_PATH = BACKEND_DIRECTORY / "paper_ledger" / "transition.json"
CANDLE_DIRECTORY = BACKEND_DIRECTORY / "data" / "prospective_paper"

EXPECTED_MARKETS = (
    "EUR_GBP",
    "EUR_JPY",
    "GBP_JPY",
    "AUD_JPY",
    "CAD_JPY",
    "AUD_CAD",
)

REQUIRED_CANDLE_COLUMNS = {
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
}


class PaperHealthError(RuntimeError):
    """Raised when prospective paper runtime health checks fail."""


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Perform a read-only integrity and safety check of the "
            "prospective paper-trading runtime."
        )
    )


def read_runtime_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        raise PaperHealthError(f"Runtime state file is missing: {state_path}")

    try:
        raw_state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PaperHealthError("Runtime state contains invalid JSON.") from error

    try:
        return verify_runtime_state(raw_state)
    except RuntimeStateError as error:
        raise PaperHealthError(f"Runtime state is invalid: {error}") from error


def verify_completed_sessions(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    if not events:
        raise PaperHealthError("Ledger contains no events.")

    if events[-1]["event_type"] != "SESSION_COMPLETED":
        raise PaperHealthError("Latest ledger event is not SESSION_COMPLETED.")

    completed_events = [event for event in events if event["event_type"] == "SESSION_COMPLETED"]

    completed_dates = [event["payload"].get("session_date") for event in completed_events]

    if any(not isinstance(value, str) or not value for value in completed_dates):
        raise PaperHealthError("A SESSION_COMPLETED event has no valid session date.")

    duplicate_dates = sorted(
        session_date for session_date, count in Counter(completed_dates).items() if count > 1
    )

    if duplicate_dates:
        raise PaperHealthError(
            "Duplicate completed sessions found for: " + ", ".join(duplicate_dates)
        )

    latest = completed_events[-1]
    payload = latest["payload"]

    if payload.get("status") != "SUCCESS":
        raise PaperHealthError("Latest completed session did not record SUCCESS.")

    if payload.get("broker_orders_sent") != 0:
        raise PaperHealthError("Latest completed session records broker orders.")

    return latest


def verify_state_matches_ledger(
    state: dict[str, Any],
    completed_event: dict[str, Any],
) -> None:
    payload = completed_event["payload"]

    comparisons = {
        "last_completed_session_date": payload.get("session_date"),
        "candidate_balance": payload.get("candidate_balance"),
        "shadow_balance": payload.get("shadow_balance"),
    }

    for state_field, ledger_value in comparisons.items():
        if state.get(state_field) != ledger_value:
            raise PaperHealthError(
                f"State field {state_field} does not match the latest completed ledger event."
            )

    if len(state["open_positions"]) != payload.get("open_positions"):
        raise PaperHealthError("Open-position count does not match the ledger.")

    if len(state["pending_entries"]) != payload.get("pending_entries"):
        raise PaperHealthError("Pending-entry count does not match the ledger.")

    if state["broker_orders_sent"] != 0:
        raise PaperHealthError("Runtime state records broker orders.")

    for balance_field in (
        "candidate_balance",
        "shadow_balance",
        "candidate_peak_equity",
        "shadow_peak_equity",
    ):
        value = state[balance_field]

        if not math.isfinite(value):
            raise PaperHealthError(f"{balance_field} is not finite.")

        if value <= 0:
            raise PaperHealthError(f"{balance_field} is not positive.")


def verify_processed_candles(
    state: dict[str, Any],
) -> dict[str, str]:
    processed = state["processed_candle_timestamps"]

    missing = sorted(set(EXPECTED_MARKETS) - processed.keys())

    unexpected = sorted(processed.keys() - set(EXPECTED_MARKETS))

    if missing:
        raise PaperHealthError("Missing processed-candle checkpoints for: " + ", ".join(missing))

    if unexpected:
        raise PaperHealthError(
            "Unexpected processed-candle checkpoints for: " + ", ".join(unexpected)
        )

    return {market: processed[market] for market in EXPECTED_MARKETS}


def read_candle_file(
    path: Path,
) -> tuple[int, str]:
    if not path.exists():
        raise PaperHealthError(f"Candle file is missing: {path.name}")

    if path.stat().st_size == 0:
        raise PaperHealthError(f"Candle file is empty: {path.name}")

    try:
        with path.open(
            newline="",
            encoding="utf-8",
        ) as candle_file:
            reader = csv.DictReader(candle_file)

            if reader.fieldnames is None:
                raise PaperHealthError(f"Candle file has no header: {path.name}")

            missing_columns = REQUIRED_CANDLE_COLUMNS - set(reader.fieldnames)

            if missing_columns:
                raise PaperHealthError(
                    f"Candle file {path.name} is missing columns: "
                    + ", ".join(sorted(missing_columns))
                )

            rows = list(reader)
    except UnicodeDecodeError as error:
        raise PaperHealthError(f"Candle file is not valid UTF-8: {path.name}") from error

    if not rows:
        raise PaperHealthError(f"Candle file has no candle rows: {path.name}")

    timestamps = [row.get("timestamp", "") for row in rows]

    if any(not timestamp for timestamp in timestamps):
        raise PaperHealthError(f"Candle file contains a blank timestamp: {path.name}")

    if timestamps != sorted(timestamps):
        raise PaperHealthError(f"Candle timestamps are not ordered: {path.name}")

    if len(timestamps) != len(set(timestamps)):
        raise PaperHealthError(f"Candle file contains duplicate timestamps: {path.name}")

    for row_number, row in enumerate(
        rows,
        start=2,
    ):
        try:
            open_price = float(row["open"])
            high_price = float(row["high"])
            low_price = float(row["low"])
            close_price = float(row["close"])
            volume = float(row["volume"])
        except (TypeError, ValueError) as error:
            raise PaperHealthError(
                f"Invalid numeric candle value in {path.name} at row {row_number}."
            ) from error

        numeric_values = (
            open_price,
            high_price,
            low_price,
            close_price,
            volume,
        )

        if not all(math.isfinite(value) for value in numeric_values):
            raise PaperHealthError(f"Non-finite candle value in {path.name} at row {row_number}.")

        if high_price < max(
            open_price,
            close_price,
            low_price,
        ):
            raise PaperHealthError(f"Invalid candle high in {path.name} at row {row_number}.")

        if low_price > min(
            open_price,
            close_price,
            high_price,
        ):
            raise PaperHealthError(f"Invalid candle low in {path.name} at row {row_number}.")

        if volume < 0:
            raise PaperHealthError(f"Negative candle volume in {path.name} at row {row_number}.")

    return len(rows), timestamps[-1]


def verify_candle_store(
    checkpoints: dict[str, str],
) -> dict[str, dict[str, Any]]:
    expected_files = {f"{market}.csv" for market in EXPECTED_MARKETS}

    actual_files = {path.name for path in CANDLE_DIRECTORY.glob("*.csv")}

    missing_files = sorted(expected_files - actual_files)

    unexpected_files = sorted(actual_files - expected_files)

    if missing_files:
        raise PaperHealthError("Missing candle files: " + ", ".join(missing_files))

    if unexpected_files:
        raise PaperHealthError("Unexpected candle files: " + ", ".join(unexpected_files))

    summary = {}

    for market in EXPECTED_MARKETS:
        row_count, latest_timestamp = read_candle_file(CANDLE_DIRECTORY / f"{market}.csv")

        if latest_timestamp != checkpoints[market]:
            raise PaperHealthError(
                f"Latest candle timestamp for {market} does not match runtime state."
            )

        summary[market] = {
            "rows": row_count,
            "latest_timestamp": latest_timestamp,
        }

    return summary


def perform_health_check() -> dict[str, Any]:
    if JOURNAL_PATH.exists():
        raise PaperHealthError("An unfinished transition journal exists.")

    try:
        events = verify_ledger(LEDGER_PATH)
    except LedgerIntegrityError as error:
        raise PaperHealthError(f"Ledger integrity check failed: {error}") from error

    state = read_runtime_state(STATE_PATH)

    latest_completed = verify_completed_sessions(events)

    verify_state_matches_ledger(
        state,
        latest_completed,
    )

    checkpoints = verify_processed_candles(state)

    candle_summary = verify_candle_store(checkpoints)

    return {
        "status": "HEALTHY",
        "ledger_events": len(events),
        "last_sequence": events[-1]["sequence"],
        "last_event_type": events[-1]["event_type"],
        "last_completed_session_date": state["last_completed_session_date"],
        "candidate_balance": state["candidate_balance"],
        "shadow_balance": state["shadow_balance"],
        "open_positions": len(state["open_positions"]),
        "pending_entries": len(state["pending_entries"]),
        "broker_orders_sent": state["broker_orders_sent"],
        "transition_journal_present": False,
        "markets": candle_summary,
        "network_calls_made": 0,
        "files_changed": 0,
    }


def execute(
    argv: Sequence[str] | None = None,
) -> int:
    parser = build_parser()
    parser.parse_args(argv)

    try:
        summary = perform_health_check()
    except (
        PaperHealthError,
        OSError,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "UNHEALTHY",
                    "error": str(error),
                    "network_calls_made": 0,
                    "files_changed": 0,
                },
                sort_keys=True,
                indent=2,
            ),
            file=sys.stderr,
        )

        return 1

    print(
        json.dumps(
            summary,
            sort_keys=True,
            indent=2,
        )
    )

    return 0


def main() -> int:
    return execute()


if __name__ == "__main__":
    raise SystemExit(main())
