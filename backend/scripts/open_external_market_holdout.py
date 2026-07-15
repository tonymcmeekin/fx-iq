from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.ai.external_validation import (
    EXPECTED_SHA256,
    EXTERNAL_MARKETS,
    HOLDOUT_START,
    PROTOCOL_FREEZE_COMMIT,
    PROTOCOL_VERSION,
)
from app.ai.readiness import (
    ValidationEvidence,
    evaluate_research_readiness,
)
from app.market_data.csv_loader import load_candles_from_csv
from scripts.adaptive_regime_policy_walk_forward import (
    INITIAL_BALANCE,
    profit_factor,
    run_test_fold,
)
from scripts.guarded_adaptive_policy_walk_forward import (
    BASELINE_STRATEGY,
    choose_guarded_policy,
    evaluate_training_candidates,
)


MARKER_FILE = Path(
    "validation/external_holdout_opened.json"
)

RESULT_FILE = Path(
    "validation/external_holdout_results.json"
)

KNOWN_DEVELOPMENT_RESULTS = {
    "EUR_USD": {
        "return": 0.23,
        "baseline_return": 1.67,
        "drawdown": 3.19,
        "baseline_drawdown": 5.16,
        "trades": 66,
    },
    "GBP_USD": {
        "return": -0.28,
        "baseline_return": -11.17,
        "drawdown": 3.78,
        "baseline_drawdown": 6.38,
        "trades": 75,
    },
    "AUD_USD": {
        "return": -0.09,
        "baseline_return": -0.09,
        "drawdown": 4.58,
        "baseline_drawdown": 4.58,
        "trades": 121,
    },
}


def current_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        text=True,
    ).strip()


def file_sha256(path: Path) -> str:
    digest = sha256()

    with path.open("rb") as file:
        for chunk in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def validate_dataset(
    symbol: str,
    path: Path,
) -> list:
    actual_hash = file_sha256(path)
    expected_hash = EXPECTED_SHA256[symbol]

    if actual_hash != expected_hash:
        raise RuntimeError(
            f"{symbol} checksum mismatch. "
            "The frozen dataset has changed."
        )

    candles = load_candles_from_csv(path)

    symbols = {
        candle.symbol
        for candle in candles
    }

    if symbols != {symbol}:
        raise RuntimeError(
            f"{symbol} contains unexpected symbols: "
            f"{sorted(symbols)}"
        )

    return candles


def run_holdout_market(
    symbol: str,
    candles,
) -> dict:
    training_candles = [
        candle
        for candle in candles
        if candle.timestamp < HOLDOUT_START
    ]

    holdout_candles = [
        candle
        for candle in candles
        if candle.timestamp >= HOLDOUT_START
    ]

    if not training_candles:
        raise RuntimeError(
            f"{symbol} has no training candles."
        )

    if not holdout_candles:
        raise RuntimeError(
            f"{symbol} has no holdout candles."
        )

    candidates = evaluate_training_candidates(
        symbol=symbol,
        training_candles=training_candles,
    )

    selected_policy, reason = choose_guarded_policy(
        candidates
    )

    guarded_result = run_test_fold(
        symbol=symbol,
        candles=candles,
        strategy_name=selected_policy,
        fold_start=HOLDOUT_START,
        fold_end=candles[-1].timestamp,
        starting_balance=INITIAL_BALANCE,
    )

    baseline_result = run_test_fold(
        symbol=symbol,
        candles=candles,
        strategy_name=BASELINE_STRATEGY,
        fold_start=HOLDOUT_START,
        fold_end=candles[-1].timestamp,
        starting_balance=INITIAL_BALANCE,
    )

    guarded_return = (
        guarded_result.final_balance
        / INITIAL_BALANCE
        - 1
    ) * 100

    baseline_return = (
        baseline_result.final_balance
        / INITIAL_BALANCE
        - 1
    ) * 100

    return {
        "symbol": symbol,
        "training_candles": len(training_candles),
        "holdout_candles": len(holdout_candles),
        "holdout_start": (
            holdout_candles[0].timestamp.isoformat()
        ),
        "holdout_end": (
            holdout_candles[-1].timestamp.isoformat()
        ),
        "selected_policy": selected_policy,
        "selection_reason": reason,
        "guarded_trades": guarded_result.total_trades,
        "guarded_return": guarded_return,
        "guarded_profit_factor": profit_factor(
            guarded_result.trades
        ),
        "guarded_drawdown": (
            guarded_result.max_drawdown_percent
        ),
        "baseline_trades": baseline_result.total_trades,
        "baseline_return": baseline_return,
        "baseline_profit_factor": profit_factor(
            baseline_result.trades
        ),
        "baseline_drawdown": (
            baseline_result.max_drawdown_percent
        ),
    }


def readiness_from_all_markets(
    holdout_results: list[dict],
):
    all_results = list(
        KNOWN_DEVELOPMENT_RESULTS.values()
    )

    all_results.extend(
        {
            "return": item["guarded_return"],
            "baseline_return": item["baseline_return"],
            "drawdown": item["guarded_drawdown"],
            "baseline_drawdown": (
                item["baseline_drawdown"]
            ),
            "trades": item["guarded_trades"],
        }
        for item in holdout_results
    )

    evidence = ValidationEvidence(
        markets_tested=len(all_results),
        profitable_markets=sum(
            item["return"] > 0
            for item in all_results
        ),
        markets_beating_baseline=sum(
            item["return"]
            > item["baseline_return"]
            for item in all_results
        ),
        markets_with_lower_drawdown=sum(
            item["drawdown"]
            < item["baseline_drawdown"]
            for item in all_results
        ),
        total_out_of_sample_trades=sum(
            item["trades"]
            for item in all_results
        ),
        combined_return_percent=sum(
            item["return"]
            for item in all_results
        ),
        worst_market_return_percent=min(
            item["return"]
            for item in all_results
        ),
        maximum_drawdown_percent=max(
            item["drawdown"]
            for item in all_results
        ),
        untouched_holdout_tested=True,
        external_markets_tested=True,
    )

    return (
        evidence,
        evaluate_research_readiness(evidence),
    )


def main() -> None:
    if MARKER_FILE.exists():
        raise RuntimeError(
            "The external holdout has already been opened."
        )

    repository_commit = current_commit()

    print("TRADE IQ FINAL EXTERNAL HOLDOUT")
    print("=" * 88)
    print("Protocol version:", PROTOCOL_VERSION)
    print(
        "Protocol strategy freeze:",
        PROTOCOL_FREEZE_COMMIT,
    )
    print(
        "Repository commit at opening:",
        repository_commit,
    )
    print(
        "Holdout boundary:",
        HOLDOUT_START.isoformat(),
    )
    print(
        "This is the single permitted opening of the "
        "external holdout."
    )

    holdout_results = []

    for symbol, path in EXTERNAL_MARKETS.items():
        candles = validate_dataset(symbol, path)

        result = run_holdout_market(
            symbol=symbol,
            candles=candles,
        )

        holdout_results.append(result)

        print()
        print("=" * 88)
        print(symbol)
        print("=" * 88)
        print(
            "Frozen policy:",
            result["selected_policy"],
        )
        print(
            "Selection:",
            result["selection_reason"],
        )
        print(
            "Holdout:",
            result["holdout_start"],
            "to",
            result["holdout_end"],
        )
        print(
            "Guarded | "
            f"Trades {result['guarded_trades']:3d} | "
            f"Return {result['guarded_return']:7.2f}% | "
            f"PF "
            f"{result['guarded_profit_factor']:6.3f} | "
            f"DD {result['guarded_drawdown']:5.2f}%"
        )
        print(
            "Baseline | "
            f"Trades {result['baseline_trades']:3d} | "
            f"Return {result['baseline_return']:7.2f}% | "
            f"PF "
            f"{result['baseline_profit_factor']:6.3f} | "
            f"DD {result['baseline_drawdown']:5.2f}%"
        )
        print(
            "Return difference:",
            round(
                result["guarded_return"]
                - result["baseline_return"],
                2,
            ),
            "percentage points",
        )

    evidence, readiness = readiness_from_all_markets(
        holdout_results
    )

    profitable_holdouts = sum(
        result["guarded_return"] > 0
        for result in holdout_results
    )

    beating_baseline = sum(
        result["guarded_return"]
        > result["baseline_return"]
        for result in holdout_results
    )

    holdout_return_sum = sum(
        result["guarded_return"]
        for result in holdout_results
    )

    holdout_baseline_sum = sum(
        result["baseline_return"]
        for result in holdout_results
    )

    print()
    print("=" * 88)
    print("FINAL EXTERNAL HOLDOUT SUMMARY")
    print("=" * 88)
    print(
        "Profitable holdout markets:",
        profitable_holdouts,
        "/ 3",
    )
    print(
        "Holdout markets beating baseline:",
        beating_baseline,
        "/ 3",
    )
    print(
        "Sum of guarded holdout returns:",
        round(holdout_return_sum, 2),
        "%",
    )
    print(
        "Sum of baseline holdout returns:",
        round(holdout_baseline_sum, 2),
        "%",
    )
    print(
        "Total holdout trades:",
        sum(
            result["guarded_trades"]
            for result in holdout_results
        ),
    )

    print()
    print("=" * 88)
    print("SIX-MARKET READINESS ASSESSMENT")
    print("=" * 88)
    print(
        "Markets tested:",
        evidence.markets_tested,
    )
    print(
        "Profitable markets:",
        evidence.profitable_markets,
    )
    print(
        "Markets beating baseline:",
        evidence.markets_beating_baseline,
    )
    print(
        "Markets lowering drawdown:",
        evidence.markets_with_lower_drawdown,
    )
    print(
        "Total out-of-sample trades:",
        evidence.total_out_of_sample_trades,
    )
    print(
        "Combined market returns:",
        round(
            evidence.combined_return_percent,
            2,
        ),
        "%",
    )
    print(
        "Worst market return:",
        round(
            evidence.worst_market_return_percent,
            2,
        ),
        "%",
    )
    print(
        "Maximum drawdown:",
        round(
            evidence.maximum_drawdown_percent,
            2,
        ),
        "%",
    )
    print()
    print("READINESS STATUS:", readiness.status)
    print("Reason:", readiness.reason)

    print()
    print("FAILED READINESS CHECKS")
    print("-" * 88)

    if readiness.failed_checks:
        for check in readiness.failed_checks:
            print("FAIL:", check)
    else:
        print("NONE")

    opened_at = datetime.now(UTC).isoformat()

    result_payload = {
        "protocol_version": PROTOCOL_VERSION,
        "protocol_freeze_commit": (
            PROTOCOL_FREEZE_COMMIT
        ),
        "repository_commit_at_opening": (
            repository_commit
        ),
        "opened_at": opened_at,
        "holdout_start": HOLDOUT_START.isoformat(),
        "markets": holdout_results,
        "evidence": evidence.model_dump(
            mode="json"
        ),
        "readiness": readiness.model_dump(
            mode="json"
        ),
    }

    RESULT_FILE.write_text(
        json.dumps(
            result_payload,
            indent=2,
        )
        + "\n"
    )

    marker_payload = {
        "opened": True,
        "opened_at": opened_at,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_freeze_commit": (
            PROTOCOL_FREEZE_COMMIT
        ),
        "repository_commit_at_opening": (
            repository_commit
        ),
        "results_file": str(RESULT_FILE),
        "post_holdout_tuning_prohibited": True,
    }

    MARKER_FILE.write_text(
        json.dumps(
            marker_payload,
            indent=2,
        )
        + "\n"
    )

    print()
    print("=" * 88)
    print("HOLDOUT OPENING RECORDED")
    print("=" * 88)
    print("Marker:", MARKER_FILE)
    print("Results:", RESULT_FILE)
    print(
        "The holdout must not be reused for parameter "
        "or policy tuning."
    )


if __name__ == "__main__":
    main()
