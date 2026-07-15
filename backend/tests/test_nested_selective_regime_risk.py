from scripts.nested_selective_regime_risk_walk_forward import (
    create_frozen_adjuster,
    discover_robust_negative_groups,
)


def make_records(
    *,
    key,
    markets,
    returns,
    fold=1,
):
    trend, volatility, direction = key

    records = []

    for index in range(40):
        market = markets[
            index % len(markets)
        ]

        records.append(
            {
                "market": market,
                "fold": fold,
                "trend": trend,
                "volatility": volatility,
                "direction": direction,
                "return": returns[
                    index % len(returns)
                ],
            }
        )

    return records


def test_discovers_robust_negative_group():
    key = (
        "TRENDING_UP",
        "NORMAL",
        "BUY",
    )

    records = make_records(
        key=key,
        markets=[
            "EUR_USD",
            "GBP_USD",
            "AUD_USD",
            "USD_JPY",
        ],
        returns=[-0.1, -0.2],
    )

    selected = (
        discover_robust_negative_groups(
            records
        )
    )

    assert key in selected


def test_rejects_positive_group():
    key = (
        "TRENDING_DOWN",
        "HIGH",
        "SELL",
    )

    records = make_records(
        key=key,
        markets=[
            "EUR_USD",
            "GBP_USD",
            "AUD_USD",
            "USD_JPY",
        ],
        returns=[0.1, 0.2],
    )

    selected = (
        discover_robust_negative_groups(
            records
        )
    )

    assert key not in selected


def test_rejects_group_with_too_few_markets():
    key = (
        "TRENDING_DOWN",
        "NORMAL",
        "SELL",
    )

    records = make_records(
        key=key,
        markets=[
            "EUR_USD",
            "GBP_USD",
            "AUD_USD",
        ],
        returns=[-0.1],
    )

    selected = (
        discover_robust_negative_groups(
            records
        )
    )

    assert key not in selected


def test_frozen_adjuster_retains_risk_with_short_history():
    adjuster = create_frozen_adjuster(
        {
            (
                "TRENDING_UP",
                "NORMAL",
                "BUY",
            )
        }
    )

    class Config:
        risk_per_trade_percent = 0.5

    result = adjuster(
        Config(),
        [],
        "BUY",
    )

    assert result == 0.5
