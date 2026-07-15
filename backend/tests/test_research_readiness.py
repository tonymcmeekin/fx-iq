from app.ai.readiness import (
    ValidationEvidence,
    evaluate_research_readiness,
)


def strong_evidence() -> ValidationEvidence:
    return ValidationEvidence(
        markets_tested=6,
        profitable_markets=4,
        markets_beating_baseline=4,
        markets_with_lower_drawdown=5,
        total_out_of_sample_trades=500,
        combined_return_percent=8.0,
        worst_market_return_percent=-2.0,
        maximum_drawdown_percent=6.0,
        untouched_holdout_tested=True,
        external_markets_tested=True,
    )


def test_strong_independent_evidence_is_candidate():
    decision = evaluate_research_readiness(
        strong_evidence()
    )

    assert decision.status == "PAPER_TRADING_CANDIDATE"
    assert decision.failed_checks == []


def test_current_three_market_result_is_research_only():
    evidence = ValidationEvidence(
        markets_tested=3,
        profitable_markets=1,
        markets_beating_baseline=1,
        markets_with_lower_drawdown=2,
        total_out_of_sample_trades=262,
        combined_return_percent=-0.14,
        worst_market_return_percent=-0.28,
        maximum_drawdown_percent=4.58,
        untouched_holdout_tested=False,
        external_markets_tested=False,
    )

    decision = evaluate_research_readiness(evidence)

    assert decision.status == "RESEARCH_ONLY"
    assert "At least five markets tested" in (
        decision.failed_checks
    )
    assert (
        "Combined out-of-sample return is positive"
        in decision.failed_checks
    )


def test_requires_majority_profitable_markets():
    evidence = strong_evidence().model_copy(
        update={
            "profitable_markets": 3,
        }
    )

    decision = evaluate_research_readiness(evidence)

    assert decision.status == "RESEARCH_ONLY"
    assert (
        "A majority of markets are profitable"
        in decision.failed_checks
    )


def test_requires_untouched_holdout():
    evidence = strong_evidence().model_copy(
        update={
            "untouched_holdout_tested": False,
        }
    )

    decision = evaluate_research_readiness(evidence)

    assert decision.status == "RESEARCH_ONLY"
    assert (
        "An untouched final holdout was tested"
        in decision.failed_checks
    )


def test_requires_external_market_validation():
    evidence = strong_evidence().model_copy(
        update={
            "external_markets_tested": False,
        }
    )

    decision = evaluate_research_readiness(evidence)

    assert decision.status == "RESEARCH_ONLY"
    assert (
        "Additional external markets were tested"
        in decision.failed_checks
    )


def test_requires_minimum_trade_count():
    evidence = strong_evidence().model_copy(
        update={
            "total_out_of_sample_trades": 299,
        }
    )

    decision = evaluate_research_readiness(evidence)

    assert decision.status == "RESEARCH_ONLY"
    assert (
        "At least 300 out-of-sample trades"
        in decision.failed_checks
    )
