"""Generate a read-only strategy attribution report."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.analytics.ledger_attribution import (
    LedgerAttributionError,
    build_ledger_attribution_report,
)
from app.paper_trading.ledger import LedgerIntegrityError

LEDGER_PATH = Path("paper_ledger/events.jsonl")


class AttributionReportError(RuntimeError):
    """Raised when an attribution report cannot be generated safely."""


def perform_report() -> dict:
    """
    Build an attribution report from the configured verified ledger.

    This function is strictly read-only.
    """
    try:
        return build_ledger_attribution_report(
            LEDGER_PATH,
        )
    except LedgerIntegrityError as error:
        raise AttributionReportError(f"Ledger integrity check failed: {error}") from error
    except LedgerAttributionError as error:
        raise AttributionReportError(f"Ledger attribution failed: {error}") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Generate a verified, read-only paper-trading strategy attribution report.")
    )

    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact JSON instead of indented JSON.",
    )

    return parser


def execute(
    argv: Sequence[str] | None = None,
) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    try:
        report = perform_report()
    except AttributionReportError as error:
        failure = {
            "status": "ERROR",
            "error": str(error),
            "safe_for_live_trading": False,
            "protocol_live_trading_permitted": False,
            "ledger_writes_performed": 0,
            "broker_orders_submitted": 0,
        }

        print(
            json.dumps(
                failure,
                sort_keys=True,
            ),
            file=sys.stderr,
        )

        return 1

    print(
        json.dumps(
            report,
            indent=(None if arguments.compact else 2),
            sort_keys=True,
        )
    )

    return 0


def main() -> None:
    raise SystemExit(execute())


if __name__ == "__main__":
    main()
