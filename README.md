# FX IQ

AI-powered trading research and automation platform.

## Safety verification

Run `make check` before committing. It lints the backend, scans every Git-tracked
text file for account identifiers and common API-secret patterns, then runs the
full test suite. Privacy findings report only the file, line, and rule name;
suspected values are never printed. Formatting remains an explicit `make format`
operation and is never performed as a side effect of verification.
