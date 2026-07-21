"""Append-only JSONL storage for passive trade observations."""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.intelligence.observations import (
    TradeObservation,
)


class ObservationStoreError(RuntimeError):
    """Raised when observation storage is invalid."""


def _encoded_observation(
    observation: TradeObservation,
) -> bytes:
    payload = observation.model_dump(
        mode="json",
    )

    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def read_observations(
    store_path: Path,
) -> list[TradeObservation]:
    if not store_path.exists():
        return []

    observations: list[TradeObservation] = []
    seen_ids: set[str] = set()

    with store_path.open(
        encoding="utf-8",
    ) as input_file:
        for line_number, line in enumerate(
            input_file,
            start=1,
        ):
            stripped = line.strip()

            if not stripped:
                raise ObservationStoreError(f"Blank observation line at {line_number}.")

            try:
                payload = json.loads(stripped)
                observation = TradeObservation.model_validate(payload)
            except (
                json.JSONDecodeError,
                ValueError,
            ) as error:
                raise ObservationStoreError(
                    f"Invalid observation at line {line_number}."
                ) from error

            if observation.observation_id in seen_ids:
                raise ObservationStoreError(
                    f"Duplicate observation ID: {observation.observation_id}."
                )

            seen_ids.add(observation.observation_id)
            observations.append(observation)

    return observations


def append_observation(
    store_path: Path,
    observation: TradeObservation,
) -> TradeObservation:
    existing = read_observations(store_path)

    if any(item.observation_id == observation.observation_id for item in existing):
        raise ObservationStoreError(f"Duplicate observation ID: {observation.observation_id}.")

    store_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_descriptor = os.open(
        store_path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o600,
    )

    try:
        os.write(
            file_descriptor,
            _encoded_observation(observation),
        )
        os.fsync(file_descriptor)
    finally:
        os.close(file_descriptor)

    stored = read_observations(store_path)

    if stored[-1] != observation:
        raise ObservationStoreError("Appended observation could not be verified.")

    return observation
