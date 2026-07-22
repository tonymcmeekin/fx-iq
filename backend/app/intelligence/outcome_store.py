"""Append-only outcome enrichment for passive trade observations."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.intelligence.observation_store import read_observations
from app.paper_trading.candle_store import read_candle_store
from app.paper_trading.ledger import verify_ledger


class ObservationOutcomeRecord(BaseModel):
    """Immutable outcome linked to one accepted observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    outcome_id: str = Field(min_length=64, max_length=64)
    observation_id: str = Field(min_length=64, max_length=64)
    close_event_id: str
    enriched_at_utc: datetime
    originating_session_date: date
    close_session_date: date
    instrument: str
    direction: str
    signal_candle_timestamp: datetime
    entry_timestamp: datetime
    exit_timestamp: datetime
    profit_percent: float
    candles_held: int = Field(ge=0)
    maximum_favourable_excursion_percent: float
    maximum_adverse_excursion_percent: float
    exit_reason: str


class ObservationOutcomeError(RuntimeError):
    """Raised when outcome enrichment is unsafe or ambiguous."""


def read_outcomes(
    store_path: Path,
) -> list[ObservationOutcomeRecord]:
    if not store_path.exists():
        return []

    outcomes = []
    seen_outcome_ids = set()
    seen_observation_ids = set()

    for line_number, line in enumerate(
        store_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        try:
            outcome = ObservationOutcomeRecord.model_validate_json(
                line
            )
        except ValueError as error:
            raise ObservationOutcomeError(
                f"Invalid outcome at line {line_number}."
            ) from error

        if outcome.outcome_id in seen_outcome_ids:
            raise ObservationOutcomeError(
                f"Duplicate outcome ID: {outcome.outcome_id}."
            )
        if outcome.observation_id in seen_observation_ids:
            raise ObservationOutcomeError(
                "An observation has multiple outcomes."
            )
        seen_outcome_ids.add(outcome.outcome_id)
        seen_observation_ids.add(outcome.observation_id)
        outcomes.append(outcome)

    return outcomes


def append_outcome(
    store_path: Path,
    outcome: ObservationOutcomeRecord,
) -> None:
    existing = read_outcomes(store_path)
    if any(item.outcome_id == outcome.outcome_id for item in existing):
        raise ObservationOutcomeError(
            f"Duplicate outcome ID: {outcome.outcome_id}."
        )
    if any(
        item.observation_id == outcome.observation_id
        for item in existing
    ):
        raise ObservationOutcomeError(
            "An observation already has an outcome."
        )

    store_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            outcome.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(
        store_path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o600,
    )
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        raise ObservationOutcomeError(
            "Outcome timestamps must be timezone-aware."
        )
    return parsed.astimezone(UTC)


def _excursions(
    *,
    direction: str,
    entry_price: float,
    candles,
) -> tuple[float, float]:
    maximum_high = max(candle.high for candle in candles)
    minimum_low = min(candle.low for candle in candles)

    if direction == "BUY":
        favourable = (
            (maximum_high - entry_price)
            / entry_price
            * 100
        )
        adverse = (
            (minimum_low - entry_price)
            / entry_price
            * 100
        )
    elif direction == "SELL":
        favourable = (
            (entry_price - minimum_low)
            / entry_price
            * 100
        )
        adverse = (
            (entry_price - maximum_high)
            / entry_price
            * 100
        )
    else:
        raise ObservationOutcomeError(
            "Outcome direction must be BUY or SELL."
        )

    return round(favourable, 10), round(adverse, 10)


def enrich_observation_outcomes(
    *,
    ledger_path: Path,
    observation_path: Path,
    outcome_path: Path,
    candle_directory: Path,
    enriched_at_utc: datetime | None = None,
) -> dict[str, int | str]:
    events = verify_ledger(ledger_path)
    observations = read_observations(observation_path)
    existing = read_outcomes(outcome_path)
    completed_close_ids = {
        outcome.close_event_id
        for outcome in existing
    }
    close_events = [
        event
        for event in events
        if event["event_type"] == "PAPER_POSITION_CLOSED"
    ]
    resolved_time = enriched_at_utc or datetime.now(UTC)
    if resolved_time.tzinfo is None:
        raise ValueError("Enrichment time must be timezone-aware.")

    recorded = 0
    duplicates = 0

    for event in close_events:
        if event["event_id"] in completed_close_ids:
            duplicates += 1
            continue

        payload = event["payload"]
        candidate = payload.get("candidate_trade")
        if not isinstance(candidate, dict):
            raise ObservationOutcomeError(
                "Close event has no candidate trade."
            )

        market = str(payload["market"])
        originating_date = date.fromisoformat(
            str(candidate["created_session_date"])
        )
        signal_timestamp = _parse_utc(
            str(candidate["signal_candle_timestamp"])
        )
        matches = [
            observation
            for observation in observations
            if observation.session_date == originating_date
            and observation.instrument == market
            and observation.latest_candle_timestamp == signal_timestamp
            and observation.trade_accepted
            and observation.direction in {"BUY", "SELL"}
        ]
        if len(matches) != 1:
            raise ObservationOutcomeError(
                "Close event does not link to exactly one accepted observation."
            )
        observation = matches[0]
        entry_timestamp = _parse_utc(
            str(candidate["entry_timestamp"])
        )
        exit_timestamp = _parse_utc(
            str(candidate["exit_timestamp"])
        )
        candles = [
            candle
            for candle in read_candle_store(
                candle_directory / f"{market}.csv",
                expected_symbol=market,
            )
            if entry_timestamp
            <= candle.timestamp.astimezone(UTC)
            <= exit_timestamp
        ]
        if not candles:
            raise ObservationOutcomeError(
                "No stored candles cover the position outcome."
            )
        timestamps = [
            candle.timestamp.astimezone(UTC)
            for candle in candles
        ]
        if entry_timestamp not in timestamps or exit_timestamp not in timestamps:
            raise ObservationOutcomeError(
                "Stored candles do not include entry and exit timestamps."
            )
        favourable, adverse = _excursions(
            direction=str(candidate["direction"]),
            entry_price=float(candidate["entry_price"]),
            candles=candles,
        )
        identity = (
            f"{observation.observation_id}|{event['event_id']}"
        )
        outcome = ObservationOutcomeRecord(
            outcome_id=hashlib.sha256(
                identity.encode("utf-8")
            ).hexdigest(),
            observation_id=observation.observation_id,
            close_event_id=event["event_id"],
            enriched_at_utc=resolved_time.astimezone(UTC),
            originating_session_date=originating_date,
            close_session_date=exit_timestamp.date(),
            instrument=market,
            direction=str(candidate["direction"]),
            signal_candle_timestamp=signal_timestamp,
            entry_timestamp=entry_timestamp,
            exit_timestamp=exit_timestamp,
            profit_percent=float(
                candidate["account_return_percent"]
            ),
            candles_held=(
                timestamps.index(exit_timestamp)
                - timestamps.index(entry_timestamp)
            ),
            maximum_favourable_excursion_percent=favourable,
            maximum_adverse_excursion_percent=adverse,
            exit_reason=str(candidate["exit_reason"]),
        )
        append_outcome(outcome_path, outcome)
        completed_close_ids.add(event["event_id"])
        recorded += 1

    return {
        "status": "COMPLETED",
        "close_events": len(close_events),
        "outcomes_recorded": recorded,
        "outcome_duplicates": duplicates,
        "broker_orders_sent": 0,
    }
