"""GET-only OANDA Practice GSLO proposal and GBP budget preflight."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlencode

from app.broker.canary_gateway import LIVE_CANARY_BUILD_ENABLED
from app.broker.models import BrokerDirection
from app.broker.oanda_read_only import OandaPracticeReadOnlyClient

MAXIMUM_QUOTE_ATTEMPTS = 3
QUOTE_RETRY_DELAY_SECONDS = 0.25


class CanaryPreflightError(RuntimeError):
    """Raised when a read-only canary proposal cannot pass every guard."""


@dataclass(frozen=True)
class CanaryPreflightRequest:
    direction: BrokerDirection
    instrument: str = "EUR_GBP"
    maximum_loss_gbp: float = 50.0
    reserved_costs_gbp: float = 10.0
    protection_distance_multiplier: int = 5
    maximum_spread_fraction: float = 0.001
    maximum_quote_age_seconds: float = 10.0
    maximum_slippage_fraction: float = 0.0005


@dataclass(frozen=True)
class CanaryPreflightResult:
    status: str
    environment: str
    instrument: str
    direction: str
    units: int
    bid: str
    ask: str
    quote_time: str
    quote_refresh_attempts: int
    proposed_stop_loss: str
    proposed_take_profit: str
    price_bound: str
    gslo_minimum_distance: str
    gslo_execution_premium_gbp: str
    stop_loss_risk_gbp: str
    reserved_costs_gbp: str
    worst_case_loss_gbp: str
    remaining_loss_budget_gbp: str
    maximum_loss_gbp: str
    quote_loss_conversion_factor: str
    account_home_currency: str
    account_open_trade_count: int
    account_pending_order_count: int
    gslo_available: bool
    network_calls_made: int
    broker_orders_submitted: int
    live_orders_submitted: int
    live_canary_build_enabled: bool
    live_execution_locked: bool


Sleeper = Callable[[float], None]


def _decimal(value: object, *, field: str, allow_zero: bool = False) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise CanaryPreflightError(f"OANDA field {field!r} must be decimal.") from error
    if not parsed.is_finite() or parsed < 0 or (parsed == 0 and not allow_zero):
        raise CanaryPreflightError(f"OANDA field {field!r} must be positive and finite.")
    return parsed


def _object(payload: dict[str, object], field: str) -> dict[str, object]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise CanaryPreflightError(f"OANDA response is missing {field!r}.")
    return value


def _price_bucket(price: dict[str, object], field: str) -> str:
    buckets = price.get(field)
    if not isinstance(buckets, list) or not buckets or not isinstance(buckets[0], dict):
        raise CanaryPreflightError(f"OANDA price is missing {field!r}.")
    value = buckets[0].get("price")
    if not isinstance(value, str) or not value:
        raise CanaryPreflightError(f"OANDA price bucket {field!r} is invalid.")
    return value


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CanaryPreflightError("OANDA quote time must be RFC3339 UTC.")
    body = value[:-1]
    if "." in body:
        whole, fraction = body.split(".", 1)
        body = f"{whole}.{fraction[:6]}"
    try:
        return datetime.fromisoformat(body).replace(tzinfo=UTC)
    except ValueError as error:
        raise CanaryPreflightError("OANDA quote time is invalid.") from error


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")


class OandaCanaryReadOnlyPreflight:
    """Build a one-unit proposal using GET requests only."""

    def __init__(
        self,
        *,
        token: str,
        account_id: str,
        opener=None,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        if not account_id.strip():
            raise ValueError("OANDA account ID is required.")
        client_arguments = {"token": token, "account_id": account_id}
        if opener is not None:
            client_arguments["opener"] = opener
        self._client = OandaPracticeReadOnlyClient(**client_arguments)
        self._account_id = account_id
        self._sleeper = sleeper
        self._network_calls = 0

    def _get(self, path: str) -> dict[str, object]:
        self._network_calls += 1
        return self._client._get_json(path)

    def inspect(
        self,
        request: CanaryPreflightRequest,
        *,
        now_utc: datetime | None = None,
    ) -> CanaryPreflightResult:
        """Return a guarded proposal without constructing any order payload."""
        self._network_calls = 0
        if request.instrument.rsplit("_", 1)[-1] != "GBP":
            raise CanaryPreflightError("Exact GBP budgeting requires a GBP-quoted instrument.")
        if request.protection_distance_multiplier < 2:
            raise CanaryPreflightError("Protection distance multiplier must be at least 2.")
        loss_budget = _decimal(request.maximum_loss_gbp, field="maximum_loss_gbp")
        reserved_costs = _decimal(
            request.reserved_costs_gbp,
            field="reserved_costs_gbp",
            allow_zero=True,
        )
        if loss_budget > Decimal("50"):
            raise CanaryPreflightError("Maximum loss cannot exceed GBP 50.")
        if reserved_costs >= loss_budget:
            raise CanaryPreflightError("Reserved costs must be below the loss budget.")
        if now_utc is not None and now_utc.tzinfo is None:
            raise CanaryPreflightError("Preflight time must be timezone-aware.")

        account = quote(self._account_id, safe="-")
        account_payload = self._get(f"/v3/accounts/{account}")
        account_state = _object(account_payload, "account")
        if account_state.get("currency") != "GBP":
            raise CanaryPreflightError("Exact GBP budgeting requires a GBP account.")
        trades = account_state.get("trades", [])
        orders = account_state.get("orders", [])
        if not isinstance(trades, list) or not isinstance(orders, list):
            raise CanaryPreflightError("OANDA account exposure data is invalid.")
        if trades or orders:
            raise CanaryPreflightError("Practice account must have no trades or pending orders.")
        if account_state.get("guaranteedStopLossOrderMode") == "DISABLED":
            raise CanaryPreflightError("Guaranteed stop loss is disabled for this account.")

        pricing_query = urlencode(
            {"instruments": request.instrument, "includeHomeConversions": "true"}
        )
        for quote_attempts in range(1, MAXIMUM_QUOTE_ATTEMPTS + 1):
            pricing = self._get(f"/v3/accounts/{account}/pricing?{pricing_query}")
            prices = pricing.get("prices")
            if not isinstance(prices, list) or len(prices) != 1 or not isinstance(prices[0], dict):
                raise CanaryPreflightError("OANDA returned an invalid price.")
            price = prices[0]
            if price.get("instrument") != request.instrument or price.get("status") != "tradeable":
                raise CanaryPreflightError("Requested instrument is not tradeable.")
            bid_text = _price_bucket(price, "bids")
            ask_text = _price_bucket(price, "asks")
            bid = _decimal(bid_text, field="bid")
            ask = _decimal(ask_text, field="ask")
            midpoint = (bid + ask) / 2
            if ask <= bid or (ask - bid) / midpoint > Decimal(str(request.maximum_spread_fraction)):
                raise CanaryPreflightError("Current spread exceeds the canary limit.")
            checked_at = now_utc or datetime.now(UTC)
            quote_age = (
                checked_at.astimezone(UTC) - _parse_time(price.get("time"))
            ).total_seconds()
            if 0 <= quote_age <= request.maximum_quote_age_seconds:
                break
            if quote_attempts == MAXIMUM_QUOTE_ATTEMPTS:
                raise CanaryPreflightError("Quote remained stale after read-only refreshes.")
            self._sleeper(QUOTE_RETRY_DELAY_SECONDS)

        conversions = pricing.get("homeConversions")
        if not isinstance(conversions, list):
            raise CanaryPreflightError("OANDA did not return home conversions.")
        conversion = next(
            (
                item
                for item in conversions
                if isinstance(item, dict) and item.get("currency") == "GBP"
            ),
            None,
        )
        if conversion is None:
            raise CanaryPreflightError("OANDA did not return the GBP loss conversion.")
        loss_factor = _decimal(conversion.get("accountLoss"), field="accountLoss")
        if loss_factor != 1:
            raise CanaryPreflightError("Quote-to-GBP loss conversion must equal exactly 1.")

        instrument_query = urlencode({"instruments": request.instrument})
        instrument_payload = self._get(f"/v3/accounts/{account}/instruments?{instrument_query}")
        instruments = instrument_payload.get("instruments")
        if (
            not isinstance(instruments, list)
            or len(instruments) != 1
            or not isinstance(instruments[0], dict)
        ):
            raise CanaryPreflightError("OANDA returned invalid instrument details.")
        instrument = instruments[0]
        if instrument.get("name") != request.instrument:
            raise CanaryPreflightError("OANDA returned the wrong instrument details.")
        if instrument.get("guaranteedStopLossOrderMode") in {None, "DISABLED"}:
            raise CanaryPreflightError("Guaranteed stop loss is unavailable.")
        minimum_distance = _decimal(
            instrument.get("minimumGuaranteedStopLossDistance"),
            field="minimumGuaranteedStopLossDistance",
            allow_zero=True,
        )
        premium = _decimal(
            instrument.get("guaranteedStopLossOrderExecutionPremium"),
            field="guaranteedStopLossOrderExecutionPremium",
            allow_zero=True,
        )
        display_precision = instrument.get("displayPrecision")
        if not isinstance(display_precision, int) or display_precision < 1:
            raise CanaryPreflightError("OANDA display precision is invalid.")
        step = Decimal(1).scaleb(-display_precision)
        distance = minimum_distance * request.protection_distance_multiplier
        if request.direction is BrokerDirection.BUY:
            stop = (bid - distance).quantize(step)
            take_profit = (ask + distance).quantize(step)
            entry_reference = ask
            bound = entry_reference * (
                Decimal("1") + Decimal(str(request.maximum_slippage_fraction))
            )
        else:
            stop = (ask + distance).quantize(step)
            take_profit = (bid - distance).quantize(step)
            entry_reference = bid
            bound = entry_reference * (
                Decimal("1") - Decimal(str(request.maximum_slippage_fraction))
            )
        bound = bound.quantize(step)
        stop_risk = abs(bound - stop) * loss_factor
        worst_case = stop_risk + premium + reserved_costs
        if worst_case > loss_budget:
            raise CanaryPreflightError("Proposed worst-case loss exceeds the GBP budget.")

        quote_time = price.get("time")
        assert isinstance(quote_time, str)
        return CanaryPreflightResult(
            status="PREFLIGHT_PASS",
            environment="practice",
            instrument=request.instrument,
            direction=request.direction.value,
            units=1,
            bid=_text(bid),
            ask=_text(ask),
            quote_time=quote_time,
            quote_refresh_attempts=quote_attempts,
            proposed_stop_loss=_text(stop),
            proposed_take_profit=_text(take_profit),
            price_bound=_text(bound),
            gslo_minimum_distance=_text(minimum_distance),
            gslo_execution_premium_gbp=_text(premium),
            stop_loss_risk_gbp=_text(stop_risk),
            reserved_costs_gbp=_text(reserved_costs),
            worst_case_loss_gbp=_text(worst_case),
            remaining_loss_budget_gbp=_text(loss_budget - worst_case),
            maximum_loss_gbp=_text(loss_budget),
            quote_loss_conversion_factor=_text(loss_factor),
            account_home_currency="GBP",
            account_open_trade_count=0,
            account_pending_order_count=0,
            gslo_available=True,
            network_calls_made=self._network_calls,
            broker_orders_submitted=0,
            live_orders_submitted=0,
            live_canary_build_enabled=LIVE_CANARY_BUILD_ENABLED,
            live_execution_locked=True,
        )
