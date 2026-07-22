"""Single-position OANDA canary lifecycle with a build-locked live path."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Final
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from app.broker.models import BrokerDirection, BrokerOrderRequest
from app.broker.oanda_payload import build_oanda_market_order_payload
from app.broker.validation import BrokerOrderValidationError

OANDA_PRACTICE_HOST: Final = "https://api-fxpractice.oanda.com"
OANDA_LIVE_HOST: Final = "https://api-fxtrade.oanda.com"
LIVE_CANARY_BUILD_ENABLED: Final = False


class CanaryEnvironment(StrEnum):
    PRACTICE = "practice"
    LIVE = "live"


class CanaryGatewayError(RuntimeError):
    """Raised when any lifecycle guard or broker response fails closed."""


@dataclass(frozen=True)
class CanaryRehearsalRequest:
    rehearsal_id: str
    instrument: str
    direction: BrokerDirection
    stop_loss: float
    take_profit: float
    maximum_spread_fraction: float = 0.001
    maximum_quote_age_seconds: float = 10.0
    maximum_slippage_fraction: float = 0.0005
    maximum_loss_gbp: float = 50.0
    reserved_costs_gbp: float = 10.0
    units: int = 1


@dataclass(frozen=True)
class CanaryRehearsalResult:
    status: str
    environment: str
    rehearsal_id: str
    account_fingerprint: str
    instrument: str
    direction: str
    units: int
    entry_transaction_id: str
    trade_id: str
    close_transaction_id: str
    network_calls_made: int
    practice_entry_orders_submitted: int
    practice_close_orders_submitted: int
    live_orders_submitted: int
    position_verified_open: bool
    position_verified_closed: bool
    live_canary_build_enabled: bool
    guaranteed_stop_loss: bool = True
    account_home_currency: str = "GBP"
    loss_budget_gbp: str = "50"
    reserved_costs_gbp: str = "10"
    stop_loss_risk_gbp: str = "0"
    gslo_premium_gbp: str = "0"
    worst_case_loss_gbp: str = "10"
    remaining_loss_budget_gbp: str = "40"
    quote_loss_conversion_factor: str = "1"
    gslo_minimum_distance: str = "0"
    gslo_execution_premium: str = "0"


@dataclass(frozen=True)
class CanaryFailureContext:
    rehearsal_id: str
    account_fingerprint: str
    stage: str
    failure_type: str
    failure_message: str
    network_calls_made: int
    entry_request_attempted: bool
    entry_order_confirmed: bool
    close_request_attempted: bool
    close_order_confirmed: bool
    emergency_close_attempted: bool
    emergency_close_confirmed: bool
    final_reconciliation_confirmed: bool
    operator_action_required: bool
    live_orders_submitted: int


OpenUrl = Callable[..., Any]


def _required_object(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise CanaryGatewayError(f"OANDA response is missing {field!r}.")
    return value


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise CanaryGatewayError(f"OANDA response is missing {field!r}.")
    return value


def _decimal(value: object, *, field: str, allow_zero: bool = False) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise CanaryGatewayError(f"OANDA field {field!r} must be decimal.") from error
    if not parsed.is_finite() or parsed < 0 or (parsed == 0 and not allow_zero):
        raise CanaryGatewayError(f"OANDA field {field!r} must be positive and finite.")
    return parsed


def _top_price(price: dict[str, Any], field: str) -> str:
    buckets = price.get(field)
    if not isinstance(buckets, list) or not buckets or not isinstance(buckets[0], dict):
        raise CanaryGatewayError(f"OANDA price is missing top-of-book {field!r}.")
    return _required_string(buckets[0], "price")


def _loss_conversion_factor(
    pricing_payload: dict[str, Any],
    price: dict[str, Any],
    *,
    quote_currency: str,
) -> Decimal:
    conversions = pricing_payload.get("homeConversions")
    if isinstance(conversions, list):
        conversion = next(
            (
                item
                for item in conversions
                if isinstance(item, dict) and item.get("currency") == quote_currency
            ),
            None,
        )
        if conversion is not None:
            return _decimal(conversion.get("accountLoss"), field="homeConversions.accountLoss")
    legacy = price.get("quoteHomeConversionFactors")
    if isinstance(legacy, dict):
        return _decimal(legacy.get("negativeUnits"), field="negativeUnits")
    raise CanaryGatewayError("OANDA did not provide a quote-to-home loss conversion factor.")


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CanaryGatewayError("OANDA price time must be an RFC3339 UTC timestamp.")
    body = value[:-1]
    if "." in body:
        whole, fraction = body.split(".", 1)
        body = f"{whole}.{fraction[:6]}"
    try:
        parsed = datetime.fromisoformat(body).replace(tzinfo=UTC)
    except ValueError as error:
        raise CanaryGatewayError("OANDA price time is invalid.") from error
    return parsed


def _client_id(prefix: str, rehearsal_id: str) -> str:
    digest = hashlib.sha256(rehearsal_id.encode()).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _format_bound(price_text: str, value: Decimal) -> str:
    decimals = len(price_text.partition(".")[2])
    return f"{value:.{decimals}f}"


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


class OandaCanaryGateway:
    """Execute one minimal practice lifecycle; live construction always fails."""

    def __init__(
        self,
        *,
        token: str,
        account_id: str,
        environment: CanaryEnvironment = CanaryEnvironment.PRACTICE,
        timeout_seconds: float = 10.0,
        opener: OpenUrl = urlopen,
    ) -> None:
        if environment is CanaryEnvironment.LIVE:
            raise CanaryGatewayError(
                "Live canary execution is build-locked; no runtime setting can enable it."
            )
        if not token.strip() or not account_id.strip():
            raise ValueError("OANDA token and account ID are required.")
        if timeout_seconds <= 0:
            raise ValueError("Timeout must be greater than zero.")
        self._token = token
        self._account_id = account_id
        self._environment = environment
        self._timeout_seconds = timeout_seconds
        self._opener = opener
        self._network_calls = 0
        self._rehearsal_id = "UNKNOWN"
        self._stage = "NOT_STARTED"
        self._entry_request_attempted = False
        self._entry_order_confirmed = False
        self._close_request_attempted = False
        self._close_order_confirmed = False
        self._emergency_close_attempted = False
        self._emergency_close_confirmed = False
        self._final_reconciliation_confirmed = False

    def failure_context(self, error: BaseException) -> CanaryFailureContext:
        """Return content-safe evidence for a failed or interrupted rehearsal."""
        message = " ".join(str(error).split())[:500] or type(error).__name__
        unresolved_entry = self._entry_request_attempted and not self._entry_order_confirmed
        unresolved_trade = self._entry_order_confirmed and not (
            self._close_order_confirmed and self._final_reconciliation_confirmed
        )
        return CanaryFailureContext(
            rehearsal_id=self._rehearsal_id,
            account_fingerprint=hashlib.sha256(self._account_id.encode()).hexdigest(),
            stage=self._stage,
            failure_type=type(error).__name__,
            failure_message=message,
            network_calls_made=self._network_calls,
            entry_request_attempted=self._entry_request_attempted,
            entry_order_confirmed=self._entry_order_confirmed,
            close_request_attempted=self._close_request_attempted,
            close_order_confirmed=self._close_order_confirmed,
            emergency_close_attempted=self._emergency_close_attempted,
            emergency_close_confirmed=self._emergency_close_confirmed,
            final_reconciliation_confirmed=self._final_reconciliation_confirmed,
            operator_action_required=unresolved_entry or unresolved_trade,
            live_orders_submitted=0,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        allow_not_found: bool = False,
        request_id: str | None = None,
    ) -> dict[str, Any] | None:
        if self._environment is not CanaryEnvironment.PRACTICE:
            raise CanaryGatewayError("Only OANDA practice transport is compiled.")
        if not path.startswith("/v3/"):
            raise CanaryGatewayError("Only OANDA v3 API paths are permitted.")
        if method not in {"GET", "POST", "PUT"}:
            raise CanaryGatewayError("Unsupported canary HTTP method.")
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Accept-Datetime-Format": "RFC3339",
        }
        encoded = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        if request_id is not None:
            headers["ClientRequestID"] = request_id
        request = Request(
            f"{OANDA_PRACTICE_HOST}{path}",
            data=encoded,
            headers=headers,
            method=method,
        )
        self._network_calls += 1
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
        except HTTPError as error:
            if allow_not_found and error.code == 404:
                return None
            raise CanaryGatewayError(f"OANDA returned HTTP {error.code}.") from error
        except URLError as error:
            raise CanaryGatewayError(f"OANDA connection failed: {error.reason}.") from error
        except TimeoutError as error:
            raise CanaryGatewayError("OANDA request timed out.") from error
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise CanaryGatewayError("OANDA returned invalid JSON.") from error
        if not isinstance(payload, dict):
            raise CanaryGatewayError("OANDA response must be a JSON object.")
        return payload

    def _close_trade(
        self,
        *,
        account: str,
        trade_id: str,
        request_id: str,
    ) -> str:
        self._close_request_attempted = True
        closed = self._request_json(
            "PUT",
            f"/v3/accounts/{account}/trades/{quote(trade_id, safe='-')}/close",
            body={"units": "ALL"},
            request_id=request_id,
        )
        assert closed is not None
        close_fill = _required_object(closed, "orderFillTransaction")
        transaction_id = _required_string(close_fill, "id")
        self._close_order_confirmed = True
        return transaction_id

    def _recover_created_trade(
        self,
        *,
        account: str,
        order_client_id: str,
        creation_error: CanaryGatewayError,
    ) -> tuple[str, str]:
        recovered = self._request_json(
            "GET",
            f"/v3/accounts/{account}/orders/@{order_client_id}",
            allow_not_found=True,
        )
        if recovered is None:
            raise creation_error
        order = _required_object(recovered, "order")
        if order.get("state") != "FILLED":
            raise CanaryGatewayError(
                "Practice entry response was lost and the client order was not verified filled."
            ) from creation_error
        return (
            _required_string(order, "fillingTransactionID"),
            _required_string(order, "tradeOpenedID"),
        )

    def rehearse(
        self,
        request: CanaryRehearsalRequest,
        *,
        now_utc: datetime | None = None,
    ) -> CanaryRehearsalResult:
        """Open, verify, close, and reconcile exactly one unit in practice."""
        self._rehearsal_id = request.rehearsal_id
        self._stage = "LOCAL_VALIDATION"
        if request.units != 1:
            raise CanaryGatewayError("Canary rehearsals are fixed at exactly one unit.")
        if not request.rehearsal_id.strip():
            raise CanaryGatewayError("A rehearsal ID is required.")
        if request.maximum_spread_fraction <= 0:
            raise CanaryGatewayError("Maximum spread fraction must be positive.")
        if request.maximum_quote_age_seconds <= 0:
            raise CanaryGatewayError("Maximum quote age must be positive.")
        if request.maximum_slippage_fraction <= 0:
            raise CanaryGatewayError("Maximum slippage fraction must be positive.")
        loss_budget_gbp = _decimal(request.maximum_loss_gbp, field="maximum_loss_gbp")
        reserved_costs_gbp = _decimal(
            request.reserved_costs_gbp,
            field="reserved_costs_gbp",
            allow_zero=True,
        )
        if loss_budget_gbp > Decimal("50"):
            raise CanaryGatewayError("Canary maximum loss budget cannot exceed GBP 50.")
        if reserved_costs_gbp >= loss_budget_gbp:
            raise CanaryGatewayError("Reserved costs must remain below the total GBP loss budget.")

        broker_request = BrokerOrderRequest(
            instrument=request.instrument,
            direction=request.direction,
            units=1,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
        )
        try:
            payload = build_oanda_market_order_payload(broker_request).order
        except BrokerOrderValidationError as error:
            raise CanaryGatewayError(str(error)) from error

        account = quote(self._account_id, safe="-")
        self._stage = "ACCOUNT_PREFLIGHT"
        account_payload = self._request_json("GET", f"/v3/accounts/{account}")
        assert account_payload is not None
        account_state = _required_object(account_payload, "account")
        if account_state.get("currency") != "GBP":
            raise CanaryGatewayError("Exact GBP loss budgeting requires a GBP account.")
        if account_state.get("guaranteedStopLossOrderMode") == "DISABLED":
            raise CanaryGatewayError("This practice account has guaranteed stop losses disabled.")
        for field in ("trades", "orders"):
            value = account_state.get(field, [])
            if not isinstance(value, list) or value:
                raise CanaryGatewayError(
                    "Practice canary requires an account with no open trades or pending orders."
                )

        order_client_id = _client_id("canary", request.rehearsal_id)
        self._stage = "DUPLICATE_PREFLIGHT"
        existing = self._request_json(
            "GET",
            f"/v3/accounts/{account}/orders/@{order_client_id}",
            allow_not_found=True,
        )
        if existing is not None:
            raise CanaryGatewayError(
                "This rehearsal ID already exists at OANDA; no duplicate order was submitted."
            )

        query = urlencode(
            {
                "instruments": request.instrument,
                "includeHomeConversions": "true",
            }
        )
        self._stage = "PRICE_PREFLIGHT"
        pricing_payload = self._request_json("GET", f"/v3/accounts/{account}/pricing?{query}")
        assert pricing_payload is not None
        prices = pricing_payload.get("prices")
        if not isinstance(prices, list) or len(prices) != 1 or not isinstance(prices[0], dict):
            raise CanaryGatewayError("OANDA returned an invalid canary price.")
        price = prices[0]
        if price.get("instrument") != request.instrument or price.get("status") != "tradeable":
            raise CanaryGatewayError("The requested instrument is not tradeable.")
        ask_text = _top_price(price, "asks")
        bid_text = _top_price(price, "bids")
        ask = _decimal(ask_text, field="asks[0].price")
        bid = _decimal(bid_text, field="bids[0].price")
        midpoint = (ask + bid) / 2
        if ask <= bid or (ask - bid) / midpoint > Decimal(str(request.maximum_spread_fraction)):
            raise CanaryGatewayError("Current practice spread exceeds the canary limit.")
        resolved_now = now_utc or datetime.now(UTC)
        if resolved_now.tzinfo is None:
            raise CanaryGatewayError("Canary time must be timezone-aware.")
        quote_age = (resolved_now.astimezone(UTC) - _parse_time(price.get("time"))).total_seconds()
        if quote_age < 0 or quote_age > request.maximum_quote_age_seconds:
            raise CanaryGatewayError("OANDA canary quote is stale.")

        quote_currency = request.instrument.rsplit("_", 1)[-1]
        if quote_currency != "GBP":
            raise CanaryGatewayError(
                "Exact GBP loss budgeting requires an instrument quoted directly in GBP."
            )
        loss_conversion_factor = _loss_conversion_factor(
            pricing_payload,
            price,
            quote_currency=quote_currency,
        )
        if loss_conversion_factor != Decimal("1"):
            raise CanaryGatewayError(
                "The broker quote-to-GBP loss conversion factor must equal exactly 1."
            )

        self._stage = "GSLO_PREFLIGHT"
        instrument_query = urlencode({"instruments": request.instrument})
        instrument_payload = self._request_json(
            "GET",
            f"/v3/accounts/{account}/instruments?{instrument_query}",
        )
        assert instrument_payload is not None
        instruments = instrument_payload.get("instruments")
        if (
            not isinstance(instruments, list)
            or len(instruments) != 1
            or not isinstance(instruments[0], dict)
        ):
            raise CanaryGatewayError("OANDA returned invalid canary instrument details.")
        instrument = instruments[0]
        if instrument.get("name") != request.instrument:
            raise CanaryGatewayError("OANDA returned the wrong canary instrument details.")
        if instrument.get("guaranteedStopLossOrderMode") in {None, "DISABLED"}:
            raise CanaryGatewayError("Guaranteed stop loss is unavailable for this instrument.")
        gslo_premium_price = _decimal(
            instrument.get("guaranteedStopLossOrderExecutionPremium"),
            field="guaranteedStopLossOrderExecutionPremium",
            allow_zero=True,
        )
        gslo_minimum_distance = _decimal(
            instrument.get("minimumGuaranteedStopLossDistance"),
            field="minimumGuaranteedStopLossDistance",
            allow_zero=True,
        )

        order = payload["order"]
        entry_price = ask if request.direction is BrokerDirection.BUY else bid
        stop_loss = Decimal(str(request.stop_loss))
        if request.direction is BrokerDirection.BUY:
            if stop_loss >= bid or Decimal(str(request.take_profit)) <= ask:
                raise CanaryGatewayError("BUY protection prices do not bracket the live quote.")
            bound = entry_price * (Decimal("1") + Decimal(str(request.maximum_slippage_fraction)))
        else:
            if stop_loss <= ask or Decimal(str(request.take_profit)) >= bid:
                raise CanaryGatewayError("SELL protection prices do not bracket the live quote.")
            bound = entry_price * (Decimal("1") - Decimal(str(request.maximum_slippage_fraction)))
        stop_trigger_reference = bid if request.direction is BrokerDirection.BUY else ask
        if abs(stop_trigger_reference - stop_loss) < gslo_minimum_distance:
            raise CanaryGatewayError("Guaranteed stop loss is inside OANDA's minimum distance.")
        bound_text = _format_bound(
            ask_text if request.direction is BrokerDirection.BUY else bid_text,
            bound,
        )
        worst_entry_price = Decimal(bound_text)
        stop_loss_risk_gbp = (
            abs(worst_entry_price - stop_loss) * Decimal(request.units) * loss_conversion_factor
        )
        gslo_premium_gbp = gslo_premium_price * Decimal(request.units) * loss_conversion_factor
        worst_case_loss_gbp = stop_loss_risk_gbp + gslo_premium_gbp + reserved_costs_gbp
        if worst_case_loss_gbp > loss_budget_gbp:
            raise CanaryGatewayError(
                "Worst-case GSLO loss, premium, and reserved costs exceed the GBP budget."
            )
        remaining_loss_budget_gbp = loss_budget_gbp - worst_case_loss_gbp

        order["priceBound"] = bound_text
        stop_details = order.pop("stopLossOnFill")
        order["guaranteedStopLossOnFill"] = stop_details
        order["clientExtensions"] = {"id": order_client_id, "tag": "trade_iq_canary"}
        order["tradeClientExtensions"] = {
            "id": _client_id("trade", request.rehearsal_id),
            "tag": "trade_iq_canary",
        }

        self._stage = "ENTRY_SUBMISSION"
        self._entry_request_attempted = True
        try:
            created = self._request_json(
                "POST",
                f"/v3/accounts/{account}/orders",
                body=payload,
                request_id=order_client_id,
            )
            assert created is not None
            fill = _required_object(created, "orderFillTransaction")
            entry_transaction_id = _required_string(fill, "id")
            opened = fill.get("tradeOpened")
            if isinstance(opened, dict):
                trade_id = _required_string(opened, "tradeID")
            else:
                trade_id = _required_string(fill, "tradeOpenedID")
            self._entry_order_confirmed = True
        except CanaryGatewayError as creation_error:
            entry_transaction_id, trade_id = self._recover_created_trade(
                account=account,
                order_client_id=order_client_id,
                creation_error=creation_error,
            )
            self._entry_order_confirmed = True

        self._stage = "PROTECTION_VERIFICATION"
        try:
            trade_payload = self._request_json(
                "GET", f"/v3/accounts/{account}/trades/{quote(trade_id, safe='-')}"
            )
            assert trade_payload is not None
            trade = _required_object(trade_payload, "trade")
            if trade.get("state") != "OPEN" or trade.get("instrument") != request.instrument:
                raise CanaryGatewayError("Practice canary trade was not verified open.")
            if not isinstance(trade.get("guaranteedStopLossOrder"), dict) or not isinstance(
                trade.get("takeProfitOrder"), dict
            ):
                raise CanaryGatewayError(
                    "Practice canary guaranteed stop and take-profit orders were not attached."
                )

            self._stage = "CLOSE_SUBMISSION"
            close_transaction_id = self._close_trade(
                account=account,
                trade_id=trade_id,
                request_id=_client_id("close", request.rehearsal_id),
            )
        except CanaryGatewayError as lifecycle_error:
            try:
                self._stage = "EMERGENCY_CLOSE"
                self._emergency_close_attempted = True
                self._close_trade(
                    account=account,
                    trade_id=trade_id,
                    request_id=_client_id("emergency", request.rehearsal_id),
                )
                self._emergency_close_confirmed = True
            except CanaryGatewayError as emergency_error:
                raise CanaryGatewayError(
                    "Practice canary lifecycle failed and emergency close could not be "
                    "confirmed; inspect the practice account immediately."
                ) from emergency_error
            raise CanaryGatewayError(
                f"{lifecycle_error} Emergency close was submitted and must be reconciled."
            ) from lifecycle_error

        self._stage = "FINAL_RECONCILIATION"
        final_payload = self._request_json("GET", f"/v3/accounts/{account}/openTrades")
        assert final_payload is not None
        final_trades = final_payload.get("trades")
        if not isinstance(final_trades, list):
            raise CanaryGatewayError("OANDA final trade reconciliation is invalid.")
        if any(isinstance(item, dict) and item.get("id") == trade_id for item in final_trades):
            raise CanaryGatewayError("Practice canary trade remains open after close request.")
        self._final_reconciliation_confirmed = True
        self._stage = "COMPLETE"

        account_fingerprint = hashlib.sha256(self._account_id.encode()).hexdigest()
        return CanaryRehearsalResult(
            status="PRACTICE_REHEARSAL_COMPLETE",
            environment=self._environment.value,
            rehearsal_id=request.rehearsal_id,
            account_fingerprint=account_fingerprint,
            instrument=request.instrument,
            direction=request.direction.value,
            units=1,
            entry_transaction_id=entry_transaction_id,
            trade_id=trade_id,
            close_transaction_id=close_transaction_id,
            network_calls_made=self._network_calls,
            practice_entry_orders_submitted=1,
            practice_close_orders_submitted=1,
            live_orders_submitted=0,
            position_verified_open=True,
            position_verified_closed=True,
            live_canary_build_enabled=LIVE_CANARY_BUILD_ENABLED,
            guaranteed_stop_loss=True,
            account_home_currency="GBP",
            loss_budget_gbp=_decimal_text(loss_budget_gbp),
            reserved_costs_gbp=_decimal_text(reserved_costs_gbp),
            stop_loss_risk_gbp=_decimal_text(stop_loss_risk_gbp),
            gslo_premium_gbp=_decimal_text(gslo_premium_gbp),
            worst_case_loss_gbp=_decimal_text(worst_case_loss_gbp),
            remaining_loss_budget_gbp=_decimal_text(remaining_loss_budget_gbp),
            quote_loss_conversion_factor=_decimal_text(loss_conversion_factor),
            gslo_minimum_distance=_decimal_text(gslo_minimum_distance),
            gslo_execution_premium=_decimal_text(gslo_premium_price),
        )
