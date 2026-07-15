from copy import deepcopy
from datetime import UTC, datetime

from app.market_data.models import Candle
from app.paper_trading.execution import (
    CANDIDATE_ACCOUNT,
    SHADOW_ACCOUNT,
    SUPPORTED_ACCOUNTS,
    PaperExecutionError,
    parse_utc_datetime,
    utc_isoformat,
)
from app.paper_trading.runtime_state import (
    verify_runtime_state,
)
from app.trading.simulator import (
    calculate_profit_percent,
)


def validate_execution_candle(
    candle: Candle,
    *,
    market: str,
) -> None:
    if candle.symbol != market:
        raise PaperExecutionError(
            "Lifecycle candle market does not match "
            "the open position."
        )

    if candle.timeframe != "D":
        raise PaperExecutionError(
            "Position lifecycle requires daily candles."
        )

    if candle.timestamp.tzinfo is None:
        raise PaperExecutionError(
            "Lifecycle candle timestamp is timezone-naive."
        )

    if candle.open <= 0:
        raise PaperExecutionError(
            "Lifecycle candle open must be positive."
        )

    if candle.high < max(
        candle.open,
        candle.close,
        candle.low,
    ):
        raise PaperExecutionError(
            "Lifecycle candle high is invalid."
        )

    if candle.low > min(
        candle.open,
        candle.close,
        candle.high,
    ):
        raise PaperExecutionError(
            "Lifecycle candle low is invalid."
        )


def validate_position_leg(
    position: dict,
    *,
    account: str,
    market: str,
) -> None:
    if account not in SUPPORTED_ACCOUNTS:
        raise ValueError(
            "Account must be candidate or shadow."
        )

    required_fields = {
        "account",
        "market",
        "direction",
        "entry_timestamp",
        "entry_price",
        "stop_loss",
        "take_profit",
        "position_size_units",
        "notional_value",
        "risk_amount",
        "trading_cost_percent",
        "status",
        "broker_order_submitted",
    }

    missing = (
        required_fields
        - position.keys()
    )

    if missing:
        raise PaperExecutionError(
            f"{account} position is missing fields: "
            + ", ".join(
                sorted(missing)
            )
            + "."
        )

    if position["account"] != account:
        raise PaperExecutionError(
            "Position account label mismatch."
        )

    if position["market"] != market:
        raise PaperExecutionError(
            "Position market label mismatch."
        )

    if position["direction"] not in {
        "BUY",
        "SELL",
    }:
        raise PaperExecutionError(
            "Position direction must be BUY or SELL."
        )

    if position["status"] != "OPEN":
        raise PaperExecutionError(
            "Only open positions can be evaluated."
        )

    if position[
        "broker_order_submitted"
    ] is not False:
        raise PaperExecutionError(
            "Paper position records a broker order."
        )

    for field in (
        "entry_price",
        "stop_loss",
        "take_profit",
        "position_size_units",
        "notional_value",
        "risk_amount",
    ):
        try:
            value = float(
                position[field]
            )
        except (
            TypeError,
            ValueError,
        ) as error:
            raise PaperExecutionError(
                f"Position field {field} is invalid."
            ) from error

        if value <= 0:
            raise PaperExecutionError(
                f"Position field {field} must be positive."
            )

    trading_cost_percent = float(
        position[
            "trading_cost_percent"
        ]
    )

    if trading_cost_percent < 0:
        raise PaperExecutionError(
            "Trading cost percent cannot be negative."
        )

    parse_utc_datetime(
        position[
            "entry_timestamp"
        ]
    )


def determine_exit(
    position: dict,
    candle: Candle,
) -> dict | None:
    direction = position[
        "direction"
    ]

    stop_loss = float(
        position[
            "stop_loss"
        ]
    )

    take_profit = float(
        position[
            "take_profit"
        ]
    )

    if direction == "BUY":
        stop_hit = (
            candle.low
            <= stop_loss
        )

        target_hit = (
            candle.high
            >= take_profit
        )

    elif direction == "SELL":
        stop_hit = (
            candle.high
            >= stop_loss
        )

        target_hit = (
            candle.low
            <= take_profit
        )

    else:
        raise PaperExecutionError(
            "Position direction must be BUY or SELL."
        )

    if stop_hit:
        return {
            "exit_price": stop_loss,
            "exit_reason": (
                "Stop-loss used: both stop-loss and "
                "take-profit were touched in the same candle."
                if target_hit
                else "Stop-loss hit."
            ),
            "stop_hit": True,
            "target_hit": target_hit,
        }

    if target_hit:
        return {
            "exit_price": (
                take_profit
            ),
            "exit_reason": (
                "Take-profit hit."
            ),
            "stop_hit": False,
            "target_hit": True,
        }

    return None


def unrealized_pnl(
    position: dict,
    *,
    current_price: float,
) -> float:
    if current_price <= 0:
        raise ValueError(
            "Current price must be positive."
        )

    entry_price = float(
        position[
            "entry_price"
        ]
    )

    units = float(
        position[
            "position_size_units"
        ]
    )

    if position[
        "direction"
    ] == "BUY":
        return (
            current_price
            - entry_price
        ) * units

    if position[
        "direction"
    ] == "SELL":
        return (
            entry_price
            - current_price
        ) * units

    raise PaperExecutionError(
        "Position direction must be BUY or SELL."
    )


def close_position_leg(
    position: dict,
    *,
    candle: Candle,
    exit_price: float,
    exit_reason: str,
    balance_before: float,
) -> dict:
    if balance_before <= 0:
        raise ValueError(
            "Balance before closure must be positive."
        )

    entry_price = float(
        position[
            "entry_price"
        ]
    )

    notional_value = float(
        position[
            "notional_value"
        ]
    )

    gross_profit_percent = (
        calculate_profit_percent(
            direction=(
                position[
                    "direction"
                ]
            ),
            entry_price=entry_price,
            exit_price=exit_price,
        )
    )

    gross_pnl = (
        gross_profit_percent
        / 100
        * notional_value
    )

    trading_cost = (
        float(
            position[
                "trading_cost_percent"
            ]
        )
        / 100
        * notional_value
    )

    net_pnl = (
        gross_pnl
        - trading_cost
    )

    balance_after = (
        balance_before
        + net_pnl
    )

    if balance_after <= 0:
        raise PaperExecutionError(
            "Position closure would make the "
            "simulated account balance non-positive."
        )

    account_return_percent = (
        net_pnl
        / balance_before
        * 100
    )

    return {
        **deepcopy(
            position
        ),
        "status": "CLOSED",
        "exit_timestamp": (
            utc_isoformat(
                candle.timestamp
            )
        ),
        "exit_price": round(
            exit_price,
            10,
        ),
        "exit_reason": (
            exit_reason
        ),
        "gross_profit_percent": round(
            gross_profit_percent,
            10,
        ),
        "gross_pnl": round(
            gross_pnl,
            10,
        ),
        "trading_cost": round(
            trading_cost,
            10,
        ),
        "net_pnl": round(
            net_pnl,
            10,
        ),
        "account_return_percent": round(
            account_return_percent,
            10,
        ),
        "balance_before": round(
            balance_before,
            10,
        ),
        "balance_after": round(
            balance_after,
            10,
        ),
    }


def evaluate_open_position(
    state: dict,
    *,
    market: str,
    candle: Candle,
) -> tuple[dict, dict]:
    updated = deepcopy(
        verify_runtime_state(
            state
        )
    )

    position_pair = updated[
        "open_positions"
    ].get(market)

    if position_pair is None:
        return updated, {
            "status": "NO_OPEN_POSITION",
            "market": market,
        }

    validate_execution_candle(
        candle,
        market=market,
    )

    candidate = position_pair.get(
        CANDIDATE_ACCOUNT
    )

    shadow = position_pair.get(
        SHADOW_ACCOUNT
    )

    if not isinstance(
        candidate,
        dict,
    ) or not isinstance(
        shadow,
        dict,
    ):
        raise PaperExecutionError(
            "Open position must contain candidate "
            "and shadow legs."
        )

    validate_position_leg(
        candidate,
        account=CANDIDATE_ACCOUNT,
        market=market,
    )

    validate_position_leg(
        shadow,
        account=SHADOW_ACCOUNT,
        market=market,
    )

    if (
        candidate[
            "entry_timestamp"
        ]
        != shadow[
            "entry_timestamp"
        ]
        or candidate[
            "entry_price"
        ]
        != shadow[
            "entry_price"
        ]
        or candidate[
            "direction"
        ]
        != shadow[
            "direction"
        ]
        or candidate[
            "stop_loss"
        ]
        != shadow[
            "stop_loss"
        ]
        or candidate[
            "take_profit"
        ]
        != shadow[
            "take_profit"
        ]
    ):
        raise PaperExecutionError(
            "Candidate and shadow position paths diverged."
        )

    entry_timestamp = (
        parse_utc_datetime(
            candidate[
                "entry_timestamp"
            ]
        )
    )

    candle_timestamp = (
        candle.timestamp
        .astimezone(
            UTC
        )
    )

    if candle_timestamp < (
        entry_timestamp
    ):
        raise PaperExecutionError(
            "Lifecycle candle predates position entry."
        )

    exit_decision = (
        determine_exit(
            candidate,
            candle,
        )
    )

    candidate_unrealized = (
        unrealized_pnl(
            candidate,
            current_price=(
                candle.close
            ),
        )
    )

    shadow_unrealized = (
        unrealized_pnl(
            shadow,
            current_price=(
                candle.close
            ),
        )
    )

    if exit_decision is None:
        return updated, {
            "status": "OPEN",
            "market": market,
            "candle_timestamp": (
                utc_isoformat(
                    candle.timestamp
                )
            ),
            "close_price": (
                candle.close
            ),
            "candidate_unrealized_pnl": round(
                candidate_unrealized,
                10,
            ),
            "shadow_unrealized_pnl": round(
                shadow_unrealized,
                10,
            ),
            "candidate_balance": (
                updated[
                    "candidate_balance"
                ]
            ),
            "shadow_balance": (
                updated[
                    "shadow_balance"
                ]
            ),
            "broker_orders_submitted": 0,
        }

    candidate_balance_before = (
        float(
            updated[
                "candidate_balance"
            ]
        )
    )

    shadow_balance_before = (
        float(
            updated[
                "shadow_balance"
            ]
        )
    )

    candidate_closed = (
        close_position_leg(
            candidate,
            candle=candle,
            exit_price=(
                exit_decision[
                    "exit_price"
                ]
            ),
            exit_reason=(
                exit_decision[
                    "exit_reason"
                ]
            ),
            balance_before=(
                candidate_balance_before
            ),
        )
    )

    shadow_closed = (
        close_position_leg(
            shadow,
            candle=candle,
            exit_price=(
                exit_decision[
                    "exit_price"
                ]
            ),
            exit_reason=(
                exit_decision[
                    "exit_reason"
                ]
            ),
            balance_before=(
                shadow_balance_before
            ),
        )
    )

    if (
        candidate_closed[
            "exit_timestamp"
        ]
        != shadow_closed[
            "exit_timestamp"
        ]
        or candidate_closed[
            "exit_price"
        ]
        != shadow_closed[
            "exit_price"
        ]
        or candidate_closed[
            "exit_reason"
        ]
        != shadow_closed[
            "exit_reason"
        ]
    ):
        raise PaperExecutionError(
            "Candidate and shadow closures diverged."
        )

    updated[
        "candidate_balance"
    ] = candidate_closed[
        "balance_after"
    ]

    updated[
        "shadow_balance"
    ] = shadow_closed[
        "balance_after"
    ]

    updated[
        "candidate_peak_equity"
    ] = max(
        float(
            updated[
                "candidate_peak_equity"
            ]
        ),
        float(
            updated[
                "candidate_balance"
            ]
        ),
    )

    updated[
        "shadow_peak_equity"
    ] = max(
        float(
            updated[
                "shadow_peak_equity"
            ]
        ),
        float(
            updated[
                "shadow_balance"
            ]
        ),
    )

    updated[
        "open_positions"
    ].pop(
        market
    )

    verify_runtime_state(
        updated
    )

    result = {
        "status": "CLOSED",
        "market": market,
        "direction": (
            candidate[
                "direction"
            ]
        ),
        "entry_timestamp": (
            candidate[
                "entry_timestamp"
            ]
        ),
        "exit_timestamp": (
            candidate_closed[
                "exit_timestamp"
            ]
        ),
        "entry_price": (
            candidate[
                "entry_price"
            ]
        ),
        "exit_price": (
            candidate_closed[
                "exit_price"
            ]
        ),
        "exit_reason": (
            candidate_closed[
                "exit_reason"
            ]
        ),
        "stop_hit": (
            exit_decision[
                "stop_hit"
            ]
        ),
        "target_hit": (
            exit_decision[
                "target_hit"
            ]
        ),
        "candidate_net_pnl": (
            candidate_closed[
                "net_pnl"
            ]
        ),
        "shadow_net_pnl": (
            shadow_closed[
                "net_pnl"
            ]
        ),
        "candidate_balance": (
            updated[
                "candidate_balance"
            ]
        ),
        "shadow_balance": (
            updated[
                "shadow_balance"
            ]
        ),
        "candidate_peak_equity": (
            updated[
                "candidate_peak_equity"
            ]
        ),
        "shadow_peak_equity": (
            updated[
                "shadow_peak_equity"
            ]
        ),
        "candidate_trade": (
            candidate_closed
        ),
        "shadow_trade": (
            shadow_closed
        ),
        "broker_orders_submitted": 0,
    }

    return updated, result
