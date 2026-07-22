import hashlib
import json
from pathlib import Path

MANIFEST_PATH = Path(
    "research_protocols/"
    "untouched_market_data_manifest.json"
)

PROTOCOL_PATH = Path(
    "research_protocols/"
    "untouched_cross_market_validation_protocol.json"
)


def load_json(path: Path) -> dict:
    return json.loads(
        path.read_text()
    )


def test_manifest_is_frozen_and_unexamined():
    manifest = load_json(
        MANIFEST_PATH
    )

    assert manifest["status"] == (
        "FROZEN_UNEXAMINED"
    )

    assert (
        manifest["strategy_results_viewed"]
        is False
    )

    assert (
        manifest[
            "external_post_2024_holdout_reused"
        ]
        is False
    )


def test_all_frozen_dataset_hashes_match():
    manifest = load_json(
        MANIFEST_PATH
    )

    assert len(
        manifest["datasets"]
    ) == 6

    for dataset in manifest["datasets"]:
        path = Path(
            dataset["file"]
        )

        actual_hash = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

        assert actual_hash == (
            dataset["sha256"]
        )


def test_protocol_is_preregistered_not_run():
    protocol = load_json(
        PROTOCOL_PATH
    )

    assert protocol["status"] == (
        "PREREGISTERED_NOT_RUN"
    )

    assert (
        protocol[
            "previous_post_2024_holdout_reused"
        ]
        is False
    )


def test_protocol_uses_six_untouched_markets():
    protocol = load_json(
        PROTOCOL_PATH
    )

    assert protocol[
        "untouched_validation_markets"
    ] == [
        "EUR_GBP",
        "EUR_JPY",
        "GBP_JPY",
        "AUD_JPY",
        "CAD_JPY",
        "AUD_CAD",
    ]


def test_primary_policy_is_frozen():
    protocol = load_json(
        PROTOCOL_PATH
    )

    primary = protocol[
        "primary_candidate"
    ]

    assert primary[
        "frozen_directional_close_location_threshold"
    ] == 0.8174

    assert primary[
        "normal_risk_percent"
    ] == 0.5

    assert primary[
        "reduced_risk_percent"
    ] == 0.25

    assert (
        primary[
            "trade_selection_changed"
        ]
        is False
    )


def test_secondary_policy_is_frozen():
    protocol = load_json(
        PROTOCOL_PATH
    )

    secondary = protocol[
        "secondary_candidate"
    ]

    assert secondary[
        "frozen_directional_close_location_threshold"
    ] == 0.8174

    assert secondary[
        "frozen_regime_groups"
    ] == [
        [
            "RANGING",
            "NORMAL",
            "BUY",
        ],
        [
            "TRENDING_UP",
            "NORMAL",
            "BUY",
        ],
    ]

    assert secondary[
        "normal_risk_percent"
    ] == 0.5

    assert secondary[
        "reduced_risk_percent"
    ] == 0.25


def test_primary_pass_criteria_are_strict():
    protocol = load_json(
        PROTOCOL_PATH
    )

    criteria = protocol[
        "primary_pass_criteria"
    ]

    assert criteria[
        "all_required"
    ] is True

    assert criteria[
        "markets_beating_fixed_at_least"
    ] == 4

    assert criteria[
        "chronological_folds_beating_fixed_at_least"
    ] == 4

    assert criteria[
        "markets_with_lower_worst_drawdown_at_least"
    ] == 3

    assert criteria[
        "candidate_aggregate_return_must_be_positive"
    ] is True

    assert criteria[
        "trade_count_must_equal_fixed"
    ] is True

    assert criteria[
        "trade_sequence_must_equal_fixed"
    ] is True


def test_exploratory_regime_policy_cannot_validate():
    protocol = load_json(
        PROTOCOL_PATH
    )

    comparator = protocol[
        "exploratory_comparator"
    ]

    assert (
        comparator[
            "eligible_for_validation_claim"
        ]
        is False
    )
