# FX IQ

AI-powered trading research and automation platform.

## Run the dashboard

From the project folder, run `make dashboard`, then open
<http://127.0.0.1:5173>. The launcher checks dependencies and ports, waits for
both services to become healthy, and stops both when you press `Control+C`.

Run `make ai-trial` to exercise the hosted-AI request contract entirely
offline. The trial uses an in-process transport, temporary audit files, and the
same sanitization, quality, hash-chain, and human-review gates as the optional
hosted path. It cannot contact OpenAI or OANDA.

## Safety verification

Run `make check` before committing. It lints the backend, scans every Git-tracked
text file for account identifiers and common API-secret patterns, then runs the
full test suite. Privacy findings report only the file, line, and rule name;
suspected values are never printed. Formatting remains an explicit `make format`
operation and is never performed as a side effect of verification.
