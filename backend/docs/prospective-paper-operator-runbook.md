# Prospective Paper Operator Runbook

This runbook covers the simulation-only prospective paper workflow. It does
not authorize live trading or broker-order submission.

## Safety invariants

- `OANDA_ENVIRONMENT` must be `practice`.
- The frozen protocol must remain `SIMULATION_ONLY` with
  `live_order_submission_permitted` set to `false`.
- Every operation must finish with `broker_orders_sent` equal to `0`.
- Runtime health must be `HEALTHY` before and after a normal session.
- Tracked source must be clean before a guarded session or recovery.
- Runtime files under `paper_ledger/` and `data/prospective_paper/` must remain
  ignored by Git.
- A pending paper entry or open paper position is not a broker order.

Stop immediately if any invariant fails.

## Local setup

Run commands from the backend directory:

```bash
cd ~/fx-iq/backend
source .venv/bin/activate
set -a
source .env
set +a
export GIT_PAGER=cat
```

The ignored `.env` file must contain an OANDA practice token, its accessible
practice account ID, and:

```text
OANDA_ENVIRONMENT=practice
```

Never paste a token into chat, source control, command-line arguments, terminal
history, logs, receipts, or runtime JSON. If a token is exposed, revoke it in
OANDA, generate a new practice token, and update `.env` locally.

## Start-of-day checks

Confirm the deployed commit and clean tracked source:

```bash
git rev-parse --short HEAD
git status --short
```

Run the read-only operational report:

```bash
python scripts/run_prospective_paper_daily_operation.py --report-only
```

Proceed only when the report says:

- `preflight_health`: `HEALTHY`
- `postflight_health`: `HEALTHY`
- `broker_orders_sent`: `0`
- `observation_integrity_status`: `HEALTHY`
- `safe_to_continue_paper_observation`: `true`
- `safe_for_live_trading`: `false`

## Daily candle timing

Run at most one session date per protocol day. A pending entry can advance only
after OANDA supplies a complete daily candle strictly later than its signal
candle. Do not manufacture, edit, or mark a candle complete manually.

If no later completed candle is available, leaving the entry pending is the
correct outcome. Do not repeatedly create new session dates merely to force a
fill.

## Normal guarded paper operation

Use an explicit ISO session date:

```bash
python scripts/run_prospective_paper_daily_operation.py \
  --use-oanda-practice \
  --session-date YYYY-MM-DD \
  --candle-count 100
```

The wrapper runs health checks, the guarded practice-data session, postflight
health, operator status, daily-operation journaling, and receipt generation.

Afterward, verify passive observations:

```bash
python scripts/report_passive_observations.py
```

The observation report must be `HEALTHY`, with no duplicate IDs, orphaned
session dates, reconciliation mismatches, missing close-event outcomes, or
outcomes referencing unknown close events. Outcomes may remain unpopulated
until a paper position closes. The combined operator report enforces the same
integrity result and blocks further paper observation if it is unhealthy.

## Transactional observation behavior

Observations are first written to a hidden per-session staging JSONL file.
They are published to `paper_ledger/intelligence_observations.jsonl` only after
the ledger/state transition reaches `SESSION_COMPLETED`.

If publication is interrupted after session completion, rerun the same daily
operation. The wrapper detects the staging file and invokes the completed
session idempotently to publish it. This reconciliation is not a new session
and does not create a new receipt.

Do not manually move or merge observation staging files.

## Incomplete-session recovery

Normal operations fail closed when the ledger does not end in
`SESSION_COMPLETED`. Never delete or truncate the ledger manually.

First inspect the recovery plan without changing files:

```bash
python scripts/recover_incomplete_paper_session.py \
  --session-date YYYY-MM-DD
```

The plan is safe only when all target events form one contiguous uncommitted
tail and all of these checks pass:

- no `SESSION_COMPLETED` exists for the target date;
- no transition journal exists;
- runtime state has not completed the target date;
- candle storage exactly matches runtime checkpoints;
- no broker activity is recorded;
- staged observations belong only to the target date;
- tracked source is clean before apply mode.

To recover and retry through the daily wrapper:

```bash
python scripts/run_prospective_paper_daily_operation.py \
  --use-oanda-practice \
  --recover-incomplete-session \
  --session-date YYYY-MM-DD \
  --candle-count 100
```

The wrapper applies recovery only after an unhealthy preflight, requires health
to return to `HEALTHY`, and then runs the normal guarded session.

For an explicitly approved recovery without an immediate retry:

```bash
python scripts/recover_incomplete_paper_session.py \
  --session-date YYYY-MM-DD \
  --apply
```

Apply mode creates a timestamped backup under
`paper_ledger/recovery_backups/` containing the original runtime files and a
hash-bearing `recovery_receipt.json`. Preserve the backup until the replacement
session, health checks, observation report, and full tests all pass.

Recovery must refuse to proceed rather than weaken any guard. Escalate for
manual review if it reports candle/state divergence, broker activity,
non-contiguous events, an active journal, or records from another session.

## Post-incident validation

After recovery or a code fix, run:

```bash
python scripts/check_prospective_paper_health.py
python scripts/report_passive_observations.py
pytest -q -p no:cacheprovider
git diff --check
git status --short
```

Expected outcomes:

- health is `HEALTHY`;
- the latest ledger event is `SESSION_COMPLETED`;
- observations reconcile with completed observation-enabled sessions;
- `broker_orders_sent` remains `0`;
- balances and trading decisions reflect only deterministic paper logic;
- tests pass;
- tracked source is clean after the reviewed fix is committed;
- runtime data remains ignored.

## Prohibited actions

- Do not change the environment to `live`.
- Do not add or invoke broker-order submission code.
- Do not treat paper evidence as permission for live trading.
- Do not bypass preflight, postflight, policy fingerprint, clean-tree, or health
  checks.
- Do not hand-edit ledger hashes, runtime state, candle checkpoints,
  observations, staging files, or recovery receipts.
- Do not commit `.env`, `paper_ledger/`, or `data/prospective_paper/`.

The evidence gate and daily operation must continue to report live trading as
prohibited until a separate reviewed protocol explicitly changes that policy.
