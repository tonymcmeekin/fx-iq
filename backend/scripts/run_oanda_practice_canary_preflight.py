"""Print a GET-only one-unit GSLO proposal for OANDA Practice."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.broker.canary_preflight import (  # noqa: E402
    CanaryPreflightError,
    CanaryPreflightRequest,
    OandaCanaryReadOnlyPreflight,
)
from app.broker.models import BrokerDirection  # noqa: E402
from app.broker.oanda_read_only import OandaReadOnlyError  # noqa: E402
from scripts.run_scheduled_practice_operation import (  # noqa: E402
    ScheduledPracticeError,
    load_local_practice_environment,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect OANDA Practice and propose a one-unit GBP-capped GSLO rehearsal. "
            "This command performs GET requests only and cannot submit an order."
        )
    )
    parser.add_argument("--instrument", default="EUR_GBP")
    parser.add_argument("--direction", choices=["BUY", "SELL"], default="BUY")
    parser.add_argument("--maximum-loss-gbp", type=float, default=50.0)
    parser.add_argument("--reserved-costs-gbp", type=float, default=10.0)
    parser.add_argument("--protection-distance-multiplier", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        environment = load_local_practice_environment()
        report = OandaCanaryReadOnlyPreflight(
            token=environment["OANDA_API_TOKEN"],
            account_id=environment["OANDA_ACCOUNT_ID"],
        ).inspect(
            CanaryPreflightRequest(
                instrument=arguments.instrument,
                direction=BrokerDirection(arguments.direction),
                maximum_loss_gbp=arguments.maximum_loss_gbp,
                reserved_costs_gbp=arguments.reserved_costs_gbp,
                protection_distance_multiplier=arguments.protection_distance_multiplier,
            )
        )
    except (
        CanaryPreflightError,
        OandaReadOnlyError,
        ScheduledPracticeError,
        ValueError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
