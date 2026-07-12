import json
from pathlib import Path

from app.market_data.oanda import (
    build_oanda_candles_url,
    convert_oanda_payload_to_rows,
    download_oanda_candles,
    save_oanda_rows_to_csv,
)


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def sample_payload() -> dict:
    return {
        "instrument": "EUR_USD",
        "granularity": "D",
        "candles": [
            {
                "complete": True,
                "volume": 1234,
                "time": "2026-07-09T21:00:00.000000000Z",
                "mid": {
                    "o": "1.17000",
                    "h": "1.18000",
                    "l": "1.16500",
                    "c": "1.17500",
                },
            },
            {
                "complete": False,
                "volume": 500,
                "time": "2026-07-10T21:00:00.000000000Z",
                "mid": {
                    "o": "1.17500",
                    "h": "1.17700",
                    "l": "1.17200",
                    "c": "1.17600",
                },
            },
        ],
    }


def test_build_oanda_practice_url():
    url = build_oanda_candles_url(
        instrument="EUR_USD",
        granularity="D",
        count=5000,
        environment="practice",
    )

    assert url.startswith(
        "https://api-fxpractice.oanda.com/v3/instruments/EUR_USD/candles?"
    )
    assert "granularity=D" in url
    assert "count=5000" in url
    assert "price=M" in url


def test_convert_oanda_payload_excludes_incomplete_candles():
    rows = convert_oanda_payload_to_rows(
        payload=sample_payload(),
        instrument="EUR_USD",
        timeframe="D",
    )

    assert len(rows) == 1
    assert rows[0]["symbol"] == "EUR_USD"
    assert rows[0]["open"] == 1.17
    assert rows[0]["close"] == 1.175
    assert rows[0]["volume"] == 1234


def test_download_oanda_candles_uses_authorisation_header(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        return FakeResponse(sample_payload())

    monkeypatch.setattr(
        "urllib.request.urlopen",
        fake_urlopen,
    )

    payload = download_oanda_candles(
        api_token="test-token",
        instrument="EUR_USD",
    )

    assert payload["instrument"] == "EUR_USD"
    assert captured["authorization"] == "Bearer test-token"
    assert captured["timeout"] == 60


def test_save_oanda_rows_to_csv(tmp_path: Path):
    rows = convert_oanda_payload_to_rows(
        payload=sample_payload(),
        instrument="EUR_USD",
        timeframe="D",
    )

    output_file = tmp_path / "oanda.csv"

    save_oanda_rows_to_csv(
        rows=rows,
        output_file=output_file,
    )

    contents = output_file.read_text()

    assert "timestamp,symbol,timeframe,open,high,low,close,volume" in contents
    assert "EUR_USD" in contents


def test_oanda_token_is_required():
    try:
        download_oanda_candles(api_token="")
    except ValueError as error:
        assert str(error) == "OANDA API token is required."
    else:
        raise AssertionError("Expected missing OANDA token to be rejected.")
