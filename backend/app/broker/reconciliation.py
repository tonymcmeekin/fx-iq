from __future__ import annotations

from dataclasses import dataclass

from app.broker.account_models import OandaAccountSnapshot


@dataclass(frozen=True)
class BrokerReconciliationReport:
    internal_open_markets: tuple[str, ...]
    broker_open_markets: tuple[str, ...]
    missing_at_broker: tuple[str, ...]
    unexpected_at_broker: tuple[str, ...]
    is_reconciled: bool
    network_calls_made: int
    broker_orders_submitted: int = 0
    paper_trading_only: bool = True
    live_trading_allowed: bool = False


def _broker_open_markets(
    snapshot: OandaAccountSnapshot,
) -> set[str]:
    markets: set[str] = set()

    for position in snapshot.positions:
        instrument = position.get("instrument")

        if not isinstance(instrument, str) or not instrument:
            raise ValueError(
                "Broker position is missing its instrument."
            )

        markets.add(instrument)

    return markets


def reconcile_open_positions(
    *,
    internal_open_markets: set[str],
    snapshot: OandaAccountSnapshot,
) -> BrokerReconciliationReport:
    if not isinstance(internal_open_markets, set):
        raise ValueError(
            "Internal open markets must be provided as a set."
        )

    if not all(
        isinstance(market, str) and market
        for market in internal_open_markets
    ):
        raise ValueError(
            "Internal open markets must be non-empty strings."
        )

    broker_markets = _broker_open_markets(snapshot)

    missing_at_broker = (
        internal_open_markets - broker_markets
    )

    unexpected_at_broker = (
        broker_markets - internal_open_markets
    )

    return BrokerReconciliationReport(
        internal_open_markets=tuple(
            sorted(internal_open_markets)
        ),
        broker_open_markets=tuple(
            sorted(broker_markets)
        ),
        missing_at_broker=tuple(
            sorted(missing_at_broker)
        ),
        unexpected_at_broker=tuple(
            sorted(unexpected_at_broker)
        ),
        is_reconciled=(
            not missing_at_broker
            and not unexpected_at_broker
        ),
        network_calls_made=(
            snapshot.network_calls_made
        ),
    )
