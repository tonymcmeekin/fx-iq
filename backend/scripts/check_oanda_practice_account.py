from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.broker import (  # noqa: E402
    OandaPracticeReadOnlyClient,
    OandaReadOnlyError,
)


def main() -> int:
    token = os.getenv("OANDA_API_TOKEN", "")
    account_id = os.getenv("OANDA_ACCOUNT_ID") or None

    if not token:
        print(
            "ERROR: OANDA_API_TOKEN is not set.",
            file=sys.stderr,
        )
        return 1

    try:
        client = OandaPracticeReadOnlyClient(
            token=token,
            account_id=account_id,
        )

        snapshot = client.get_account_snapshot()
    except OandaReadOnlyError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        return 1

    output = asdict(snapshot)

    output["trades"] = list(snapshot.trades)
    output["positions"] = list(snapshot.positions)
    output["orders"] = list(snapshot.orders)

    print(
        json.dumps(
            output,
            indent=2,
            sort_keys=True,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
