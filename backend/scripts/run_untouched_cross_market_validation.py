import hashlib
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.ai.regime import detect_market_regime
from app.market_data.csv_loader import (
    load_candles_from_csv,
)
from app.portfolio.engine import (
    run_portfolio_backtest,
)
from scripts.adaptive_regime_policy_walk_forward import (
    FOLDS,
    end_timestamp,
    profit_factor,
    start_timestamp,
    strategy_config,
)
from scripts.nested_close_location_risk_walk_forward import (
    signal_features,
)


PROTOCOL_PATH = Path(
    "research_protocols/"
    "untouched_cross_market_validation_protocol.json"
)

MANIFEST_PATH = Path(
    "research_protocols/"
    "untouched_market_data_manifest.json"
)

RESULTS_PATH = Path(
    "research_results/"
    "untouched_cross_market_validation_results.json"
)

CONSOLE_RESULTS_PATH = Path(
    "untouched_cross_market_validation_console.txt"
)

REGIME_LOOKBACK = 50


def load_json(path: Path) -> dict:
    return json.loads(
        path.read_text()
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def verify_frozen_inputs(
    protocol: dict,
    manifest: dict,
) -> None:
    if protocol["status"] != (
        "PREREGISTERED_NOT_RUN"
    ):
        raise RuntimeError(
            "Validation protocol is not marked "
            "PREREGISTERED_NOT_RUN."
        )

    if manifest["status"] != (
        "FROZEN_UNEXAMINED"
    ):
        raise RuntimeError(
            "Dataset manifest is not marked "
            "FROZEN_UNEXAMINED."
        )

    if manifest["strategy_results_viewed"]:
        raise RuntimeError(
            "Manifest says validation results "
            "were already viewed."
        )

    if protocol[
        "previous_post_2024_holdout_reused"
    ]:
        raise RuntimeError(
            "Protocol permits reuse of the "
            "previous post-2024 holdout."
        )

    protocol_markets = protocol[
        "untouched_validation_markets"
    ]

    manifest_markets = [
        dataset["instrument"]
        for dataset in manifest["datasets"]
    ]

    if protocol_markets != manifest_markets:
        raise RuntimeError(
            "Protocol and manifest market order "
            "do not match."
        )

    for dataset in manifest["datasets"]:
        path = Path(dataset["file"])

        if not path.exists():
            raise RuntimeError(
                f"Missing frozen dataset: {path}"
            )

        actual_hash = sha256_file(path)

        if actual_hash != dataset["sha256"]:
            raise RuntimeError(
                f"Frozen dataset hash mismatch: {path}"
            )


def make_strategy_config(
    symbol: str,
    protocol: dict,
):
    configuration = protocol[
        "common_strategy_configuration"
    ]

    config = strategy_config(
        configuration["strategy_name"],
        symbol,
    )

    expected = {
        "stop_loss_percent": configuration[
            "stop_loss_percent"
        ],
        "take_profit_percent": configuration[
            "take_profit_percent"
        ],
        "risk_per_trade_percent": configuration[
            "base_risk_per_trade_percent"
        ],
        "spread_pips": configuration[
            "spread_pips"
        ],
        "slippage_pips": configuration[
            "slippage_pips"
        ],
    }

    for field, expected_value in expected.items():
        actual_value = getattr(
            config,
            field,
        )

        if actual_value != expected_value:
            raise RuntimeError(
                f"Strategy configuration mismatch "
                f"for {field}: expected "
                f"{expected_value}, found "
                f"{actual_value}."
            )

    return config


def create_close_location_adjuster(
    threshold: float,
    reduced_risk_percent: float,
):
    def adjuster(
        config,
        historical_candles,
        direction,
    ) -> float:
        features = signal_features(
            historical_candles,
            direction,
        )

        if features is None:
            return config.risk_per_trade_percent

        close_location = float(
            features[
                "directional_close_location"
            ]
        )

        if close_location > threshold:
            return config.risk_per_trade_percent

        return reduced_risk_percent

    return adjuster


def create_regime_adjuster(
    frozen_groups,
    reduced_risk_percent: float,
):
    reduced_groups = {
        tuple(group)
        for group in frozen_groups
    }

    def adjuster(
        config,
        historical_candles,
        direction,
    ) -> float:
        if len(historical_candles) < (
            REGIME_LOOKBACK
        ):
            return config.risk_per_trade_percent

        try:
            regime = detect_market_regime(
                historical_candles,
                lookback=REGIME_LOOKBACK,
            )
        except ValueError:
            return config.risk_per_trade_percent

        key = (
            regime.trend,
            regime.volatility,
            direction,
        )

        if key not in reduced_groups:
            return config.risk_per_trade_percent

        return reduced_risk_percent

    return adjuster


def create_conjunction_adjuster(
    threshold: float,
    frozen_groups,
    reduced_risk_percent: float,
):
    reduced_groups = {
        tuple(group)
        for group in frozen_groups
    }

    def adjuster(
        config,
        historical_candles,
        direction,
    ) -> float:
        features = signal_features(
            historical_candles,
            direction,
        )

        if features is None:
            return config.risk_per_trade_percent

        close_location = float(
            features[
                "directional_close_location"
            ]
        )

        if close_location > threshold:
            return config.risk_per_trade_percent

        if len(historical_candles) < (
            REGIME_LOOKBACK
        ):
            return config.risk_per_trade_percent

        try:
            regime = detect_market_regime(
                historical_candles,
                lookback=REGIME_LOOKBACK,
            )
        except ValueError:
            return config.risk_per_trade_percent

        key = (
            regime.trend,
            regime.volatility,
            direction,
        )

        if key not in reduced_groups:
            return config.risk_per_trade_percent

        return reduced_risk_percent

    return adjuster


def run_fold(
    *,
    symbol: str,
    candles,
    fold_start,
    fold_end,
    starting_balance: float,
    protocol: dict,
    risk_adjuster=None,
):
    available = [
        candle
        for candle in candles
        if candle.timestamp <= fold_end
    ]

    configuration = protocol[
        "common_strategy_configuration"
    ]

    arguments = {
        "candles_by_symbol": {
            symbol: available,
        },
        "strategy_configs": [
            make_strategy_config(
                symbol,
                protocol,
            )
        ],
        "initial_balance": starting_balance,
        "max_portfolio_leverage": configuration[
            "max_portfolio_leverage"
        ],
        "max_total_risk_percent": configuration[
            "max_total_risk_percent"
        ],
        "trading_start_timestamp": fold_start,
    }

    if risk_adjuster is not None:
        arguments[
            "risk_percent_adjuster"
        ] = risk_adjuster

    return run_portfolio_backtest(
        **arguments
    )


def fold_return(
    result,
    starting_balance: float,
) -> float:
    return (
        result.final_balance
        / starting_balance
        - 1
    ) * 100


def trade_sequence(result) -> list[tuple]:
    return [
        (
            trade.signal_timestamp,
            trade.entry_timestamp,
            trade.direction,
        )
        for trade in result.trades
    ]


def assert_identical_trade_sequence(
    fixed_result,
    candidate_result,
    *,
    symbol: str,
    fold_number: int,
    policy_name: str,
) -> None:
    if (
        fixed_result.total_trades
        != candidate_result.total_trades
    ):
        raise RuntimeError(
            f"{symbol} fold {fold_number}: "
            f"{policy_name} changed trade count."
        )

    if (
        trade_sequence(fixed_result)
        != trade_sequence(candidate_result)
    ):
        raise RuntimeError(
            f"{symbol} fold {fold_number}: "
            f"{policy_name} changed trade sequence."
        )


def estimated_risk_percentages(
    result,
    starting_balance: float,
) -> list[float]:
    balance = starting_balance
    percentages = []

    for trade in result.trades:
        if balance > 0:
            percentages.append(
                trade.risk_amount
                / balance
                * 100
            )

        balance += trade.net_pnl

    return percentages


def count_reduced_trades(
    result,
    starting_balance: float,
    base_risk_percent: float,
) -> int:
    return sum(
        risk_percent
        < base_risk_percent - 0.01
        for risk_percent
        in estimated_risk_percentages(
            result,
            starting_balance,
        )
    )


def evaluate_candidate(
    summary: dict,
    criteria: dict,
) -> dict:
    checks = {
        "aggregate_improvement": (
            summary[
                "aggregate_improvement_pp"
            ]
            > criteria[
                "aggregate_return_improvement_over_fixed_percentage_points_greater_than"
            ]
        ),
        "markets_beating_fixed": (
            summary[
                "markets_beating_fixed"
            ]
            >= criteria[
                "markets_beating_fixed_at_least"
            ]
        ),
        "folds_beating_fixed": (
            summary[
                "folds_beating_fixed"
            ]
            >= criteria[
                "chronological_folds_beating_fixed_at_least"
            ]
        ),
        "markets_lowering_drawdown": (
            summary[
                "markets_lowering_worst_drawdown"
            ]
            >= criteria[
                "markets_with_lower_worst_drawdown_at_least"
            ]
        ),
        "profitable_candidate_markets": (
            summary[
                "profitable_markets"
            ]
            >= criteria[
                "profitable_candidate_markets_at_least"
            ]
        ),
        "trade_count_equal": (
            summary["trade_count_equal"]
            is True
        ),
        "trade_sequence_equal": (
            summary["trade_sequence_equal"]
            is True
        ),
        "positive_aggregate_return": (
            summary[
                "candidate_aggregate_return"
            ]
            > 0
        ),
    }

    return {
        "checks": checks,
        "passed": all(
            checks.values()
        ),
    }


def build_candidate_summary(
    *,
    policy_name: str,
    market_results: dict,
    fold_results: list[dict],
) -> dict:
    fixed_aggregate_return = sum(
        details["fixed_return"]
        for details in market_results.values()
    )

    candidate_aggregate_return = sum(
        details["candidate_return"]
        for details in market_results.values()
    )

    return {
        "policy_name": policy_name,
        "fixed_aggregate_return": (
            fixed_aggregate_return
        ),
        "candidate_aggregate_return": (
            candidate_aggregate_return
        ),
        "aggregate_improvement_pp": (
            candidate_aggregate_return
            - fixed_aggregate_return
        ),
        "markets_beating_fixed": sum(
            details["candidate_return"]
            > details["fixed_return"]
            for details in market_results.values()
        ),
        "markets_lowering_worst_drawdown": sum(
            details[
                "candidate_worst_drawdown"
            ]
            < details[
                "fixed_worst_drawdown"
            ]
            for details in market_results.values()
        ),
        "profitable_markets": sum(
            details["candidate_return"] > 0
            for details in market_results.values()
        ),
        "folds_beating_fixed": sum(
            fold["candidate_return_sum"]
            > fold["fixed_return_sum"]
            for fold in fold_results
        ),
        "total_trades": sum(
            details["trades"]
            for details in market_results.values()
        ),
        "reduced_trades": sum(
            details["reduced_trades"]
            for details in market_results.values()
        ),
        "trade_count_equal": True,
        "trade_sequence_equal": True,
    }


def run_policy(
    *,
    policy_name: str,
    risk_adjuster,
    candles_by_market: dict,
    protocol: dict,
) -> dict:
    initial_balance = protocol[
        "common_strategy_configuration"
    ][
        "initial_balance_per_market"
    ]

    base_risk_percent = protocol[
        "common_strategy_configuration"
    ][
        "base_risk_per_trade_percent"
    ]

    fixed_balances = {
        symbol: initial_balance
        for symbol in candles_by_market
    }

    candidate_balances = {
        symbol: initial_balance
        for symbol in candles_by_market
    }

    market_results = {
        symbol: {
            "fixed_return": 0.0,
            "candidate_return": 0.0,
            "fixed_worst_drawdown": 0.0,
            "candidate_worst_drawdown": 0.0,
            "trades": 0,
            "reduced_trades": 0,
            "folds": [],
        }
        for symbol in candles_by_market
    }

    fold_results = []

    print()
    print("=" * 132)
    print(policy_name.upper())
    print("=" * 132)

    for fold_number, (
        start_text,
        end_text,
    ) in enumerate(
        FOLDS[:6],
        start=1,
    ):
        fold_start = start_timestamp(
            start_text
        )
        fold_end = end_timestamp(
            end_text
        )

        fixed_return_sum = 0.0
        candidate_return_sum = 0.0
        fold_reduced_trades = 0

        print()
        print(
            f"FOLD {fold_number}: "
            f"{start_text} to {end_text}"
        )
        print("-" * 132)

        for symbol, candles in (
            candles_by_market.items()
        ):
            fixed_start = fixed_balances[
                symbol
            ]
            candidate_start = (
                candidate_balances[symbol]
            )

            fixed_result = run_fold(
                symbol=symbol,
                candles=candles,
                fold_start=fold_start,
                fold_end=fold_end,
                starting_balance=fixed_start,
                protocol=protocol,
            )

            candidate_result = run_fold(
                symbol=symbol,
                candles=candles,
                fold_start=fold_start,
                fold_end=fold_end,
                starting_balance=candidate_start,
                protocol=protocol,
                risk_adjuster=risk_adjuster,
            )

            assert_identical_trade_sequence(
                fixed_result,
                candidate_result,
                symbol=symbol,
                fold_number=fold_number,
                policy_name=policy_name,
            )

            fixed_fold_return = fold_return(
                fixed_result,
                fixed_start,
            )

            candidate_fold_return = (
                fold_return(
                    candidate_result,
                    candidate_start,
                )
            )

            reduced_trades = (
                count_reduced_trades(
                    candidate_result,
                    candidate_start,
                    base_risk_percent,
                )
            )

            fixed_balances[
                symbol
            ] = fixed_result.final_balance

            candidate_balances[
                symbol
            ] = (
                candidate_result.final_balance
            )

            details = market_results[
                symbol
            ]

            details[
                "fixed_worst_drawdown"
            ] = max(
                details[
                    "fixed_worst_drawdown"
                ],
                fixed_result.max_drawdown_percent,
            )

            details[
                "candidate_worst_drawdown"
            ] = max(
                details[
                    "candidate_worst_drawdown"
                ],
                candidate_result.max_drawdown_percent,
            )

            details[
                "trades"
            ] += fixed_result.total_trades

            details[
                "reduced_trades"
            ] += reduced_trades

            details["folds"].append(
                {
                    "fold": fold_number,
                    "start": start_text,
                    "end": end_text,
                    "fixed_return": (
                        fixed_fold_return
                    ),
                    "candidate_return": (
                        candidate_fold_return
                    ),
                    "difference_pp": (
                        candidate_fold_return
                        - fixed_fold_return
                    ),
                    "trades": (
                        fixed_result.total_trades
                    ),
                    "reduced_trades": (
                        reduced_trades
                    ),
                    "fixed_drawdown": (
                        fixed_result
                        .max_drawdown_percent
                    ),
                    "candidate_drawdown": (
                        candidate_result
                        .max_drawdown_percent
                    ),
                    "candidate_profit_factor": (
                        profit_factor(
                            candidate_result.trades
                        )
                    ),
                }
            )

            fixed_return_sum += (
                fixed_fold_return
            )

            candidate_return_sum += (
                candidate_fold_return
            )

            fold_reduced_trades += (
                reduced_trades
            )

            print(
                f"{symbol:7s} | "
                f"Fixed {fixed_fold_return:7.2f}% | "
                f"Candidate "
                f"{candidate_fold_return:7.2f}% | "
                f"Difference "
                f"{candidate_fold_return - fixed_fold_return:7.2f}pp | "
                f"Trades "
                f"{fixed_result.total_trades:3d} | "
                f"Reduced {reduced_trades:3d} | "
                f"Fixed DD "
                f"{fixed_result.max_drawdown_percent:5.2f}% | "
                f"Candidate DD "
                f"{candidate_result.max_drawdown_percent:5.2f}% | "
                f"PF "
                f"{profit_factor(candidate_result.trades):6.3f}"
            )

        fold_results.append(
            {
                "fold": fold_number,
                "start": start_text,
                "end": end_text,
                "fixed_return_sum": (
                    fixed_return_sum
                ),
                "candidate_return_sum": (
                    candidate_return_sum
                ),
                "difference_pp": (
                    candidate_return_sum
                    - fixed_return_sum
                ),
                "reduced_trades": (
                    fold_reduced_trades
                ),
            }
        )

        print()
        print(
            f"Fold {fold_number} sum | "
            f"Fixed {fixed_return_sum:.2f}% | "
            f"Candidate "
            f"{candidate_return_sum:.2f}% | "
            f"Difference "
            f"{candidate_return_sum - fixed_return_sum:.2f}pp | "
            f"Reduced {fold_reduced_trades}"
        )

    for symbol, details in (
        market_results.items()
    ):
        details["fixed_return"] = (
            fixed_balances[symbol]
            / initial_balance
            - 1
        ) * 100

        details["candidate_return"] = (
            candidate_balances[symbol]
            / initial_balance
            - 1
        ) * 100

    summary = build_candidate_summary(
        policy_name=policy_name,
        market_results=market_results,
        fold_results=fold_results,
    )

    return {
        "policy_name": policy_name,
        "market_results": market_results,
        "fold_results": fold_results,
        "summary": summary,
    }


def print_policy_summary(
    result: dict,
    evaluation: dict | None,
) -> None:
    print()
    print("=" * 132)
    print(
        result["policy_name"].upper(),
        "MARKET SUMMARY",
    )
    print("=" * 132)

    for symbol, details in (
        result["market_results"].items()
    ):
        print(
            f"{symbol:7s} | "
            f"Fixed "
            f"{details['fixed_return']:7.2f}% | "
            f"Candidate "
            f"{details['candidate_return']:7.2f}% | "
            f"Difference "
            f"{details['candidate_return'] - details['fixed_return']:7.2f}pp | "
            f"Reduced "
            f"{details['reduced_trades']:3d}/"
            f"{details['trades']:3d} | "
            f"Fixed worst DD "
            f"{details['fixed_worst_drawdown']:5.2f}% | "
            f"Candidate worst DD "
            f"{details['candidate_worst_drawdown']:5.2f}%"
        )

    summary = result["summary"]

    print()
    print("=" * 132)
    print("AGGREGATE SUMMARY")
    print("=" * 132)
    print(
        "Fixed aggregate return:",
        round(
            summary[
                "fixed_aggregate_return"
            ],
            2,
        ),
        "%",
    )
    print(
        "Candidate aggregate return:",
        round(
            summary[
                "candidate_aggregate_return"
            ],
            2,
        ),
        "%",
    )
    print(
        "Improvement over fixed:",
        round(
            summary[
                "aggregate_improvement_pp"
            ],
            2,
        ),
        "percentage points",
    )
    print(
        "Markets beating fixed:",
        summary["markets_beating_fixed"],
        "/ 6",
    )
    print(
        "Chronological folds beating fixed:",
        summary["folds_beating_fixed"],
        "/ 6",
    )
    print(
        "Markets lowering worst drawdown:",
        summary[
            "markets_lowering_worst_drawdown"
        ],
        "/ 6",
    )
    print(
        "Profitable candidate markets:",
        summary["profitable_markets"],
        "/ 6",
    )
    print(
        "Trades:",
        summary["total_trades"],
    )
    print(
        "Trades receiving reduced risk:",
        summary["reduced_trades"],
    )

    if evaluation is None:
        print(
            "VALIDATION STATUS: EXPLORATORY_ONLY"
        )
        return

    print()
    print("PREREGISTERED CRITERIA:")

    for name, passed in (
        evaluation["checks"].items()
    ):
        print(
            f" - {name}:",
            "PASS" if passed else "FAIL",
        )

    print()
    print(
        "VALIDATION RESULT:",
        "PASSED"
        if evaluation["passed"]
        else "FAILED",
    )


def main() -> None:
    if RESULTS_PATH.exists():
        raise RuntimeError(
            "Validation results already exist. "
            "This one-time runner will not execute again."
        )

    protocol = load_json(
        PROTOCOL_PATH
    )

    manifest = load_json(
        MANIFEST_PATH
    )

    verify_frozen_inputs(
        protocol,
        manifest,
    )

    print(
        "TRADE IQ ONE-TIME UNTOUCHED "
        "CROSS-MARKET VALIDATION"
    )
    print("=" * 132)
    print(
        "Frozen protocol:",
        PROTOCOL_PATH,
    )
    print(
        "Frozen manifest:",
        MANIFEST_PATH,
    )
    print(
        "No parameters are learned from "
        "the validation markets."
    )
    print(
        "The previously viewed post-2024 "
        "holdout is not accessed."
    )

    candles_by_market = {
        dataset["instrument"]:
        load_candles_from_csv(
            Path(dataset["file"])
        )
        for dataset in manifest["datasets"]
    }

    primary = protocol[
        "primary_candidate"
    ]

    secondary = protocol[
        "secondary_candidate"
    ]

    exploratory = protocol[
        "exploratory_comparator"
    ]

    primary_adjuster = (
        create_close_location_adjuster(
            threshold=primary[
                "frozen_directional_close_location_threshold"
            ],
            reduced_risk_percent=primary[
                "reduced_risk_percent"
            ],
        )
    )

    secondary_adjuster = (
        create_conjunction_adjuster(
            threshold=secondary[
                "frozen_directional_close_location_threshold"
            ],
            frozen_groups=secondary[
                "frozen_regime_groups"
            ],
            reduced_risk_percent=secondary[
                "reduced_risk_percent"
            ],
        )
    )

    exploratory_adjuster = (
        create_regime_adjuster(
            frozen_groups=exploratory[
                "frozen_regime_groups"
            ],
            reduced_risk_percent=exploratory[
                "reduced_risk_percent"
            ],
        )
    )

    primary_result = run_policy(
        policy_name=primary["name"],
        risk_adjuster=primary_adjuster,
        candles_by_market=candles_by_market,
        protocol=protocol,
    )

    secondary_result = run_policy(
        policy_name=secondary["name"],
        risk_adjuster=secondary_adjuster,
        candles_by_market=candles_by_market,
        protocol=protocol,
    )

    exploratory_result = run_policy(
        policy_name=exploratory["name"],
        risk_adjuster=exploratory_adjuster,
        candles_by_market=candles_by_market,
        protocol=protocol,
    )

    primary_evaluation = evaluate_candidate(
        primary_result["summary"],
        protocol[
            "primary_pass_criteria"
        ],
    )

    secondary_evaluation = evaluate_candidate(
        secondary_result["summary"],
        protocol[
            "secondary_pass_criteria"
        ],
    )

    print_policy_summary(
        primary_result,
        primary_evaluation,
    )

    print_policy_summary(
        secondary_result,
        secondary_evaluation,
    )

    print_policy_summary(
        exploratory_result,
        None,
    )

    results = {
        "protocol_name": protocol[
            "protocol_name"
        ],
        "protocol_version": protocol[
            "protocol_version"
        ],
        "protocol_status_before_run": (
            protocol["status"]
        ),
        "data_manifest": str(
            MANIFEST_PATH
        ),
        "input_hashes_verified": True,
        "previous_post_2024_holdout_reused": False,
        "primary": {
            **primary_result,
            "evaluation": primary_evaluation,
        },
        "secondary": {
            **secondary_result,
            "evaluation": secondary_evaluation,
        },
        "exploratory": exploratory_result,
        "overall_status": {
            "primary": (
                "PASSED"
                if primary_evaluation["passed"]
                else "FAILED"
            ),
            "secondary": (
                "PASSED"
                if secondary_evaluation["passed"]
                else "FAILED"
            ),
            "exploratory": (
                "NO_VALIDATION_CLAIM"
            ),
        },
    }

    RESULTS_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    RESULTS_PATH.write_text(
        json.dumps(
            results,
            indent=2,
            default=str,
        )
        + "\n"
    )

    print()
    print("=" * 132)
    print("FINAL ONE-TIME RESULT")
    print("=" * 132)
    print(
        "Primary candidate:",
        results[
            "overall_status"
        ]["primary"],
    )
    print(
        "Secondary candidate:",
        results[
            "overall_status"
        ]["secondary"],
    )
    print(
        "Exploratory comparator:",
        results[
            "overall_status"
        ]["exploratory"],
    )
    print(
        "Results file:",
        RESULTS_PATH,
    )
    print(
        "This result must not be used "
        "to retune the frozen policies."
    )


if __name__ == "__main__":
    main()
