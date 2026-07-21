from datetime import (
    UTC,
    date,
    datetime,
    timedelta,
)

import pytest

from app.intelligence import (
    PortfolioContext,
    build_trade_observation,
)
from app.market_data.models import Candle
from app.signals.models import TradeSignal


def make_candles(
    count: int = 80,
) -> list[Candle]:
    start = datetime(
        2026,
        1,
        1,
        tzinfo=UTC,
    )

    candles = []

    for index in range(count):
        close = 1.10 + index * 0.001

        candles.append(
            Candle(
                symbol="EUR_USD",
                timeframe="D",
                timestamp=(start + timedelta(days=index)),
                open=close,
                high=close + 0.0005,
                low=close - 0.0005,
                close=close,
                volume=1000,
            )
        )

    return candles


def make_signal() -> TradeSignal:
    return TradeSignal(
        symbol="EUR_USD",
        direction="BUY",
        confidence=0.8,
        strategy_name="atr_breakout",
        reason="Test signal.",
    )


def build_observation():
    return build_trade_observation(
        session_date=date(
            2026,
            7,
            21,
        ),
        recorded_at_utc=datetime(
            2026,
            7,
            21,
            20,
            0,
            tzinfo=UTC,
        ),
        candles=make_candles(),
        signal=make_signal(),
        trade_accepted=True,
        decision_reason=("Accepted by existing rules."),
        portfolio_context=(
            PortfolioContext(
                pending_entries_total=1,
                open_positions_total=2,
                correlated_positions=1,
                portfolio_risk_percent=1.0,
            )
        ),
    )


def test_observation_is_deterministic():
    first = build_observation()
    second = build_observation()

    assert first == second
    assert first.observation_id == second.observation_id


def test_observation_reuses_existing_features():
    observation = build_observation()

    assert observation.features.candle_count == 80
    assert observation.features.ema_20 is not None
    assert observation.features.ema_50 is not None
    assert observation.features.atr_14 is not None
    assert observation.features.atr_percent is not None
    assert 0 <= (observation.features.setup_quality_score) <= 100


def test_observation_records_regime():
    observation = build_observation()

    assert observation.regime.trend == "TRENDING_UP"
    assert observation.regime.confidence == 1.0
    assert observation.regime.candles_analysed == 50


def test_observation_contains_no_credentials():
    payload = build_observation().model_dump_json()

    forbidden = (
        "OANDA_API_TOKEN",
        "OANDA_ACCOUNT_ID",
        "Bearer ",
        "secret-token",
    )

    for value in forbidden:
        assert value not in payload


def test_observation_requires_sufficient_regime_history():
    with pytest.raises(
        ValueError,
        match="At least 50 candles",
    ):
        build_trade_observation(
            session_date=date(
                2026,
                7,
                21,
            ),
            recorded_at_utc=datetime(
                2026,
                7,
                21,
                tzinfo=UTC,
            ),
            candles=make_candles(49),
            signal=make_signal(),
            trade_accepted=False,
            decision_reason=("Insufficient history."),
        )


def test_signal_must_match_instrument():
    signal = make_signal().model_copy(
        update={
            "symbol": "GBP_USD",
        }
    )

    with pytest.raises(
        ValueError,
        match="does not match candles",
    ):
        build_trade_observation(
            session_date=date(
                2026,
                7,
                21,
            ),
            recorded_at_utc=datetime(
                2026,
                7,
                21,
                tzinfo=UTC,
            ),
            candles=make_candles(),
            signal=signal,
            trade_accepted=False,
            decision_reason=("Instrument mismatch."),
        )
