"""Append verified paper-trade outcomes to passive observations."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.intelligence.outcome_store import enrich_observation_outcomes  # noqa: E402


def main() -> int:
    try:
        result = enrich_observation_outcomes(
            ledger_path=(PROJECT_ROOT / "paper_ledger" / "events.jsonl"),
            observation_path=(
                PROJECT_ROOT
                / "paper_ledger"
                / "intelligence_observations.jsonl"
            ),
            outcome_path=(
                PROJECT_ROOT
                / "paper_ledger"
                / "intelligence_outcomes.jsonl"
            ),
            candle_directory=(
                PROJECT_ROOT / "data" / "prospective_paper"
            ),
        )
    except Exception as error:
        print(
            f"ERROR: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
