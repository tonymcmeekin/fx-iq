from scripts.guarded_adaptive_policy_walk_forward import (
    BASELINE_STRATEGY,
    choose_guarded_policy,
)


def candidate(
    strategy,
    score,
    return_percent,
    profit_factor,
    drawdown,
    trades=50,
):
    return {
        "strategy": strategy,
        "score": score,
        "return": return_percent,
        "profit_factor": profit_factor,
        "drawdown": drawdown,
        "trades": trades,
    }


def baseline(score=2.0):
    return candidate(
        BASELINE_STRATEGY,
        score=score,
        return_percent=2.0,
        profit_factor=1.2,
        drawdown=4.0,
    )


def test_promotes_strong_challenger():
    selected, reason = choose_guarded_policy(
        [
            candidate(
                "atr_regime_sell_bias",
                score=5.0,
                return_percent=4.0,
                profit_factor=1.4,
                drawdown=3.0,
            ),
            baseline(),
        ]
    )

    assert selected == "atr_regime_sell_bias"
    assert "promoted" in reason.lower()


def test_retains_baseline_when_margin_is_too_small():
    selected, reason = choose_guarded_policy(
        [
            candidate(
                "atr_regime_filtered",
                score=3.0,
                return_percent=3.0,
                profit_factor=1.3,
                drawdown=3.0,
            ),
            baseline(),
        ]
    )

    assert selected == BASELINE_STRATEGY
    assert "retained" in reason.lower()


def test_retains_baseline_for_negative_return():
    selected, _ = choose_guarded_policy(
        [
            candidate(
                "atr_regime_sell_bias",
                score=5.0,
                return_percent=-1.0,
                profit_factor=1.3,
                drawdown=3.0,
            ),
            baseline(score=0.0),
        ]
    )

    assert selected == BASELINE_STRATEGY


def test_retains_baseline_for_weak_profit_factor():
    selected, _ = choose_guarded_policy(
        [
            candidate(
                "atr_regime_sell_bias",
                score=5.0,
                return_percent=3.0,
                profit_factor=1.01,
                drawdown=3.0,
            ),
            baseline(score=0.0),
        ]
    )

    assert selected == BASELINE_STRATEGY


def test_retains_baseline_for_insufficient_trades():
    selected, _ = choose_guarded_policy(
        [
            candidate(
                "atr_regime_sell_bias",
                score=5.0,
                return_percent=3.0,
                profit_factor=1.3,
                drawdown=3.0,
                trades=10,
            ),
            baseline(score=0.0),
        ]
    )

    assert selected == BASELINE_STRATEGY
