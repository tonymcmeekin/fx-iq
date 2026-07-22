"""Print a read-only passive-observation integrity report."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.intelligence.reporting import build_observation_report  # noqa: E402

LEDGER_PATH = PROJECT_ROOT / "paper_ledger" / "events.jsonl"
OBSERVATION_PATH = (
    PROJECT_ROOT / "paper_ledger" / "intelligence_observations.jsonl"
)


def main() -> int:
    try:
        report = build_observation_report(
            ledger_path=LEDGER_PATH,
            observation_path=OBSERVATION_PATH,
        )
    except Exception as error:
        print(
            f"ERROR: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "HEALTHY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
