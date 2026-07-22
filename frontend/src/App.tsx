import { useCallback, useEffect, useState } from "react";

import {
  fetchDashboardData,
  fetchScannerOpportunities,
} from "./api";
import { MarketScanner } from "./components/MarketScanner";
import type {
  CountProgress,
  DashboardData,
  DecisionClassification,
  DecisionComponentScores,
  ScannerSource,
} from "./types";

type ViewState =
  | { status: "loading" }
  | { status: "refreshing"; data: DashboardData }
  | { status: "error"; message: string }
  | { status: "ready"; data: DashboardData };

interface ScoreItem {
  key: keyof DecisionComponentScores;
  label: string;
}

const scoreItems: ScoreItem[] = [
  {
    key: "signal_quality",
    label: "Signal quality",
  },
  {
    key: "trend_alignment",
    label: "Trend alignment",
  },
  {
    key: "regime_confidence",
    label: "Regime confidence",
  },
  {
    key: "volatility_suitability",
    label: "Volatility suitability",
  },
  {
    key: "risk_reward",
    label: "Risk / reward",
  },
];

function formatLabel(value: string): string {
  return value
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function progressPercent(progress: CountProgress): number {
  if (progress.required <= 0) {
    return progress.requirement_met ? 100 : 0;
  }

  return Math.min(
    100,
    Math.max(0, (progress.current / progress.required) * 100),
  );
}

function decisionBadgeClass(
  decision: DecisionClassification,
): string {
  if (decision === "ALLOW") {
    return "badge badge--positive";
  }

  if (decision === "WATCH") {
    return "badge badge--warning";
  }

  return "badge badge--danger";
}

function decisionPanelClass(
  decision: DecisionClassification,
): string {
  if (decision === "ALLOW") {
    return "decision-panel decision-panel--allow";
  }

  if (decision === "WATCH") {
    return "decision-panel decision-panel--watch";
  }

  return "decision-panel decision-panel--reject";
}

function ProgressPanel({
  title,
  progress,
}: {
  title: string;
  progress: CountProgress;
}) {
  const percent = progressPercent(progress);

  return (
    <article className="panel progress-panel">
      <div className="panel-heading">
        <h2>{title}</h2>
        <span
          className={
            progress.requirement_met
              ? "badge badge--positive"
              : "badge badge--neutral"
          }
        >
          {progress.requirement_met ? "Complete" : "In progress"}
        </span>
      </div>

      <strong>
        {progress.current} / {progress.required}
      </strong>

      <div
        className="progress-track"
        role="progressbar"
        aria-label={title}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(percent)}
      >
        <div
          className="progress-fill"
          style={{ width: `${percent}%` }}
        />
      </div>

      <p>
        {progress.requirement_met
          ? "Requirement reached"
          : `${progress.remaining} remaining`}
      </p>
    </article>
  );
}

function App() {
  const [state, setState] = useState<ViewState>({
    status: "loading",
  });
  const [scannerSource, setScannerSource] =
    useState<ScannerSource>("synthetic");
  const [scannerLoading, setScannerLoading] = useState(false);
  const [scannerError, setScannerError] = useState<string | null>(
    null,
  );

  const loadDashboard = useCallback(async (refresh = false) => {
    setState((current) => {
      if (
        refresh &&
        (current.status === "ready" ||
          current.status === "refreshing")
      ) {
        return {
          status: "refreshing",
          data: current.data,
        };
      }

      return { status: "loading" };
    });

    try {
      const data = await fetchDashboardData();
      setState({ status: "ready", data });
    } catch (error: unknown) {
      setState({
        status: "error",
        message:
          error instanceof Error
            ? error.message
            : "Unknown dashboard error.",
      });
    }
  }, []);

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard]);

  const changeScannerSource = useCallback(
    async (source: ScannerSource) => {
      if (source === scannerSource) {
        return;
      }

      setScannerSource(source);
      setScannerLoading(true);
      setScannerError(null);

      try {
        const scanner = await fetchScannerOpportunities(source);

        setState((current) => {
          if (
            current.status !== "ready" &&
            current.status !== "refreshing"
          ) {
            return current;
          }

          return {
            status: "ready",
            data: {
              ...current.data,
              scanner,
            },
          };
        });
      } catch (error: unknown) {
        setScannerError(
          error instanceof Error
            ? error.message
            : "Unknown scanner error.",
        );
      } finally {
        setScannerLoading(false);
      }
    },
    [scannerSource],
  );

  if (state.status === "loading") {
    return (
      <main className="state-screen">
        <div className="loading-indicator" />
        <h1>Loading Trade IQ</h1>
        <p>Reading verified analytics and decision intelligence.</p>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="state-screen">
        <span className="badge badge--danger">
          Connection error
        </span>
        <h1>Dashboard unavailable</h1>
        <p>{state.message}</p>
        <p>Confirm the FastAPI backend is running on port 8000.</p>
        <button
          className="button"
          type="button"
          onClick={() => void loadDashboard()}
        >
          Try again
        </button>
      </main>
    );
  }

  const {
    readiness,
    explanation,
    operatorStatus,
    decision,
    scanner,
  } = state.data;
  const calendar = readiness.progress.calendar_requirement;
  const isRefreshing = state.status === "refreshing";

  return (
    <main className="dashboard">
      <header className="hero">
        <div>
          <span className="eyebrow">Decision intelligence</span>
          <h1>Trade IQ</h1>
          <p>
            Explainable, read-only trade evaluation for prospective
            paper observation.
          </p>
        </div>

        <button
          className="button button--secondary"
          type="button"
          disabled={isRefreshing}
          onClick={() => void loadDashboard(true)}
        >
          {isRefreshing ? "Refreshing…" : "Refresh data"}
        </button>
      </header>

      <section className="status-grid">
        <article className="card">
          <span>Status</span>
          <strong>{formatLabel(readiness.status)}</strong>
          <div>
            <span className="badge badge--neutral">
              Deterministic
            </span>
          </div>
        </article>

        <article className="card">
          <span>Current stage</span>
          <strong>{formatLabel(readiness.current_stage)}</strong>
          <div>
            <span className="badge badge--neutral">Read only</span>
          </div>
        </article>

        <article className="card">
          <span>Paper observation</span>
          <strong>
            {readiness.paper_observation_allowed
              ? "Allowed"
              : "Paused"}
          </strong>
          <div>
            <span
              className={
                readiness.paper_observation_allowed
                  ? "badge badge--positive"
                  : "badge badge--warning"
              }
            >
              {readiness.paper_observation_allowed
                ? "Protocol active"
                : "Review required"}
            </span>
          </div>
        </article>

        <article className="card">
          <span>Observation integrity</span>
          <strong>
            {formatLabel(
              operatorStatus.observation_integrity_status ??
                "Unavailable",
            )}
          </strong>
          <div>
            <span
              className={
                operatorStatus.observation_integrity_status ===
                "HEALTHY"
                  ? "badge badge--positive"
                  : "badge badge--danger"
              }
            >
              {operatorStatus.observations_recorded} observations ·{" "}
              {operatorStatus.observation_outcomes_populated} outcomes
            </span>
          </div>
        </article>

        <article className="card card--danger">
          <span>Live trading</span>
          <strong>
            {readiness.live_trading_allowed
              ? "Allowed"
              : "Prohibited"}
          </strong>
          <div>
            <span className="badge badge--danger">
              No execution controls
            </span>
          </div>
        </article>
      </section>

      <section className={decisionPanelClass(decision.decision)}>
        <div className="decision-summary">
          <div>
            <span className="eyebrow">Current sample evaluation</span>
            <div className="instrument-line">
              <h2>{decision.symbol.replace("_", "/")}</h2>
              <span className="direction-label">
                {decision.direction}
              </span>
            </div>

            <div className="decision-result">
              <span className={decisionBadgeClass(decision.decision)}>
                {decision.decision}
              </span>
              <strong>
                {decision.confidence_score.toFixed(2)}
                <small>% confidence</small>
              </strong>
            </div>

            <p className="decision-explanation">
              {decision.explanation}
            </p>
          </div>

          <div className="decision-metrics">
            <div>
              <span>Market regime</span>
              <strong>{formatLabel(decision.market_regime)}</strong>
            </div>

            <div>
              <span>Volatility</span>
              <strong>
                {formatLabel(decision.regime_volatility)}
              </strong>
            </div>

            <div>
              <span>Risk / reward</span>
              <strong>
                {decision.risk_assessment.risk_reward_ratio.toFixed(
                  2,
                )}
                :1
              </strong>
            </div>

            <div>
              <span>Adjusted risk</span>
              <strong>
                {decision.risk_assessment.adjusted_risk_percent.toFixed(
                  2,
                )}
                %
              </strong>
            </div>
          </div>
        </div>

        <div className="decision-detail-grid">
          <article className="decision-section">
            <div className="panel-heading">
              <h3>Component scores</h3>
              <span className="badge badge--neutral">
                Weighted
              </span>
            </div>

            <div className="score-list">
              {scoreItems.map((item) => {
                const score = decision.component_scores[item.key];

                return (
                  <div className="score-row" key={item.key}>
                    <div className="score-heading">
                      <span>{item.label}</span>
                      <strong>{score.toFixed(0)}</strong>
                    </div>

                    <div
                      className="score-track"
                      role="progressbar"
                      aria-label={item.label}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={score}
                    >
                      <div
                        className="score-fill"
                        style={{
                          width: `${Math.min(
                            100,
                            Math.max(0, score),
                          )}%`,
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </article>

          <article className="decision-section">
            <div className="panel-heading">
              <h3>Risk policy</h3>
              <span className="badge badge--neutral">
                v{decision.risk_assessment.policy_version}
              </span>
            </div>

            <dl className="risk-list">
              <div>
                <dt>Requested risk</dt>
                <dd>
                  {decision.risk_assessment.requested_risk_percent.toFixed(
                    2,
                  )}
                  %
                </dd>
              </div>

              <div>
                <dt>Risk multiplier</dt>
                <dd>
                  {decision.risk_assessment.risk_multiplier.toFixed(
                    2,
                  )}
                  ×
                </dd>
              </div>

              <div>
                <dt>Approved for paper trade</dt>
                <dd>
                  {decision.approved_for_paper_trade ? "Yes" : "No"}
                </dd>
              </div>
            </dl>

            <ul className="compact-list">
              {decision.risk_assessment.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </article>
        </div>

        <div className="decision-detail-grid">
          <article className="decision-section">
            <div className="panel-heading">
              <h3>Decision warnings</h3>
              <span
                className={
                  decision.warnings.length === 0
                    ? "badge badge--positive"
                    : "badge badge--warning"
                }
              >
                {decision.warnings.length}
              </span>
            </div>

            {decision.warnings.length === 0 ? (
              <p>No decision warnings reported.</p>
            ) : (
              <ul className="compact-list">
                {decision.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            )}
          </article>

          <article className="decision-section">
            <div className="panel-heading">
              <h3>Blocking reasons</h3>
              <span
                className={
                  decision.blocking_reasons.length === 0
                    ? "badge badge--positive"
                    : "badge badge--danger"
                }
              >
                {decision.blocking_reasons.length}
              </span>
            </div>

            {decision.blocking_reasons.length === 0 ? (
              <p>No decision blockers reported.</p>
            ) : (
              <ul className="compact-list">
                {decision.blocking_reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            )}
          </article>
        </div>

        <div className="safety-strip">
          <div>
            <span>Paper trading only</span>
            <strong>
              {decision.paper_trading_only ? "Enabled" : "Disabled"}
            </strong>
          </div>

          <div>
            <span>Live trading</span>
            <strong>
              {decision.live_trading_allowed
                ? "Enabled"
                : "Disabled"}
            </strong>
          </div>

          <div>
            <span>Broker orders</span>
            <strong>{decision.broker_orders_submitted}</strong>
          </div>

          <div>
            <span>Network calls</span>
            <strong>{decision.network_calls_made}</strong>
          </div>

          <div>
            <span>Ledger writes</span>
            <strong>{decision.ledger_writes_performed}</strong>
          </div>
        </div>
      </section>

      <MarketScanner
        scanner={scanner}
        source={scannerSource}
        loading={scannerLoading}
        error={scannerError}
        onSourceChange={(source) =>
          void changeScannerSource(source)
        }
      />

      <section className="progress-grid">
        <ProgressPanel
          title="Completed sessions"
          progress={readiness.progress.completed_sessions}
        />

        <ProgressPanel
          title="Closed paper trades"
          progress={readiness.progress.closed_trades}
        />

        <article className="panel progress-panel">
          <div className="panel-heading">
            <h2>Calendar requirement</h2>
            <span
              className={
                calendar.requirement_met
                  ? "badge badge--positive"
                  : "badge badge--neutral"
              }
            >
              {calendar.requirement_met
                ? "Complete"
                : "Time dependent"}
            </span>
          </div>

          <strong>
            {calendar.earliest_eligible_assessment_date ??
              "Unavailable"}
          </strong>

          <p>
            {calendar.requirement_met
              ? "Calendar requirement reached"
              : "Observation period remains active"}
          </p>
        </article>
      </section>

      <section className="content-grid">
        <article className="panel briefing">
          <span className="eyebrow">Operator briefing</span>
          <h2>{explanation.headline}</h2>
          <p>{explanation.briefing}</p>

          <div className="summary-list">
            {explanation.progress_summary.map((item) => (
              <div className="summary-item" key={item}>
                <span aria-hidden="true">✓</span>
                <p>{item}</p>
              </div>
            ))}
          </div>

          <p className="danger-text">
            {explanation.safety_statement}
          </p>
        </article>

        <article className="panel">
          <div className="panel-heading">
            <h2>Next actions</h2>
            <span className="badge badge--neutral">
              {readiness.next_actions.length}
            </span>
          </div>

          {readiness.next_actions.length === 0 ? (
            <p>No immediate actions reported.</p>
          ) : (
            <ol className="action-list">
              {readiness.next_actions.map((action) => (
                <li key={action}>{action}</li>
              ))}
            </ol>
          )}
        </article>
      </section>

      <section className="content-grid">
        <article className="panel">
          <div className="panel-heading">
            <h2>Warnings</h2>
            <span
              className={
                readiness.warnings.length === 0
                  ? "badge badge--positive"
                  : "badge badge--warning"
              }
            >
              {readiness.warnings.length}
            </span>
          </div>

          {readiness.warnings.length === 0 ? (
            <p>No warnings reported.</p>
          ) : (
            <ul>
              {readiness.warnings.map((item) => (
                <li key={item}>{formatLabel(item)}</li>
              ))}
            </ul>
          )}
        </article>

        <article className="panel">
          <div className="panel-heading">
            <h2>Blocking issues</h2>
            <span
              className={
                readiness.blocking_issues.length === 0 &&
                readiness.immediate_stop_reasons.length === 0
                  ? "badge badge--positive"
                  : "badge badge--danger"
              }
            >
              {readiness.blocking_issues.length +
                readiness.immediate_stop_reasons.length}
            </span>
          </div>

          {readiness.blocking_issues.length === 0 &&
          readiness.immediate_stop_reasons.length === 0 ? (
            <p>No blocking issues reported.</p>
          ) : (
            <ul>
              {[
                ...readiness.blocking_issues,
                ...readiness.immediate_stop_reasons,
              ].map((item) => (
                <li key={item}>{formatLabel(item)}</li>
              ))}
            </ul>
          )}
        </article>
      </section>

      <footer>
        <span>
          Read-only interface. No broker orders, ledger writes, or live
          trading controls.
        </span>
        <span>
          Strategy: {formatLabel(decision.strategy_name)}
        </span>
      </footer>
    </main>
  );
}

export default App;
