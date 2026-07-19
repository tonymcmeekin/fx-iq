from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class PreflightReport:
    passed: bool
    checks: tuple[PreflightCheck, ...]

    @property
    def failed_checks(self) -> tuple[PreflightCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)
