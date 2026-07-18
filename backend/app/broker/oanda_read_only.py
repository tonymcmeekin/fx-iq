from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.broker.account_models import OandaAccountSnapshot

OANDA_PRACTICE_HOST = "https://api-fxpractice.oanda.com"

OpenUrl = Callable[..., Any]


class OandaReadOnlyError(RuntimeError):
    """Raised when OANDA Practice account state cannot be read safely."""


def _required_string(
    value: object,
    *,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OandaReadOnlyError(
            f"OANDA response field {field!r} must be a non-empty string."
        )

    return value


def _numeric_value(
    value: object,
    *,
    field: str,
) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError) as error:
        raise OandaReadOnlyError(
            f"OANDA response field {field!r} must be numeric."
        ) from error


def _object_list(
    value: object,
    *,
    field: str,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise OandaReadOnlyError(
            f"OANDA response field {field!r} must be a list."
        )

    if not all(isinstance(item, dict) for item in value):
        raise OandaReadOnlyError(
            f"OANDA response field {field!r} must contain objects."
        )

    return tuple(value)


class OandaPracticeReadOnlyClient:
    """
    Read OANDA Practice account state.

    This client exposes GET requests only. It contains no POST, PUT,
    PATCH, DELETE, order submission or position-closing operation.
    """

    def __init__(
        self,
        *,
        token: str,
        account_id: str | None = None,
        timeout_seconds: float = 10.0,
        opener: OpenUrl = urlopen,
    ) -> None:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("OANDA API token is required.")

        if (
            account_id is not None
            and (
                not isinstance(account_id, str)
                or not account_id.strip()
            )
        ):
            raise ValueError(
                "OANDA account ID must be a non-empty string."
            )

        if timeout_seconds <= 0:
            raise ValueError(
                "Timeout must be greater than zero."
            )

        self._token = token
        self._account_id = account_id
        self._timeout_seconds = timeout_seconds
        self._opener = opener

    def _get_json(
        self,
        path: str,
    ) -> dict[str, Any]:
        if not path.startswith("/v3/"):
            raise OandaReadOnlyError(
                "Only OANDA v3 API paths are permitted."
            )

        request = Request(
            url=f"{OANDA_PRACTICE_HOST}{path}",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "Accept-Datetime-Format": "RFC3339",
            },
            method="GET",
        )

        if request.get_method() != "GET":
            raise OandaReadOnlyError(
                "Read-only OANDA client permits GET requests only."
            )

        try:
            with self._opener(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                raw_body = response.read()
        except HTTPError as error:
            raise OandaReadOnlyError(
                f"OANDA returned HTTP {error.code}."
            ) from error
        except URLError as error:
            raise OandaReadOnlyError(
                f"OANDA connection failed: {error.reason}."
            ) from error
        except TimeoutError as error:
            raise OandaReadOnlyError(
                "OANDA request timed out."
            ) from error

        try:
            payload = json.loads(raw_body)
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as error:
            raise OandaReadOnlyError(
                "OANDA returned invalid JSON."
            ) from error

        if not isinstance(payload, dict):
            raise OandaReadOnlyError(
                "OANDA response must be a JSON object."
            )

        return payload

    def list_account_ids(
        self,
    ) -> tuple[str, ...]:
        payload = self._get_json("/v3/accounts")

        accounts = payload.get("accounts")

        if not isinstance(accounts, list):
            raise OandaReadOnlyError(
                "OANDA response is missing the accounts list."
            )

        account_ids: list[str] = []

        for index, account in enumerate(accounts):
            if not isinstance(account, dict):
                raise OandaReadOnlyError(
                    "OANDA accounts list must contain objects."
                )

            account_ids.append(
                _required_string(
                    account.get("id"),
                    field=f"accounts[{index}].id",
                )
            )

        if not account_ids:
            raise OandaReadOnlyError(
                "OANDA token has no accessible Practice accounts."
            )

        return tuple(account_ids)

    def resolve_account_id(
        self,
    ) -> str:
        if self._account_id is not None:
            return self._account_id

        account_ids = self.list_account_ids()

        if len(account_ids) != 1:
            raise OandaReadOnlyError(
                "Multiple OANDA Practice accounts are accessible. "
                "Set OANDA_ACCOUNT_ID explicitly."
            )

        return account_ids[0]

    def get_account_snapshot(
        self,
    ) -> OandaAccountSnapshot:
        account_id = self.resolve_account_id()

        encoded_account_id = quote(
            account_id,
            safe="-",
        )

        payload = self._get_json(
            f"/v3/accounts/{encoded_account_id}"
        )

        account = payload.get("account")

        if not isinstance(account, dict):
            raise OandaReadOnlyError(
                "OANDA response is missing the account object."
            )

        response_account_id = _required_string(
            account.get("id"),
            field="account.id",
        )

        if response_account_id != account_id:
            raise OandaReadOnlyError(
                "OANDA response account ID does not match "
                "the requested account."
            )

        trades = _object_list(
            account.get("trades", []),
            field="account.trades",
        )

        positions = _object_list(
            account.get("positions", []),
            field="account.positions",
        )

        orders = _object_list(
            account.get("orders", []),
            field="account.orders",
        )

        last_transaction_id = payload.get(
            "lastTransactionID"
        )

        if (
            last_transaction_id is not None
            and not isinstance(last_transaction_id, str)
        ):
            raise OandaReadOnlyError(
                "OANDA lastTransactionID must be a string."
            )

        return OandaAccountSnapshot(
            account_id=response_account_id,
            currency=_required_string(
                account.get("currency"),
                field="account.currency",
            ),
            balance=_numeric_value(
                account.get("balance"),
                field="account.balance",
            ),
            nav=_numeric_value(
                account.get("NAV"),
                field="account.NAV",
            ),
            margin_used=_numeric_value(
                account.get("marginUsed", "0"),
                field="account.marginUsed",
            ),
            margin_available=_numeric_value(
                account.get("marginAvailable"),
                field="account.marginAvailable",
            ),
            open_trade_count=len(trades),
            open_position_count=len(positions),
            pending_order_count=len(orders),
            last_transaction_id=last_transaction_id,
            trades=trades,
            positions=positions,
            orders=orders,
        )
