import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.market_data.oanda import (
    convert_oanda_payload_to_rows,
    download_oanda_candles,
    save_oanda_rows_to_csv,
)


def main() -> None:
    api_token = os.getenv("OANDA_API_TOKEN", "")
    environment = os.getenv("OANDA_ENVIRONMENT", "practice")
    instrument = os.getenv("OANDA_INSTRUMENT", "EUR_USD")
    granularity = os.getenv("OANDA_GRANULARITY", "D")
    count = int(os.getenv("OANDA_CANDLE_COUNT", "5000"))

    output_file = Path(
        os.getenv(
            "OANDA_OUTPUT_FILE",
            "data/oanda_eur_usd_daily.csv",
        )
    )

    payload = download_oanda_candles(
        api_token=api_token,
        instrument=instrument,
        granularity=granularity,
        count=count,
        environment=environment,
    )

    rows = convert_oanda_payload_to_rows(
        payload=payload,
        instrument=instrument,
        timeframe=granularity,
    )

    save_oanda_rows_to_csv(
        rows=rows,
        output_file=output_file,
    )

    print(f"Saved {len(rows)} genuine OANDA candles to {output_file}")
    print(f"Instrument: {instrument}")
    print(f"Granularity: {granularity}")
    print(f"Environment: {environment}")


if __name__ == "__main__":
    main()
