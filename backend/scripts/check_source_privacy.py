"""Check tracked source without printing any suspected secret value."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIRECTORY.parent

if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIRECTORY))

from app.safety.source_privacy import scan_tracked_source  # noqa: E402


def main() -> int:
    try:
        findings = scan_tracked_source(REPOSITORY_ROOT)
    except RuntimeError as error:
        print(f"SOURCE PRIVACY CHECK ERROR: {error}")
        return 2
    if findings:
        print("SOURCE PRIVACY CHECK FAILED")
        for finding in findings:
            print(f"{finding.path}:{finding.line_number}: {finding.rule}")
        print(f"{len(findings)} sensitive-pattern finding(s); matched values were not printed.")
        return 1
    print("SOURCE PRIVACY CHECK PASSED: no sensitive literals found in tracked source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
