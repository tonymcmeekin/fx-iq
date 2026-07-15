import json
from pathlib import Path

from scripts.run_untouched_cross_market_validation import (
    create_close_location_adjuster,
    create_conjunction_adjuster,
    evaluate_candidate,
    sha256_file,
    verify_frozen_inputs,
)


def test_primary_candidate_passes_only_when_all_checks_pass():
    summary = {
        "aggregate_improvement_pp": 1.0,
        "markets_beating_fixed": 4,
        "folds_beating_fixed": 4,
        "markets_lowering_worst_drawdown": 3,
        "profitable_markets": 3,
        "trade_count_equal": True,
        "trade_sequence_equal": True,
        "candidate_aggregate_return": 1.0,
    }

    criteria = {
        "aggregate_return_improvement_over_fixed_percentage_points_greater_than": 0.0,
        "markets_beating_fixed_at_least": 4,
        "chronological_folds_beating_fixed_at_least": 4,
        "markets_with_lower_worst_drawdown_at_least": 3,
        "profitable_candidate_markets_at_least": 3,
    }

    evaluation = evaluate_candidate(
        summary,
        criteria,
    )

    assert evaluation["passed"] is True
    assert all(
        evaluation["checks"].values()
    )


def test_candidate_fails_when_one_required_check_fails():
    summary = {
        "aggregate_improvement_pp": 1.0,
        "markets_beating_fixed": 4,
        "folds_beating_fixed": 3,
        "markets_lowering_worst_drawdown": 3,
        "profitable_markets": 3,
        "trade_count_equal": True,
        "trade_sequence_equal": True,
        "candidate_aggregate_return": 1.0,
    }

    criteria = {
        "aggregate_return_improvement_over_fixed_percentage_points_greater_than": 0.0,
        "markets_beating_fixed_at_least": 4,
        "chronological_folds_beating_fixed_at_least": 4,
        "markets_with_lower_worst_drawdown_at_least": 3,
        "profitable_candidate_markets_at_least": 3,
    }

    evaluation = evaluate_candidate(
        summary,
        criteria,
    )

    assert evaluation["passed"] is False
    assert (
        evaluation["checks"][
            "folds_beating_fixed"
        ]
        is False
    )


def test_inactive_close_features_retain_configured_risk():
    adjuster = (
        create_close_location_adjuster(
            threshold=0.8174,
            reduced_risk_percent=0.25,
        )
    )

    class Config:
        risk_per_trade_percent = 0.5

    assert adjuster(
        Config(),
        [],
        "BUY",
    ) == 0.5


def test_short_history_conjunction_retains_risk():
    adjuster = (
        create_conjunction_adjuster(
            threshold=0.8174,
            frozen_groups=[
                [
                    "TRENDING_UP",
                    "NORMAL",
                    "BUY",
                ]
            ],
            reduced_risk_percent=0.25,
        )
    )

    class Config:
        risk_per_trade_percent = 0.5

    assert adjuster(
        Config(),
        [],
        "BUY",
    ) == 0.5


def test_committed_frozen_inputs_verify():
    protocol_path = Path(
        "research_protocols/"
        "untouched_cross_market_validation_protocol.json"
    )

    manifest_path = Path(
        "research_protocols/"
        "untouched_market_data_manifest.json"
    )

    protocol = json.loads(
        protocol_path.read_text()
    )

    manifest = json.loads(
        manifest_path.read_text()
    )

    verify_frozen_inputs(
        protocol,
        manifest,
    )

    for dataset in manifest["datasets"]:
        assert sha256_file(
            Path(dataset["file"])
        ) == dataset["sha256"]
