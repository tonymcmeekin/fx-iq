"""Fail-closed scanning for sensitive literals in tracked source files."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourcePrivacyFinding:
    path: str
    line_number: int
    rule: str


_LINE_PATTERNS = (
    (
        "oanda_account_identifier",
        re.compile(r"(?<!\d)(?!999-)\d{3}-\d{3}-\d{8}-\d{3}(?!\d)"),
    ),
    (
        "openai_api_key",
        re.compile(r"(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{16,}"),
    ),
    (
        "github_access_token",
        re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{36,}"),
    ),
    (
        "aws_access_key_id",
        re.compile(r"(?<![A-Z0-9])AKIA[A-Z0-9]{16}(?![A-Z0-9])"),
    ),
    (
        "private_key_block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+)?"
    r"(?:OANDA_API_TOKEN|OANDA_ACCOUNT_ID|OPENAI_API_KEY)\s*=\s*"
    r"[\"']?([^\s\"'#]+)"
)
_PLACEHOLDER_PREFIXES = (
    "<",
    "${",
    "dummy",
    "example",
    "placeholder",
    "replace",
    "test-",
    "your_",
    "999-",
)


def scan_source_text(path: str, text: str) -> list[SourcePrivacyFinding]:
    """Return safe metadata only; never retain or report matched text."""
    findings = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in _LINE_PATTERNS:
            if pattern.search(line):
                findings.append(SourcePrivacyFinding(path, line_number, rule))
        assignment = _SENSITIVE_ASSIGNMENT.match(line)
        if assignment and not assignment.group(1).lower().startswith(_PLACEHOLDER_PREFIXES):
            findings.append(
                SourcePrivacyFinding(path, line_number, "configured_sensitive_environment_value")
            )
    return findings


def tracked_source_paths(repository_root: Path) -> list[Path]:
    """Resolve only Git-tracked files so ignored runtime data is never opened."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repository_root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError("Tracked source files could not be enumerated.") from error
    return [
        repository_root / value.decode("utf-8") for value in result.stdout.split(b"\0") if value
    ]


def scan_tracked_source(repository_root: Path) -> list[SourcePrivacyFinding]:
    findings = []
    for path in tracked_source_paths(repository_root):
        try:
            content = path.read_bytes()
        except OSError as error:
            raise RuntimeError(f"Tracked source could not be read: {path.name}") from error
        if b"\0" in content:
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(scan_source_text(str(path.relative_to(repository_root)), text))
    return findings
