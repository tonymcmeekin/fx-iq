from app.market_data.models import Candle
from app.market_data.oanda import (
    convert_oanda_payload_to_rows,
    download_oanda_candles,
)

OANDA_GRANULARITY_BY_TIMEFRAME = {
    "M15": "M15",
    "H1": "H1",
    "H4": "H4",
    "D1": "D",
}


class OandaReadOnlyMarketDataProvider:
    """
    Read completed midpoint candles from OANDA practice.

    This provider contains no account, order, position, trade,
    financing, or transaction endpoints.
    """

    provider_name = "oanda_practice"

    def __init__(self, api_token: str) -> None:
        if not api_token.strip():
            raise ValueError("OANDA API token is required.")

        self._api_token = api_token
        self.network_calls_made = 0

    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int,
    ) -> list[Candle]:
        try:
            granularity = OANDA_GRANULARITY_BY_TIMEFRAME[
                timeframe
            ]
        except KeyError as error:
            supported = ", ".join(
                sorted(OANDA_GRANULARITY_BY_TIMEFRAME)
            )
            raise ValueError(
                f"Unsupported scanner timeframe: {timeframe}. "
                f"Supported values: {supported}."
            ) from error

        payload = download_oanda_candles(
            api_token=self._api_token,
            instrument=symbol,
            granularity=granularity,
            count=count,
            environment="practice",
        )

        self.network_calls_made += 1

        rows = convert_oanda_payload_to_rows(
            payload=payload,
            instrument=symbol,
            timeframe=timeframe,
        )

        return [
            Candle.model_validate(row)
            for row in rows
        ]
