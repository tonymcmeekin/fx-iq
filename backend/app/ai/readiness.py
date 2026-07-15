from typing import Literal

from pydantic import BaseModel, Field


ReadinessStatus = Literal[
    "RESEARCH_ONLY",
    "PAPER_TRADING_CANDIDATE",
]


class ValidationEvidence(BaseModel):
    markets_tested: int = Field(ge=0)
    profitable_markets: int = Field(ge=0)
    markets_beating_baseline: int = Field(ge=0)
    markets_with_lower_drawdown: int = Field(ge=0)
    total_out_of_sample_trades: int = Field(ge=0)
    combined_return_percent: float
    worst_market_return_percent: float
    maximum_drawdown_percent: float = Field(ge=0)
    untouched_holdout_tested: bool
    external_markets_tested: bool


class ReadinessDecision(BaseModel):
    status: ReadinessStatus
    passed_checks: list[str]
    failed_checks: list[str]
    reason: str


def evaluate_research_readiness(
    evidence: ValidationEvidence,
) -> ReadinessDecision:
    checks = {
        "At least five markets tested": (
            evidence.markets_tested >= 5
        ),
        "A majority of markets are profitable": (
            evidence.markets_tested > 0
            and evidence.profitable_markets
            > evidence.markets_tested / 2
        ),
        "A majority of markets beat the baseline": (
            evidence.markets_tested > 0
            and evidence.markets_beating_baseline
            > evidence.markets_tested / 2
        ),
        "A majority of markets reduce drawdown": (
            evidence.markets_tested > 0
            and evidence.markets_with_lower_drawdown
            > evidence.markets_tested / 2
        ),
        "At least 300 out-of-sample trades": (
            evidence.total_out_of_sample_trades >= 300
        ),
        "Combined out-of-sample return is positive": (
            evidence.combined_return_percent > 0
        ),
        "No market loses more than five percent": (
            evidence.worst_market_return_percent > -5
        ),
        "Maximum drawdown is below ten percent": (
            evidence.maximum_drawdown_percent < 10
        ),
        "An untouched final holdout was tested": (
            evidence.untouched_holdout_tested
        ),
        "Additional external markets were tested": (
            evidence.external_markets_tested
        ),
    }

    passed_checks = [
        name
        for name, passed in checks.items()
        if passed
    ]

    failed_checks = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    if not failed_checks:
        return ReadinessDecision(
            status="PAPER_TRADING_CANDIDATE",
            passed_checks=passed_checks,
            failed_checks=[],
            reason=(
                "All minimum research-validation requirements "
                "were satisfied. This permits controlled paper "
                "trading only, not live trading."
            ),
        )

    return ReadinessDecision(
        status="RESEARCH_ONLY",
        passed_checks=passed_checks,
        failed_checks=failed_checks,
        reason=(
            "The evidence is not broad or independent enough "
            "for paper-trading promotion."
        ),
    )
