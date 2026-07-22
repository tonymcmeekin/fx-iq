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

Run the non-trading audited operational report:

```bash
python scripts/run_prospective_paper_daily_operation.py --report-only
```

This mode does not collect OANDA data, execute a paper session, alter trading
state, or create a session receipt. It does acquire the operation lock and
append one `REPORT_ONLY` record to
`paper_ledger/daily_operations.jsonl`. If a strictly no-write inspection is
required, run these reports directly instead:

```bash
python scripts/check_prospective_paper_health.py
python scripts/report_prospective_paper_operator_status.py
python scripts/report_passive_observations.py
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

## Scheduled weekday operation

The scheduler-safe launcher runs only Monday through Friday at or after 22:20
Europe/London. It reads only the three OANDA settings from the ignored local
`.env`, requires `OANDA_ENVIRONMENT=practice`, invokes the normal guarded daily
operation for the current London date, and refuses any result that records a
broker order or permits live trading:

```bash
python scripts/run_scheduled_practice_operation.py
```

The configured Codex automation invokes this entry point at 22:20
Europe/London on weekdays. A weekend invocation is a reported no-op. A late,
failed, or missed invocation must be reviewed; the launcher never fabricates or
backdates a prospective session.

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
- Do not connect the prospective paper operation to any broker-order gateway.
- Do not invoke the practice canary rehearsal without separate explicit
  operator approval and its exact confirmation phrase.
- Do not treat paper evidence as permission for live trading.
- Do not bypass preflight, postflight, policy fingerprint, clean-tree, or health
  checks.
- Do not hand-edit ledger hashes, runtime state, candle checkpoints,
  observations, staging files, or recovery receipts.
- Do not commit `.env`, `paper_ledger/`, or `data/prospective_paper/`.

The evidence gate and daily operation must continue to report live trading as
prohibited until a separate reviewed protocol explicitly changes that policy.

## Isolated practice canary rehearsal

The canary gateway is isolated from the prospective strategy. It cannot be
called by the daily operation, accepts exactly one unit, and requires an OANDA
Practice account with no open trades or pending orders. It checks the quote,
submits one protected practice entry, verifies the resulting trade and attached
stop/take-profit orders, immediately closes the trade, and confirms it is no
longer open.

The live gateway constructor is build-locked by
`LIVE_CANARY_BUILD_ENABLED = False`. No environment variable, command-line
flag, API key, account ID, or confirmation phrase can enable the live host in
this build.

After separately approving a rehearsal, calculate protection prices around the
current practice quote and run:

```bash
python scripts/run_oanda_practice_canary_preflight.py \
  --instrument EUR_GBP \
  --direction BUY \
  --maximum-loss-gbp 50 \
  --reserved-costs-gbp 10
```

The preflight command loads only the allow-listed Practice settings from
`.env`, performs GET requests only, proposes protection prices, and prints the
exact GBP allowance. It has no confirmation phrase or order-submission path.
Review its output before separately approving and running the rehearsal:

```bash
python scripts/run_oanda_practice_canary_rehearsal.py \
  --rehearsal-id UNIQUE-ID \
  --instrument EUR_GBP \
  --direction BUY \
  --stop-loss PRICE \
  --take-profit PRICE \
  --maximum-loss-gbp 50 \
  --reserved-costs-gbp 10 \
  --confirmation EXECUTE_ONE_UNIT_OANDA_PRACTICE_REHEARSAL
```

Qualifying rehearsals require a GBP-denominated account, an instrument quoted
directly in GBP, broker-reported GSLO availability and minimum distance, and a
broker loss-conversion factor of exactly 1. The order uses
`guaranteedStopLossOnFill`, not a normal stop. Before submission, the gateway
calculates the worst allowed entry from `priceBound`, loss to the GSLO, the
broker-reported GSLO premium, and the explicit reserved-cost allowance. Their
sum must not exceed £50. Older normal-stop receipts remain in lifetime history
but do not count toward the qualifying GSLO rehearsal streak.

If OANDA initially returns a stale price, the gateway performs at most two
additional GET-only refreshes with a short bounded delay. It never retries an
order submission. A quote that remains stale fails closed before any entry
request is attempted.

Never reuse a rehearsal ID. The gateway checks OANDA for the derived client ID
before price collection or submission. If post-fill verification fails, it
attempts an emergency close and instructs the operator to reconcile the
practice account immediately. A completed result must show two practice broker
actions (entry and close), zero live orders, and a verified closed position.
The final account-wide reconciliation requires no open trades, no pending
orders, zero units on every reported position, and a balance matching the close
fill. New receipts also capture the entry reference and fill prices, exit fill,
signed entry slippage, realized GBP P/L, financing, commission, GSLO execution
fee, net account-balance impact, and quote-refresh count.
Successful results are appended to the ignored, hash-chained runtime audit at
`paper_ledger/canary_rehearsals.jsonl`; no token or raw account ID is stored.
Failed attempts are appended separately to
`paper_ledger/canary_rehearsal_failures.jsonl` with content-safe stage,
request-confirmation, emergency-close, and reconciliation evidence. A failure
that cannot prove there is no remaining exposure is marked for immediate human
action. Any failed attempt resets the dashboard's qualifying rehearsal streak;
the lifetime success count is retained for audit history.
