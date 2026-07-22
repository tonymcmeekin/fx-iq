from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

PROTOCOL_VERSION = "1.0"
PROTOCOL_FREEZE_COMMIT = "cd66c9b"

HOLDOUT_START = datetime(
    2024,
    8,
    5,
    0,
    0,
    tzinfo=UTC,
)

EXTERNAL_MARKETS = {
    "USD_JPY": Path("data/oanda_usd_jpy_daily.csv"),
    "USD_CAD": Path("data/oanda_usd_cad_daily.csv"),
    "NZD_USD": Path("data/oanda_nzd_usd_daily.csv"),
}

EXPECTED_SHA256 = {
    "USD_JPY": (
        "7927a64886fa7eabc9be18b6afef2e93"
        "bee11a0bd537a50f8335e7b8120545c6"
    ),
    "USD_CAD": (
        "2582d4fffb5176c3a9342322292fe961"
        "787ed5388e279ea1dbcf19471cfef219"
    ),
    "NZD_USD": (
        "86f5c0cd2a614469eaaa5d3d0aad2e29"
        "f90ac7be730bc279c8bcc26982fa734b"
    ),
}


class ExternalDatasetRecord(BaseModel):
    symbol: str
    path: Path
    expected_sha256: str = Field(
        min_length=64,
        max_length=64,
    )


class ExternalValidationProtocol(BaseModel):
    protocol_version: str
    freeze_commit: str
    holdout_start: datetime
    markets: list[ExternalDatasetRecord]
    strategy_logic_frozen: bool
    parameter_tuning_after_holdout_prohibited: bool
    holdout_may_be_opened_once: bool


def build_external_validation_protocol(
) -> ExternalValidationProtocol:
    return ExternalValidationProtocol(
        protocol_version=PROTOCOL_VERSION,
        freeze_commit=PROTOCOL_FREEZE_COMMIT,
        holdout_start=HOLDOUT_START,
        markets=[
            ExternalDatasetRecord(
                symbol=symbol,
                path=path,
                expected_sha256=EXPECTED_SHA256[symbol],
            )
            for symbol, path in EXTERNAL_MARKETS.items()
        ],
        strategy_logic_frozen=True,
        parameter_tuning_after_holdout_prohibited=True,
        holdout_may_be_opened_once=True,
    )
