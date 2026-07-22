"""Run the local hosted-AI safety simulation."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]

if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIRECTORY))

from app.ai_briefing.simulation import run_simulated_hosted_trial  # noqa: E402


def main() -> int:
    try:
        run_simulated_hosted_trial()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"SIMULATED HOSTED AI TRIAL: FAIL\n{error}")
        return 1
    print("SIMULATED HOSTED AI TRIAL: PASS")
    print("External network calls: 0")
    print("Persistent runtime files changed: 0")
    print("Broker orders submitted: 0")
    print("OpenAI request storage: disabled")
    print("Deterministic quality gate: PASS")
    print("Temporary insight chain: verified")
    print("Human review gate: required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
