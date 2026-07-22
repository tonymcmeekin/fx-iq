# External FX Platform Benchmark

Status: initial product-research baseline  
Research date: 2026-07-22  
Scope: product capabilities, operator workflows, risk controls, analytics, and
research tooling  
Out of scope: competitor trading performance, investment recommendations, and
authorization of live trading

## Purpose

This benchmark identifies product patterns that could improve Trade IQ without
changing its frozen prospective paper-trading protocol. Competitor features are
inputs to product design only. They are not evidence that a trading strategy is
profitable, safe, or suitable for live capital.

Trade IQ's differentiator should remain controlled, explainable evidence
collection. New product features must preserve these invariants:

- simulation-only operation unless a separately reviewed protocol says
  otherwise;
- no broker-order submission from the current system;
- deterministic decisions tied to a frozen policy fingerprint;
- append-only, reconcilable observations and outcomes;
- explicit separation of research, observation, and execution concerns;
- fail-closed behavior when data, state, or evidence integrity is uncertain.

## Method

The initial review uses official platform and help documentation. Each platform
is evaluated on six dimensions:

1. risk controls;
2. research and analysis;
3. paper-to-market workflow;
4. alerts and monitoring;
5. performance learning;
6. product structure and operator clarity.

Scores are qualitative product-research judgments from 1 (limited evidence in
the reviewed sources) to 5 (strong, explicit capability). They compare product
patterns, not broker quality or expected user profitability.

## Platform summaries

### OANDA

Observed capabilities:

- web and mobile trading, TradingView integration, and MetaTrader 4 support;
- technical-analysis tools, configurable layouts, alerts, and chart-based
  trading;
- trade-performance analytics intended to help users understand behavior and
  risk;
- correlation, volatility, currency-strength, sentiment, and Value-at-Risk
  tools;
- demo accounts and API-driven automation options.

Relevant sources:

- [OANDA trading platforms](https://www.oanda.com/ca-en/platforms/)
- [OANDA Labs risk and analysis tools](https://www.oanda.com/us-en/skills-and-insights/oanda-labs/)
- [OANDA performance-management integration](https://www.oanda.com/group/media-center/press-releases/oanda-and-chasing-returns-announce-integration/)

Trade IQ lesson: elevate portfolio context and post-trade behavioral learning
to the same prominence as signal generation. Correlation and exposure views
would be more valuable than simply adding more indicators.

### IG

Observed capabilities:

- normal, guaranteed, and trailing stop choices;
- limit orders and risk-per-trade/risk-reward guidance;
- price-level, price-change, technical-indicator, and economic-event alerts;
- delivery through platform notifications, email, and mobile push;
- visible balance, profit, and loss context.

Relevant sources:

- [IG risk-management overview](https://www.ig.com/en/risk-management)
- [IG stop configuration](https://www.ig.com/en/help-and-support/articles/682424-how-do-i-apply-a-stop-on-the-ig-trading-platform)
- [IG alert types and delivery](https://www.ig.com/en/help-and-support/articles/682168-how-do-i-use-alerts)

Trade IQ lesson: alerts should communicate state transitions and safety
conditions, not merely price movement. A useful alert must say what changed,
which frozen policy produced it, and whether operator action is required.

### TradingView

Observed capabilities:

- paper trading with simulated money against market data;
- order tickets, chart trading, and depth-of-market workflows;
- alerts based on price, indicators, strategies, drawings, and chart patterns;
- server-side strategy alerts that preserve a copy of the strategy and its
  settings at creation time;
- multiple notification channels and explicit alert frequency/expiration;
- historical strategy calculation followed by real-time alerting.

Relevant sources:

- [TradingView paper trading](https://www.tradingview.com/support/solutions/43000516466-paper-trading-main-functionality/)
- [TradingView strategy alerts](https://www.tradingview.com/support/solutions/43000481368-strategy-alerts/)
- [TradingView technical alerts](https://www.tradingview.com/support/solutions/43000763315-getting-started-with-technical-alerts/)
- [TradingView alert configuration](https://www.tradingview.com/support/solutions/43000763312-learn-how-to-configure-alerts/)

Trade IQ lesson: every alert or experiment should be pinned to an immutable
configuration snapshot. Editing a strategy after an alert is created must not
silently change the meaning of that alert.

### cTrader

Observed capabilities:

- explicit Trade, Copy, Algo, and Analyze applications;
- account-level performance, equity, volume, win/loss, history, and
  symbol-specific analytics;
- watchlists, charts, positions, orders, account metrics, market hours, and
  connection latency in a unified operator workspace;
- separate accounts for copied strategies and equity-scaled copy allocation;
- creation of algorithmic tools separated from normal trading workflows.

Relevant sources:

- [cTrader applications and layouts](https://help.ctrader.com/ctrader/interface/basics-and-layouts/)
- [cTrader Analyze](https://help.ctrader.com/ctrader-analyze/)
- [cTrader Copy model](https://help.ctrader.com/ctrader-copy/)

Trade IQ lesson: use distinct workspaces for observation, research, and
evidence review. Trade IQ should adopt the separation principle, not copy
social-trading or strategy-provider mechanics.

### MetaTrader 5

Observed capabilities:

- multi-currency strategy testing and optimization;
- historical and forward-test partitions;
- visual strategy replay and detailed test journals;
- local, remote, and cloud-backed test agents;
- integrated algorithm and custom-indicator development.

Relevant sources:

- [MetaTrader 5 platform manual](https://www.metatrader5.com/en/terminal/help)
- [MetaTrader 5 strategy testing](https://www.metatrader5.com/en/terminal/help/algotrading/testing)

Trade IQ lesson: build a controlled research laboratory with reproducible
experiment manifests, forward-validation splits, and visual review. Research
results must never automatically modify or promote the frozen prospective
protocol.

## Comparative matrix

| Platform | Risk controls | Research and analysis | Paper-to-market workflow | Alerts and monitoring | Performance learning | Product separation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| OANDA | 4 | 4 | 4 | 4 | 4 | 3 |
| IG | 5 | 3 | 3 | 5 | 3 | 3 |
| TradingView | 3 | 5 | 5 | 5 | 3 | 4 |
| cTrader | 4 | 4 | 4 | 4 | 5 | 5 |
| MetaTrader 5 | 3 | 5 | 4 | 3 | 4 | 4 |

The scores indicate where a platform offers a useful design reference. They
must not be added together to produce a platform ranking.

## Trade IQ gap analysis

### Existing strengths

- frozen simulation-only protocol and policy fingerprint;
- guarded practice-data collection;
- deterministic candidate and shadow accounts;
- recoverable state transitions and hash-verified ledger;
- append-only passive observations and outcomes;
- portfolio-aware acceptance semantics;
- combined health, operator, evidence, readiness, and integrity reports;
- visible prohibition of live trading and broker orders.

### Important gaps

1. The dashboard reports aggregate health but lacks a dedicated experiment
   manifest showing the exact code, policy, data window, and session lineage.
2. Operational alerts are not yet delivered when a candle becomes available,
   a position changes state, or an integrity check blocks operation.
3. Outcome analytics are stored and summarized but not yet explored by regime,
   setup quality, holding period, or excursion distribution.
4. Portfolio context does not yet provide correlation clusters, concentrated
   currency exposure, or scenario stress views.
5. Research experiments do not yet have a separate, reproducible laboratory
   with train/validation/forward partitions.
6. There is no structured operator review workflow for annotating decisions
   without changing the immutable evidence.

## Feature-priority matrix

Scores use 1 (low) to 5 (high). Evidence risk estimates how likely a feature is
to contaminate, overfit, or confuse prospective evidence; lower is better.

| Priority | Feature | User value | Safety value | Effort | Evidence risk | Recommendation |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| P0 | Experiment manifest and session lineage panel | 5 | 5 | 2 | 1 | Build next |
| P0 | Complete-candle and integrity alerts | 5 | 5 | 3 | 1 | Design next; keep notification-only |
| P0 | Portfolio exposure and correlation view | 5 | 5 | 3 | 2 | Build from read-only evidence |
| P1 | Outcome explorer by market, regime, setup, and exit | 5 | 4 | 3 | 2 | Activate as outcomes accumulate |
| P1 | MFE/MAE and holding-period distributions | 4 | 4 | 2 | 2 | Extend current outcome reporting |
| P1 | Operator annotations in a separate append-only store | 4 | 4 | 3 | 2 | Never edit observations or ledger |
| P1 | Strategy-version-pinned alert definitions | 4 | 5 | 3 | 1 | Require immutable fingerprints |
| P2 | Reproducible research-lab manifests | 5 | 4 | 4 | 3 | Strictly separate from prospective data |
| P2 | Walk-forward and multi-market validation | 5 | 4 | 5 | 4 | Require predeclared evaluation rules |
| P3 | Visual candle-by-candle replay | 3 | 3 | 4 | 2 | Useful for review, not urgent |
| Do not build | One-click live execution | 2 | 1 | 4 | 5 | Conflicts with current protocol |
| Do not build | Social/copy trading | 2 | 1 | 5 | 5 | Outside product thesis |
| Do not build | Unbounded indicator marketplace | 2 | 1 | 5 | 5 | Increases noise and overfitting risk |

## Recommended implementation sequence

### Phase 1: evidence cockpit

Create a read-only experiment panel containing:

- current software commit and policy fingerprint;
- protocol mode and explicit live-order prohibition;
- last complete candle per market and freshness status;
- last completed session and receipt lineage;
- candidate/shadow balances, pending entries, and open positions;
- observation schema versions and outcome reconciliation status;
- blocking issues, warnings, and next eligible action.

Acceptance criterion: an operator can determine in one screen whether another
paper session is permitted and why, without consulting runtime files.

### Phase 2: notification-only monitoring

Design alerts for:

- a new complete candle becoming available;
- a pending entry filling or expiring;
- a paper position closing;
- stale or conflicting market data;
- ledger, observation, outcome, policy, or clean-tree integrity failures;
- evidence thresholds being reached.

Every alert should contain a stable event ID, timestamp, market, session date,
software commit, policy fingerprint, severity, and recommended operator action.
Alerts must not place, modify, or close orders.

### Phase 3: outcome intelligence

After closed trades exist, add read-only analysis for:

- return and win rate by instrument, direction, regime, and setup quality;
- maximum favorable and adverse excursion;
- holding-period distribution;
- exit-reason distribution;
- candidate-versus-shadow divergence;
- currency and correlation concentration;
- calibration between signal confidence and realized outcomes.

Minimum sample sizes must be displayed with every aggregation. Sparse groups
must be labeled insufficient rather than ranked.

### Phase 4: isolated research laboratory

Define immutable experiment manifests containing:

- hypothesis and predeclared acceptance criteria;
- code commit and dependency lock;
- strategy and parameter fingerprint;
- instruments, timeframe, date range, and data hashes;
- train, validation, and forward-test partitions;
- fees, spread, slippage, and leverage assumptions;
- generated artifacts and deterministic result hashes.

Promotion into a future prospective protocol must require an explicit human
review and a new protocol version. Research must never rewrite current
prospective evidence.

## Research questions for the next round

1. Which information lets an operator decide whether to act without opening a
   chart?
2. Which alerts reduce missed sessions without encouraging overtrading?
3. How do mature platforms explain margin, exposure, and correlated risk before
   an order is submitted?
4. How do platforms communicate stale data, disconnection, latency, and partial
   service failure?
5. Which performance views help identify behavior without implying statistical
   significance from small samples?
6. How should Trade IQ show differences between backtest, forward test,
   prospective paper evidence, and real-market execution?
7. What audit information must accompany every recommendation, alert, and
   experiment result?

## Decision

The recommended next product increment is the P0 evidence cockpit. It builds on
verified data Trade IQ already produces, adds no trading authority, and makes
the system's safety and evidence state easier to understand. Notification-only
monitoring should follow after the cockpit defines the canonical state that an
alert will summarize.
