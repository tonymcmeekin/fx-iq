from hashlib import sha256
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.ai.external_validation import (
    build_external_validation_protocol,
)
from app.market_data.csv_loader import (
    load_candles_from_csv,
)


def file_sha256(path: Path) -> str:
    digest = sha256()

    with path.open("rb") as file:
        for chunk in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def main() -> None:
    protocol = build_external_validation_protocol()

    print("TRADE IQ EXTERNAL VALIDATION PROTOCOL")
    print("=" * 76)
    print("Protocol version:", protocol.protocol_version)
    print("Frozen at commit:", protocol.freeze_commit)
    print(
        "Untouched holdout begins:",
        protocol.holdout_start.isoformat(),
    )
    print(
        "Strategy logic frozen:",
        protocol.strategy_logic_frozen,
    )
    print(
        "Post-holdout tuning prohibited:",
        protocol.parameter_tuning_after_holdout_prohibited,
    )
    print(
        "Holdout may be opened once:",
        protocol.holdout_may_be_opened_once,
    )

    errors = []

    for market in protocol.markets:
        print()
        print(market.symbol)
        print("-" * 76)

        if not market.path.exists():
            errors.append(
                f"{market.symbol}: file is missing"
            )
            continue

        actual_hash = file_sha256(market.path)
        candles = load_candles_from_csv(market.path)

        development = [
            candle
            for candle in candles
            if candle.timestamp
            < protocol.holdout_start
        ]

        holdout = [
            candle
            for candle in candles
            if candle.timestamp
            >= protocol.holdout_start
        ]

        symbols = {
            candle.symbol
            for candle in candles
        }

        print("Path:", market.path)
        print("SHA-256:", actual_hash)
        print(
            "Checksum:",
            (
                "MATCH"
                if actual_hash
                == market.expected_sha256
                else "MISMATCH"
            ),
        )
        print("Total candles:", len(candles))
        print("Development candles:", len(development))
        print("Reserved holdout candles:", len(holdout))
        print(
            "Development end:",
            (
                development[-1].timestamp.isoformat()
                if development
                else "NONE"
            ),
        )
        print(
            "Holdout start:",
            (
                holdout[0].timestamp.isoformat()
                if holdout
                else "NONE"
            ),
        )
        print(
            "Dataset end:",
            candles[-1].timestamp.isoformat(),
        )

        if actual_hash != market.expected_sha256:
            errors.append(
                f"{market.symbol}: checksum mismatch"
            )

        if symbols != {market.symbol}:
            errors.append(
                f"{market.symbol}: unexpected symbols "
                f"{sorted(symbols)}"
            )

        if len(development) < 4000:
            errors.append(
                f"{market.symbol}: insufficient development "
                "history"
            )

        if len(holdout) < 400:
            errors.append(
                f"{market.symbol}: insufficient holdout history"
            )

        if not development:
            errors.append(
                f"{market.symbol}: no development candles"
            )

        if not holdout:
            errors.append(
                f"{market.symbol}: no holdout candles"
            )

    print()
    print("=" * 76)

    if errors:
        print("PROTOCOL VERIFICATION FAILED")

        for error in errors:
            print("FAIL:", error)

        raise SystemExit(1)

    print("PROTOCOL VERIFIED")
    print(
        "No trading performance has been calculated by this "
        "script."
    )
    print(
        "The final holdout remains reserved and unopened."
    )


if __name__ == "__main__":
    main()
