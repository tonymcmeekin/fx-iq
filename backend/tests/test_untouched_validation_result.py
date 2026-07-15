import hashlib
import json
from pathlib import Path


RESULTS_PATH = Path(
    "research_results/"
    "untouched_cross_market_validation_results.json"
)

OUTCOME_PATH = Path(
    "research_results/"
    "untouched_cross_market_validation_outcome.json"
)

EXPECTED_RESULTS_HASH = (
    "50964f9e746310442db6447984e8d187"
    "41231620b39c3add3e3720d412aa53b9"
)


def test_one_time_result_hash_is_preserved():
    assert RESULTS_PATH.exists()

    actual_hash = hashlib.sha256(
        RESULTS_PATH.read_bytes()
    ).hexdigest()

    assert actual_hash == EXPECTED_RESULTS_HASH


def test_primary_candidate_passed():
    results = json.loads(
        RESULTS_PATH.read_text()
    )

    assert results[
        "overall_status"
    ]["primary"] == "PASSED"

    assert results[
        "primary"
    ]["evaluation"]["passed"] is True

    assert all(
        results[
            "primary"
        ]["evaluation"]["checks"].values()
    )


def test_secondary_candidate_failed():
    results = json.loads(
        RESULTS_PATH.read_text()
    )

    assert results[
        "overall_status"
    ]["secondary"] == "FAILED"

    checks = results[
        "secondary"
    ]["evaluation"]["checks"]

    assert (
        checks[
            "markets_lowering_drawdown"
        ]
        is False
    )


def test_outcome_record_matches_result_hash():
    outcome = json.loads(
        OUTCOME_PATH.read_text()
    )

    assert outcome[
        "results_sha256"
    ] == EXPECTED_RESULTS_HASH

    assert outcome[
        "execution_status"
    ] == "COMPLETED_ONCE"

    assert outcome[
        "primary_candidate"
    ]["status"] == "PASSED"

    assert outcome[
        "next_research_stage"
    ] == "prospective_paper_trading"
