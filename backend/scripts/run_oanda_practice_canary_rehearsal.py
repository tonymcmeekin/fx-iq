"""Explicitly rehearse one open/verify/close lifecycle on OANDA Practice."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.broker.canary_audit import CanaryAuditError, append_canary_audit  # noqa: E402
from app.broker.canary_gateway import (  # noqa: E402
    CanaryGatewayError,
    CanaryRehearsalRequest,
    OandaCanaryGateway,
)
from app.broker.models import BrokerDirection  # noqa: E402

CONFIRMATION = "EXECUTE_ONE_UNIT_OANDA_PRACTICE_REHEARSAL"
AUDIT_PATH = PROJECT_ROOT / "paper_ledger" / "canary_rehearsals.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Open, verify, and immediately close exactly one unit on OANDA Practice. "
            "The live canary path remains build-locked."
        )
    )
    parser.add_argument("--rehearsal-id", required=True)
    parser.add_argument("--instrument", required=True)
    parser.add_argument("--direction", choices=["BUY", "SELL"], required=True)
    parser.add_argument("--stop-loss", type=float, required=True)
    parser.add_argument("--take-profit", type=float, required=True)
    parser.add_argument("--confirmation", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.confirmation != CONFIRMATION:
        print("ERROR: Exact practice-rehearsal confirmation was not supplied.", file=sys.stderr)
        return 2
    if os.environ.get("OANDA_ENVIRONMENT") != "practice":
        print("ERROR: OANDA_ENVIRONMENT must be exactly 'practice'.", file=sys.stderr)
        return 2
    token = os.environ.get("OANDA_API_TOKEN", "")
    account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
    try:
        result = OandaCanaryGateway(token=token, account_id=account_id).rehearse(
            CanaryRehearsalRequest(
                rehearsal_id=arguments.rehearsal_id,
                instrument=arguments.instrument,
                direction=BrokerDirection(arguments.direction),
                stop_loss=arguments.stop_loss,
                take_profit=arguments.take_profit,
            )
        )
        audit, created = append_canary_audit(AUDIT_PATH, result)
    except (CanaryAuditError, CanaryGatewayError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    output = asdict(result)
    output["audit_status"] = "CREATED" if created else "EXISTING"
    output["audit_record_hash"] = audit["record_hash"]
    output["audit_path"] = str(AUDIT_PATH.relative_to(PROJECT_ROOT))
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
