"""Sparse-safe analysis of verified passive-observation outcomes."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from app.intelligence.observation_store import read_observations
from app.intelligence.outcome_store import read_outcomes
from app.intelligence.reporting import build_observation_report

BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER_PATH = BACKEND_DIRECTORY / "paper_ledger" / "events.jsonl"
DEFAULT_OBSERVATION_PATH = (
    BACKEND_DIRECTORY / "paper_ledger" / "intelligence_observations.jsonl"
)
DEFAULT_OUTCOME_PATH = (
    BACKEND_DIRECTORY / "paper_ledger" / "intelligence_outcomes.jsonl"
)
DEFAULT_MINIMUM_OVERALL_SAMPLE = 20
DEFAULT_MINIMUM_GROUP_SAMPLE = 5


class OutcomeExplorerError(RuntimeError):
    """Raised when verified outcome exploration cannot be produced."""


def _percentile(values: list[float], proportion: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _metrics(
    records: list[dict[str, Any]],
    *,
    minimum_sample_size: int,
) -> dict[str, Any]:
    sample_size = len(records)
    available = sample_size >= minimum_sample_size
    result: dict[str, Any] = {
        "sample_size": sample_size,
        "minimum_sample_size": minimum_sample_size,
        "status": "AVAILABLE" if available else "INSUFFICIENT_DATA",
        "mean_return_percent": None,
        "median_return_percent": None,
        "win_rate_percent": None,
        "profit_factor": None,
        "mean_favourable_excursion_percent": None,
        "mean_adverse_excursion_percent": None,
        "mean_candles_held": None,
    }
    if not available:
        return result

    returns = [float(record["profit_percent"]) for record in records]
    winners = [value for value in returns if value > 0]
    losers = [value for value in returns if value < 0]
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    result.update(
        {
            "mean_return_percent": round(mean(returns), 6),
            "median_return_percent": round(median(returns), 6),
            "win_rate_percent": round(len(winners) / sample_size * 100, 6),
            "profit_factor": (
                None if gross_loss == 0 else round(gross_profit / gross_loss, 6)
            ),
            "mean_favourable_excursion_percent": round(
                mean(
                    float(record["maximum_favourable_excursion_percent"])
                    for record in records
                ),
                6,
            ),
            "mean_adverse_excursion_percent": round(
                mean(
                    float(record["maximum_adverse_excursion_percent"])
                    for record in records
                ),
                6,
            ),
            "mean_candles_held": round(
                mean(float(record["candles_held"]) for record in records),
                6,
            ),
        }
    )
    return result


def _distribution(
    records: list[dict[str, Any]],
    *,
    minimum_sample_size: int,
) -> dict[str, Any]:
    available = len(records) >= minimum_sample_size
    result: dict[str, Any] = {
        "sample_size": len(records),
        "minimum_sample_size": minimum_sample_size,
        "status": "AVAILABLE" if available else "INSUFFICIENT_DATA",
        "return_percent": None,
        "favourable_excursion_percent": None,
        "adverse_excursion_percent": None,
        "candles_held": None,
    }
    if not available:
        return result

    for output_key, record_key in (
        ("return_percent", "profit_percent"),
        (
            "favourable_excursion_percent",
            "maximum_favourable_excursion_percent",
        ),
        (
            "adverse_excursion_percent",
            "maximum_adverse_excursion_percent",
        ),
        ("candles_held", "candles_held"),
    ):
        values = [float(record[record_key]) for record in records]
        result[output_key] = {
            "minimum": round(min(values), 6),
            "p25": round(_percentile(values, 0.25), 6),
            "median": round(median(values), 6),
            "p75": round(_percentile(values, 0.75), 6),
            "maximum": round(max(values), 6),
        }
    return result


def _group_rows(
    records: list[dict[str, Any]],
    *,
    minimum_group_sample: int,
) -> list[dict[str, Any]]:
    dimensions = (
        "instrument",
        "direction",
        "strategy",
        "regime_trend",
        "regime_volatility",
        "setup_quality",
        "exit_reason",
    )
    rows = []
    for dimension in dimensions:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            groups[str(record[dimension])].append(record)
        for value, grouped_records in sorted(groups.items()):
            rows.append(
                {
                    "dimension": dimension,
                    "value": value,
                    **_metrics(
                        grouped_records,
                        minimum_sample_size=minimum_group_sample,
                    ),
                }
            )
    return rows


def build_outcome_explorer_report(
    *,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    observation_path: Path = DEFAULT_OBSERVATION_PATH,
    outcome_path: Path = DEFAULT_OUTCOME_PATH,
    minimum_overall_sample: int = DEFAULT_MINIMUM_OVERALL_SAMPLE,
    minimum_group_sample: int = DEFAULT_MINIMUM_GROUP_SAMPLE,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Join outcomes to immutable observations and aggregate them safely."""
    if minimum_overall_sample < minimum_group_sample:
        raise OutcomeExplorerError(
            "Overall sample threshold cannot be below the group threshold."
        )
    if minimum_group_sample < 2:
        raise OutcomeExplorerError("Group sample threshold must be at least two.")

    try:
        integrity = build_observation_report(
            ledger_path=ledger_path,
            observation_path=observation_path,
            outcome_path=outcome_path,
        )
        if integrity["status"] != "HEALTHY":
            raise OutcomeExplorerError(
                "Observation outcome integrity is not healthy: "
                + " ".join(integrity["blocking_issues"])
            )
        observations = {
            observation.observation_id: observation
            for observation in read_observations(observation_path)
        }
        outcomes = read_outcomes(outcome_path)
    except (OSError, RuntimeError, ValueError) as error:
        if isinstance(error, OutcomeExplorerError):
            raise
        raise OutcomeExplorerError(str(error)) from error

    records = []
    for outcome in outcomes:
        observation = observations.get(outcome.observation_id)
        if observation is None:
            raise OutcomeExplorerError(
                f"Outcome {outcome.outcome_id} has no originating observation."
            )
        if (
            observation.instrument != outcome.instrument
            or observation.direction != outcome.direction
        ):
            raise OutcomeExplorerError(
                f"Outcome {outcome.outcome_id} conflicts with its observation."
            )
        records.append(
            {
                "outcome_id": outcome.outcome_id,
                "observation_id": outcome.observation_id,
                "instrument": outcome.instrument,
                "direction": outcome.direction,
                "strategy": observation.strategy,
                "regime_trend": observation.regime.trend,
                "regime_volatility": observation.regime.volatility,
                "setup_quality": observation.features.setup_quality_label,
                "exit_reason": outcome.exit_reason,
                "profit_percent": outcome.profit_percent,
                "candles_held": outcome.candles_held,
                "maximum_favourable_excursion_percent": (
                    outcome.maximum_favourable_excursion_percent
                ),
                "maximum_adverse_excursion_percent": (
                    outcome.maximum_adverse_excursion_percent
                ),
            }
        )

    overall = _metrics(records, minimum_sample_size=minimum_overall_sample)
    grouped = _group_rows(
        records,
        minimum_group_sample=minimum_group_sample,
    )
    available_groups = sum(row["status"] == "AVAILABLE" for row in grouped)
    resolved_now = now_utc or datetime.now(UTC)
    if resolved_now.tzinfo is None:
        raise OutcomeExplorerError("Outcome explorer time must be timezone-aware.")

    return {
        "schema_version": 1,
        "status": overall["status"],
        "generated_at_utc": resolved_now.astimezone(UTC).isoformat(),
        "minimum_overall_sample": minimum_overall_sample,
        "minimum_group_sample": minimum_group_sample,
        "outcome_count": len(records),
        "available_group_count": available_groups,
        "group_count": len(grouped),
        "overall": overall,
        "distribution": _distribution(
            records,
            minimum_sample_size=minimum_overall_sample,
        ),
        "groups": grouped,
        "integrity_status": integrity["status"],
        "integrity_warnings": list(integrity["warnings"]),
        "network_calls_made": 0,
        "files_changed": 0,
        "ledger_writes_performed": 0,
        "broker_orders_submitted": 0,
        "safe_for_live_trading": False,
        "protocol_live_trading_permitted": False,
    }
