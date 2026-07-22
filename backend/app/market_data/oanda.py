import json
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

OANDA_HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}


def build_oanda_candles_url(
    instrument: str,
    granularity: str = "D",
    count: int = 5000,
    environment: str = "practice",
) -> str:
    if environment not in OANDA_HOSTS:
        raise ValueError("OANDA environment must be 'practice' or 'live'.")

    if count < 1 or count > 5000:
        raise ValueError("OANDA candle count must be between 1 and 5000.")

    query = urllib.parse.urlencode(
        {
            "price": "M",
            "granularity": granularity,
            "count": count,
        }
    )

    return (
        f"{OANDA_HOSTS[environment]}"
        f"/v3/instruments/{instrument}/candles?{query}"
    )


def download_oanda_candles(
    api_token: str,
    instrument: str = "EUR_USD",
    granularity: str = "D",
    count: int = 5000,
    environment: str = "practice",
) -> dict:
    if not api_token.strip():
        raise ValueError("OANDA API token is required.")

    url = build_oanda_candles_url(
        instrument=instrument,
        granularity=granularity,
        count=count,
        environment=environment,
    )

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Accept-Datetime-Format": "RFC3339",
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def convert_oanda_payload_to_rows(
    payload: dict,
    instrument: str,
    timeframe: str,
) -> list[dict]:
    rows: list[dict] = []

    for candle in payload.get("candles", []):
        if not candle.get("complete", False):
            continue

        midpoint = candle.get("mid")

        if not midpoint:
            continue

        timestamp = candle["time"]
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        rows.append(
            {
                "timestamp": timestamp,
                "symbol": instrument,
                "timeframe": timeframe,
                "open": float(midpoint["o"]),
                "high": float(midpoint["h"]),
                "low": float(midpoint["l"]),
                "close": float(midpoint["c"]),
                "volume": int(candle.get("volume", 0)),
            }
        )

    if not rows:
        raise ValueError("OANDA returned no complete midpoint candles.")

    return rows


def save_oanda_rows_to_csv(
    rows: list[dict],
    output_file: Path,
) -> None:
    import csv

    output_file.parent.mkdir(parents=True, exist_ok=True)

    with output_file.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "timestamp",
                "symbol",
                "timeframe",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
