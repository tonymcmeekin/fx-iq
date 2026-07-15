from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.ai.readiness import (
    ValidationEvidence,
    evaluate_research_readiness,
)


def main() -> None:
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

    print("TRADE IQ AI RESEARCH READINESS")
    print("=" * 72)
    print("Status:", decision.status)
    print("Reason:", decision.reason)

    print()
    print("PASSED CHECKS")
    print("-" * 72)

    for check in decision.passed_checks:
        print("PASS:", check)

    print()
    print("FAILED CHECKS")
    print("-" * 72)

    for check in decision.failed_checks:
        print("FAIL:", check)

    print()
    print("CURRENT DECISION")
    print("-" * 72)

    if decision.status == "RESEARCH_ONLY":
        print(
            "Do not promote this strategy to paper or live "
            "trading."
        )
        print(
            "Next requirement: test frozen logic on additional "
            "markets and a genuinely untouched holdout."
        )
    else:
        print(
            "Eligible for controlled paper-trading evaluation "
            "only."
        )


if __name__ == "__main__":
    main()
