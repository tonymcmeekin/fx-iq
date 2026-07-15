from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.ai.regime import detect_market_regime
from app.ai.regime_risk import calculate_regime_risk
from app.market_data.csv_loader import load_candles_from_csv


DATA_FILE = Path(
    "data/oanda_eur_usd_daily.csv"
)


def main() -> None:
    candles = load_candles_from_csv(DATA_FILE)

    regime = detect_market_regime(candles)

    decision = calculate_regime_risk(
        base_risk_percent=0.5,
        regime=regime,
    )

    print("TRADE IQ REGIME-AWARE RISK DEMONSTRATION")
    print("=" * 72)
    print("Market:", candles[-1].symbol)
    print("Trend:", regime.trend)
    print("Volatility:", regime.volatility)
    print("Regime confidence:", regime.confidence)
    print("Configured base risk:", "0.5%")
    print(
        "Risk multiplier:",
        decision.risk_multiplier,
    )
    print(
        "Adjusted risk:",
        f"{decision.adjusted_risk_percent}%",
    )
    print()
    print("Reasons:")

    for reason in decision.reasons:
        print("-", reason)

    print()
    print(
        "This module only calculates a risk recommendation. "
        "It is not yet connected to trade execution."
    )


if __name__ == "__main__":
    main()
