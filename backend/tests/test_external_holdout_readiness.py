from scripts.open_external_market_holdout import (
    readiness_from_all_markets,
)


def holdout_result(
    return_percent,
    baseline_return,
    drawdown,
    baseline_drawdown,
    trades,
):
    return {
        "guarded_return": return_percent,
        "baseline_return": baseline_return,
        "guarded_drawdown": drawdown,
        "baseline_drawdown": baseline_drawdown,
        "guarded_trades": trades,
    }


def test_holdout_results_are_added_to_six_markets():
    evidence, _ = readiness_from_all_markets(
        [
            holdout_result(
                2.0,
                1.0,
                3.0,
                4.0,
                20,
            ),
            holdout_result(
                1.0,
                -1.0,
                2.0,
                4.0,
                20,
            ),
            holdout_result(
                -1.0,
                -2.0,
                4.0,
                5.0,
                20,
            ),
        ]
    )

    assert evidence.markets_tested == 6
    assert evidence.untouched_holdout_tested is True
    assert evidence.external_markets_tested is True


def test_holdout_trade_counts_are_included():
    evidence, _ = readiness_from_all_markets(
        [
            holdout_result(
                1.0,
                0.0,
                3.0,
                4.0,
                10,
            ),
            holdout_result(
                1.0,
                0.0,
                3.0,
                4.0,
                20,
            ),
            holdout_result(
                1.0,
                0.0,
                3.0,
                4.0,
                30,
            ),
        ]
    )

    assert evidence.total_out_of_sample_trades == 322
