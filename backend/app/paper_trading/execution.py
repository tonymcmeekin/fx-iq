from copy import deepcopy
from datetime import UTC, datetime

from app.market_data.models import Candle
from app.paper_trading.runtime_state import (
    RuntimeStateError,
    verify_runtime_state,
)
from app.trading.simulator import (
    calculate_trading_cost_percent,
)

STOP_LOSS_PERCENT = 1.5
TAKE_PROFIT_PERCENT = 3.0

SPREAD_PIPS = 1.0
SLIPPAGE_PIPS = 0.5
COMMISSION_PERCENT = 0.0

# This deliberately preserves the frozen validation implementation.
# It is used for every market, including JPY-quoted markets.
FROZEN_PIP_SIZE = 0.0001

MAXIMUM_PORTFOLIO_LEVERAGE = 30.0
MAXIMUM_TOTAL_OPEN_RISK_PERCENT = 0.5

CANDIDATE_ACCOUNT = "candidate"
SHADOW_ACCOUNT = "shadow"

SUPPORTED_ACCOUNTS = {
    CANDIDATE_ACCOUNT,
    SHADOW_ACCOUNT,
}


class PaperExecutionError(RuntimeError):
    """Raised when a simulated paper fill cannot be executed safely."""


def utc_isoformat(
    value: datetime,
) -> str:
    if value.tzinfo is None:
        raise ValueError(
            "Datetime must be timezone-aware."
        )

    return (
        value.astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_utc_datetime(
    value: str,
) -> datetime:
    try:
        parsed = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )
    except ValueError as error:
        raise PaperExecutionError(
            "Timestamp is not valid ISO-8601."
        ) from error

    if parsed.tzinfo is None:
        raise PaperExecutionError(
            "Timestamp must be timezone-aware."
        )

    return parsed.astimezone(UTC)


def next_complete_candle(
    candles: list[Candle],
    *,
    signal_candle_timestamp: datetime,
    expected_market: str,
) -> Candle | None:
    if signal_candle_timestamp.tzinfo is None:
        raise ValueError(
            "Signal timestamp must be timezone-aware."
        )

    signal_timestamp = (
        signal_candle_timestamp.astimezone(
            UTC
        )
    )

    previous_timestamp = None

    for candle in candles:
        if candle.symbol != expected_market:
            raise PaperExecutionError(
                "Candle market does not match the "
                "pending-entry market."
            )

        if candle.timeframe != "D":
            raise PaperExecutionError(
                "Paper execution requires daily candles."
            )

        if candle.timestamp.tzinfo is None:
            raise PaperExecutionError(
                "Execution candle timestamp is timezone-naive."
            )

        candle_timestamp = (
            candle.timestamp.astimezone(
                UTC
            )
        )

        if (
            previous_timestamp is not None
            and candle_timestamp
            <= previous_timestamp
        ):
            raise PaperExecutionError(
                "Execution candles must be strictly chronological."
            )

        previous_timestamp = candle_timestamp

        if candle_timestamp > signal_timestamp:
            return candle

    return None


def account_balance_field(
    account: str,
) -> str:
    if account not in SUPPORTED_ACCOUNTS:
        raise ValueError(
            "Account must be candidate or shadow."
        )

    return f"{account}_balance"


def account_risk_percent(
    pending_entry: dict,
    account: str,
) -> float:
    if account == CANDIDATE_ACCOUNT:
        risk = float(
            pending_entry[
                "candidate_risk_percent"
            ]
        )
    elif account == SHADOW_ACCOUNT:
        risk = float(
            pending_entry[
                "shadow_risk_percent"
            ]
        )
    else:
        raise ValueError(
            "Account must be candidate or shadow."
        )

    if risk <= 0:
        raise PaperExecutionError(
            "Position risk must be greater than zero."
        )

    if risk > (
        MAXIMUM_TOTAL_OPEN_RISK_PERCENT
    ):
        raise PaperExecutionError(
            "Position risk exceeds the frozen maximum."
        )

    return risk


def account_position(
    position_pair: dict,
    account: str,
) -> dict:
    position = position_pair.get(
        account
    )

    if not isinstance(position, dict):
        raise PaperExecutionError(
            f"Open position is missing its {account} leg."
        )

    return position


def total_open_risk_amount(
    state: dict,
    *,
    account: str,
) -> float:
    verify_runtime_state(
        state
    )

    total = 0.0

    for position_pair in (
        state["open_positions"].values()
    ):
        position = account_position(
            position_pair,
            account,
        )

        try:
            risk_amount = float(
                position["risk_amount"]
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise PaperExecutionError(
                "Open position has invalid risk amount."
            ) from error

        if risk_amount < 0:
            raise PaperExecutionError(
                "Open position risk cannot be negative."
            )

        total += risk_amount

    return total


def total_open_notional(
    state: dict,
    *,
    account: str,
) -> float:
    verify_runtime_state(
        state
    )

    total = 0.0

    for position_pair in (
        state["open_positions"].values()
    ):
        position = account_position(
            position_pair,
            account,
        )

        try:
            notional = float(
                position["notional_value"]
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise PaperExecutionError(
                "Open position has invalid notional value."
            ) from error

        if notional < 0:
            raise PaperExecutionError(
                "Open position notional cannot be negative."
            )

        total += notional

    return total


def stop_and_target(
    *,
    direction: str,
    entry_price: float,
) -> tuple[float, float]:
    if entry_price <= 0:
        raise ValueError(
            "Entry price must be greater than zero."
        )

    if direction == "BUY":
        stop_loss = entry_price * (
            1
            - STOP_LOSS_PERCENT
            / 100
        )

        take_profit = entry_price * (
            1
            + TAKE_PROFIT_PERCENT
            / 100
        )

    elif direction == "SELL":
        stop_loss = entry_price * (
            1
            + STOP_LOSS_PERCENT
            / 100
        )

        take_profit = entry_price * (
            1
            - TAKE_PROFIT_PERCENT
            / 100
        )

    else:
        raise ValueError(
            "Direction must be BUY or SELL."
        )

    return stop_loss, take_profit


def build_account_position(
    *,
    state: dict,
    pending_entry: dict,
    entry_candle: Candle,
    account: str,
) -> dict:
    verify_runtime_state(
        state
    )

    market = pending_entry[
        "market"
    ]

    if entry_candle.symbol != market:
        raise PaperExecutionError(
            "Entry candle market does not match "
            "the pending entry."
        )

    direction = pending_entry[
        "direction"
    ]

    entry_price = float(
        entry_candle.open
    )

    stop_loss, take_profit = (
        stop_and_target(
            direction=direction,
            entry_price=entry_price,
        )
    )

    stop_distance = abs(
        entry_price - stop_loss
    )

    if stop_distance <= 0:
        raise PaperExecutionError(
            "Calculated stop distance is invalid."
        )

    balance = float(
        state[
            account_balance_field(
                account
            )
        ]
    )

    configured_risk_percent = (
        account_risk_percent(
            pending_entry,
            account,
        )
    )

    desired_risk_amount = (
        balance
        * configured_risk_percent
        / 100
    )

    open_risk_amount = (
        total_open_risk_amount(
            state,
            account=account,
        )
    )

    maximum_open_risk_amount = (
        balance
        * MAXIMUM_TOTAL_OPEN_RISK_PERCENT
        / 100
    )

    remaining_risk_amount = max(
        maximum_open_risk_amount
        - open_risk_amount,
        0.0,
    )

    allocated_risk_amount = min(
        desired_risk_amount,
        remaining_risk_amount,
    )

    if allocated_risk_amount <= 0:
        raise PaperExecutionError(
            f"No {account} portfolio risk capacity remains."
        )

    open_notional = total_open_notional(
        state,
        account=account,
    )

    maximum_notional = (
        balance
        * MAXIMUM_PORTFOLIO_LEVERAGE
    )

    remaining_notional = max(
        maximum_notional
        - open_notional,
        0.0,
    )

    risk_based_units = (
        allocated_risk_amount
        / stop_distance
    )

    leverage_based_units = (
        remaining_notional
        / entry_price
    )

    position_size_units = min(
        risk_based_units,
        leverage_based_units,
    )

    if position_size_units <= 0:
        raise PaperExecutionError(
            f"No {account} leverage capacity remains."
        )

    notional_value = (
        position_size_units
        * entry_price
    )

    actual_risk_amount = (
        position_size_units
        * stop_distance
    )

    leverage_after_entry = (
        open_notional
        + notional_value
    ) / balance

    trading_cost_percent = (
        calculate_trading_cost_percent(
            entry_price=entry_price,
            spread_pips=SPREAD_PIPS,
            commission_percent=(
                COMMISSION_PERCENT
            ),
            slippage_pips=(
                SLIPPAGE_PIPS
            ),
            pip_size=FROZEN_PIP_SIZE,
        )
    )

    return {
        "account": account,
        "market": market,
        "direction": direction,
        "signal_candle_timestamp": (
            pending_entry[
                "signal_candle_timestamp"
            ]
        ),
        "created_session_date": (
            pending_entry[
                "created_session_date"
            ]
        ),
        "entry_timestamp": (
            utc_isoformat(
                entry_candle.timestamp
            )
        ),
        "entry_price": round(
            entry_price,
            10,
        ),
        "stop_loss": round(
            stop_loss,
            10,
        ),
        "take_profit": round(
            take_profit,
            10,
        ),
        "configured_risk_percent": (
            configured_risk_percent
        ),
        "risk_amount": round(
            actual_risk_amount,
            10,
        ),
        "position_size_units": round(
            position_size_units,
            10,
        ),
        "notional_value": round(
            notional_value,
            10,
        ),
        "leverage_at_entry": round(
            leverage_after_entry,
            10,
        ),
        "spread_pips": SPREAD_PIPS,
        "slippage_pips": (
            SLIPPAGE_PIPS
        ),
        "commission_percent": (
            COMMISSION_PERCENT
        ),
        "pip_size": FROZEN_PIP_SIZE,
        "trading_cost_percent": round(
            trading_cost_percent,
            12,
        ),
        "status": "OPEN",
        "broker_order_submitted": False,
    }


def fill_pending_entry(
    state: dict,
    *,
    market: str,
    candles: list[Candle],
    policy_fingerprint: str,
) -> tuple[dict, dict]:
    verified_state = deepcopy(
        verify_runtime_state(
            state
        )
    )

    if market in verified_state[
        "open_positions"
    ]:
        raise RuntimeStateError(
            f"{market} already has an open position."
        )

    pending_entry = verified_state[
        "pending_entries"
    ].get(market)

    if pending_entry is None:
        return verified_state, {
            "status": "NO_PENDING_ENTRY",
            "market": market,
        }

    if pending_entry[
        "policy_fingerprint"
    ] != policy_fingerprint:
        raise PaperExecutionError(
            "Pending-entry policy fingerprint mismatch."
        )

    signal_timestamp = (
        parse_utc_datetime(
            pending_entry[
                "signal_candle_timestamp"
            ]
        )
    )

    entry_candle = next_complete_candle(
        candles,
        signal_candle_timestamp=(
            signal_timestamp
        ),
        expected_market=market,
    )

    if entry_candle is None:
        return verified_state, {
            "status": "WAITING_FOR_NEXT_CANDLE",
            "market": market,
            "signal_candle_timestamp": (
                pending_entry[
                    "signal_candle_timestamp"
                ]
            ),
        }

    candidate_position = (
        build_account_position(
            state=verified_state,
            pending_entry=(
                pending_entry
            ),
            entry_candle=entry_candle,
            account=CANDIDATE_ACCOUNT,
        )
    )

    shadow_position = (
        build_account_position(
            state=verified_state,
            pending_entry=(
                pending_entry
            ),
            entry_candle=entry_candle,
            account=SHADOW_ACCOUNT,
        )
    )

    if (
        candidate_position[
            "entry_timestamp"
        ]
        != shadow_position[
            "entry_timestamp"
        ]
        or candidate_position[
            "entry_price"
        ]
        != shadow_position[
            "entry_price"
        ]
        or candidate_position[
            "direction"
        ]
        != shadow_position[
            "direction"
        ]
    ):
        raise PaperExecutionError(
            "Candidate and shadow trade sequences diverged."
        )

    position_pair = {
        "market": market,
        "direction": pending_entry[
            "direction"
        ],
        "signal_candle_timestamp": (
            pending_entry[
                "signal_candle_timestamp"
            ]
        ),
        "created_session_date": (
            pending_entry[
                "created_session_date"
            ]
        ),
        "entry_timestamp": (
            candidate_position[
                "entry_timestamp"
            ]
        ),
        "entry_price": (
            candidate_position[
                "entry_price"
            ]
        ),
        "candidate_risk_percent": (
            candidate_position[
                "configured_risk_percent"
            ]
        ),
        "shadow_risk_percent": (
            shadow_position[
                "configured_risk_percent"
            ]
        ),
        "candidate": (
            candidate_position
        ),
        "shadow": (
            shadow_position
        ),
        "broker_orders_submitted": 0,
    }

    verified_state[
        "pending_entries"
    ].pop(
        market
    )

    verified_state[
        "open_positions"
    ][market] = position_pair

    verify_runtime_state(
        verified_state
    )

    result = {
        "status": "FILLED",
        "market": market,
        "direction": position_pair[
            "direction"
        ],
        "signal_candle_timestamp": (
            position_pair[
                "signal_candle_timestamp"
            ]
        ),
        "created_session_date": (
            pending_entry[
                "created_session_date"
            ]
        ),
        "entry_timestamp": (
            position_pair[
                "entry_timestamp"
            ]
        ),
        "entry_price": (
            position_pair[
                "entry_price"
            ]
        ),
        "candidate_risk_percent": (
            candidate_position[
                "configured_risk_percent"
            ]
        ),
        "shadow_risk_percent": (
            shadow_position[
                "configured_risk_percent"
            ]
        ),
        "candidate_risk_amount": (
            candidate_position[
                "risk_amount"
            ]
        ),
        "shadow_risk_amount": (
            shadow_position[
                "risk_amount"
            ]
        ),
        "candidate_units": (
            candidate_position[
                "position_size_units"
            ]
        ),
        "shadow_units": (
            shadow_position[
                "position_size_units"
            ]
        ),
        "broker_orders_submitted": 0,
    }

    return verified_state, result
