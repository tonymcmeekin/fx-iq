import { useCallback, useEffect, useRef, useState } from "react";

import {
  createOperatorAnnotation,
  fetchAiInsights,
  fetchDashboardData,
  fetchOperatorAnnotations,
  fetchScannerOpportunities,
  saveOfflineAiInsight,
} from "./api";
import { MarketScanner } from "./components/MarketScanner";
import type {
  AnnotationCategory,
  CountProgress,
  DashboardData,
  DecisionClassification,
  DecisionComponentScores,
  OperatorAlertSeverity,
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

function alertBadgeClass(severity: OperatorAlertSeverity): string {
  if (severity === "CRITICAL") {
    return "badge badge--danger";
  }

  if (severity === "WARNING") {
    return "badge badge--warning";
  }

  return "badge badge--neutral";
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
  const [annotationSubject, setAnnotationSubject] = useState("");
  const [annotationCategory, setAnnotationCategory] =
    useState<AnnotationCategory>("REVIEW");
  const [annotationNote, setAnnotationNote] = useState("");
  const [annotationStatus, setAnnotationStatus] = useState<
    "idle" | "saving" | "saved" | "error"
  >("idle");
  const [annotationError, setAnnotationError] = useState<string | null>(
    null,
  );
  const [insightStatus, setInsightStatus] = useState<
    "idle" | "saving" | "saved" | "error"
  >("idle");
  const [insightError, setInsightError] = useState<string | null>(null);
  const insightRequestKey = useRef<string | null>(null);
  const [insightReviewNote, setInsightReviewNote] = useState("");
  const [insightReviewStatus, setInsightReviewStatus] = useState<
    "idle" | "saving" | "saved" | "error"
  >("idle");
  const [insightReviewError, setInsightReviewError] = useState<string | null>(
    null,
  );
  const insightReviewKey = useRef<string | null>(null);

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

  const submitAnnotation = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const currentData =
        state.status === "ready" || state.status === "refreshing"
          ? state.data
          : null;
      const subjectId =
        annotationSubject || currentData?.alerts.alerts[0]?.alert_id;

      if (!subjectId || !annotationNote.trim()) {
        return;
      }

      setAnnotationStatus("saving");
      setAnnotationError(null);

      try {
        await createOperatorAnnotation({
          idempotency_key: crypto.randomUUID(),
          subject_id: subjectId,
          category: annotationCategory,
          note: annotationNote.trim(),
        });
        const annotations = await fetchOperatorAnnotations();
        setState((current) => {
          if (
            current.status !== "ready" &&
            current.status !== "refreshing"
          ) {
            return current;
          }
          return {
            status: "ready",
            data: { ...current.data, annotations },
          };
        });
        setAnnotationNote("");
        setAnnotationStatus("saved");
      } catch (error: unknown) {
        setAnnotationStatus("error");
        setAnnotationError(
          error instanceof Error
            ? error.message
            : "Operator annotation could not be appended.",
        );
      }
    },
    [annotationCategory, annotationNote, annotationSubject, state],
  );

  const saveBriefing = useCallback(async () => {
    setInsightStatus("saving");
    setInsightError(null);
    insightRequestKey.current ??= crypto.randomUUID();

    try {
      await saveOfflineAiInsight(insightRequestKey.current);
      const aiInsights = await fetchAiInsights();
      setState((current) => {
        if (
          current.status !== "ready" &&
          current.status !== "refreshing"
        ) {
          return current;
        }
        return {
          status: "ready",
          data: { ...current.data, aiInsights },
        };
      });
      insightRequestKey.current = null;
      setInsightStatus("saved");
    } catch (error: unknown) {
      setInsightStatus("error");
      setInsightError(
        error instanceof Error
          ? error.message
          : "The briefing could not be saved.",
      );
    }
  }, []);

  const submitInsightReview = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const currentData =
        state.status === "ready" || state.status === "refreshing"
          ? state.data
          : null;
      const insight = currentData?.aiInsights.insights.at(-1);
      if (!insight || !insightReviewNote.trim()) {
        return;
      }

      setInsightReviewStatus("saving");
      setInsightReviewError(null);
      insightReviewKey.current ??= crypto.randomUUID();
      try {
        await createOperatorAnnotation({
          idempotency_key: insightReviewKey.current,
          subject_type: "AI_INSIGHT",
          subject_id: insight.insight_id,
          category: "REVIEW",
          note: insightReviewNote.trim(),
        });
        const annotations = await fetchOperatorAnnotations();
        setState((current) => {
          if (
            current.status !== "ready" &&
            current.status !== "refreshing"
          ) {
            return current;
          }
          return {
            status: "ready",
            data: { ...current.data, annotations },
          };
        });
        insightReviewKey.current = null;
        setInsightReviewNote("");
        setInsightReviewStatus("saved");
      } catch (error: unknown) {
        setInsightReviewStatus("error");
        setInsightReviewError(
          error instanceof Error
            ? error.message
            : "The human review could not be appended.",
        );
      }
    },
    [insightReviewNote, state],
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
    cockpit,
    alerts,
    portfolio,
    outcomes,
    annotations,
    aiBriefing,
    aiInsights,
    decision,
    scanner,
  } = state.data;
  const calendar = readiness.progress.calendar_requirement;
  const isRefreshing = state.status === "refreshing";
  const warningCount =
    readiness.warnings.length +
    readiness.observation_integrity_warnings.length;
  const latestLineage = cockpit.session_lineage.at(-1);
  const latestMarketTimestamp = cockpit.markets.find(
    (market) => market.latest_complete_timestamp,
  )?.latest_complete_timestamp;
  const maximumAlignedReturns = Math.max(
    0,
    ...portfolio.correlations.map(
      (correlation) => correlation.aligned_return_count,
    ),
  );
  const reviewedInsightIds = new Set(
    annotations.annotations
      .filter((annotation) => annotation.subject_type === "AI_INSIGHT")
      .map((annotation) => annotation.subject_id),
  );
  const latestInsight = aiInsights.insights.at(-1);

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
              readiness.observation_integrity_status ??
                "Unavailable",
            )}
          </strong>
          <div>
            <span
              className={
                readiness.observation_integrity_status ===
                "HEALTHY"
                  ? "badge badge--positive"
                  : "badge badge--danger"
              }
            >
              {readiness.observations_recorded} observations ·{" "}
              {readiness.observation_outcomes_populated} outcomes
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

      <section className="panel evidence-cockpit">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Verified operating evidence</span>
            <h2>Evidence cockpit</h2>
          </div>
          <span
            className={
              cockpit.status === "HEALTHY"
                ? "badge badge--positive"
                : "badge badge--danger"
            }
          >
            {formatLabel(cockpit.status)}
          </span>
        </div>

        <div className="evidence-grid">
          <div>
            <span>Next safe action</span>
            <strong>{formatLabel(cockpit.next_action)}</strong>
          </div>
          <div>
            <span>Last / next session</span>
            <strong>
              {cockpit.last_completed_session_date ?? "None"} →{" "}
              {cockpit.next_session_date ?? "Pending"}
            </strong>
          </div>
          <div>
            <span>Latest complete candle</span>
            <strong>{latestMarketTimestamp ?? "Unavailable"}</strong>
            <small>
              {cockpit.markets.length} markets ·{" "}
              {cockpit.markets_aligned ? "aligned" : "misaligned"}
            </small>
          </div>
          <div>
            <span>Positions</span>
            <strong>
              {cockpit.pending_entries.length} pending ·{" "}
              {cockpit.open_positions.length} open
            </strong>
            <small>Broker orders sent: {cockpit.broker_orders_sent}</small>
          </div>
          <div>
            <span>Software lineage</span>
            <strong>{cockpit.current_software_commit}</strong>
            <small>
              {cockpit.tracked_source_clean ? "Source clean" : "Source changed"}
              {cockpit.software_changed_since_last_session
                ? " · changed since session"
                : " · matches session"}
            </small>
          </div>
          <div>
            <span>Policy & receipt</span>
            <strong>
              {cockpit.policy_matches_last_session
                ? "Policy matched"
                : "Policy mismatch"}
            </strong>
            <small>
              Latest receipt: {formatLabel(latestLineage?.receipt_status ?? "Unavailable")}
            </small>
          </div>
        </div>

        {cockpit.blocking_issues.length > 0 && (
          <div className="evidence-alert" role="alert">
            <strong>Action paused</strong>
            <span>{cockpit.blocking_issues.join(" ")}</span>
          </div>
        )}

        <p className="evidence-safety">
          Simulation only. This cockpit can inspect evidence, but it cannot
          submit or authorize broker orders.
        </p>
      </section>

      <section className="panel ai-briefing">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Guarded AI evidence analyst</span>
            <h2>Evidence briefing</h2>
          </div>
          <div className="ai-heading-actions">
            <span className="badge badge--positive">
              {aiBriefing.provider_mode === "OFFLINE"
                ? "Offline · no network"
                : "Hosted · sanitized"}
            </span>
            <button
              className="button button--compact"
              type="button"
              disabled={insightStatus === "saving"}
              onClick={() => void saveBriefing()}
            >
              {insightStatus === "saving"
                ? "Saving…"
                : "Save verified briefing"}
            </button>
          </div>
        </div>

        <p className="ai-headline">{aiBriefing.briefing.headline}</p>

        <div className="ai-briefing-grid">
          <article>
            <h3>What the evidence says</h3>
            <ul>
              {aiBriefing.briefing.what_changed.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
          <article>
            <h3>Why we are waiting</h3>
            <ul>
              {aiBriefing.briefing.why_waiting.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
          <article>
            <h3>Missing evidence</h3>
            <ul>
              {aiBriefing.briefing.missing_evidence.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
          <article>
            <h3>Risks to review</h3>
            <ul>
              {aiBriefing.briefing.risks_to_review.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
          <article>
            <h3>Questions for human review</h3>
            <ul>
              {aiBriefing.briefing.next_review_questions.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
        </div>

        <div className="ai-citations" aria-label="Briefing evidence citations">
          {aiBriefing.briefing.citations.map((citation) => (
            <code key={citation.evidence_id} title={citation.evidence_id}>
              {citation.label}
            </code>
          ))}
        </div>

        {insightStatus === "saved" && (
          <p className="annotation-message annotation-message--success">
            Briefing appended to the verified AI insight chain.
          </p>
        )}
        {insightStatus === "error" && insightError && (
          <p className="annotation-message annotation-message--error">
            {insightError}
          </p>
        )}

        <div className="ai-history">
          <div>
            <h3>Verified insight history</h3>
            <span className="badge badge--neutral">
              {aiInsights.insight_count} saved
            </span>
          </div>
          {aiInsights.insights.length === 0 ? (
            <p>No AI briefings have been saved.</p>
          ) : (
            aiInsights.insights
              .slice(-3)
              .reverse()
              .map((insight) => (
                <article key={insight.insight_id}>
                  <div>
                    <strong>Briefing #{insight.sequence}</strong>
                    <span
                      className={
                        reviewedInsightIds.has(insight.insight_id)
                          ? "badge badge--positive"
                          : "badge badge--warning"
                      }
                    >
                      {reviewedInsightIds.has(insight.insight_id)
                        ? "Human reviewed"
                        : "Review required"}
                    </span>
                  </div>
                  <p>{insight.briefing.headline}</p>
                  <small>
                    Hash {insight.record_hash.slice(0, 10)} ·{" "}
                    {formatLabel(insight.provider_mode)} · {insight.model} ·{" "}
                    {new Date(insight.created_at_utc).toLocaleString()}
                  </small>
                </article>
              ))
          )}

          {latestInsight && !reviewedInsightIds.has(latestInsight.insight_id) && (
            <form className="ai-review-form" onSubmit={submitInsightReview}>
              <label>
                Human review note for briefing #{latestInsight.sequence}
                <textarea
                  maxLength={2000}
                  placeholder="Record your assessment before treating any follow-up question as accepted."
                  value={insightReviewNote}
                  onChange={(event) => {
                    setInsightReviewNote(event.target.value);
                    setInsightReviewStatus("idle");
                  }}
                />
              </label>
              <button
                className="button button--compact"
                type="submit"
                disabled={
                  !insightReviewNote.trim() || insightReviewStatus === "saving"
                }
              >
                {insightReviewStatus === "saving"
                  ? "Appending…"
                  : "Append human review"}
              </button>
              {insightReviewStatus === "error" && insightReviewError && (
                <p className="annotation-message annotation-message--error">
                  {insightReviewError}
                </p>
              )}
            </form>
          )}

          {insightReviewStatus === "saved" && (
            <p className="annotation-message annotation-message--success">
              Human review appended and linked to the insight hash.
            </p>
          )}
        </div>

        <p className="evidence-safety">
          Input sanitized · no credentials, annotation text, or raw candles.
          This analyst cannot change strategy, authorize live trading, or submit
          broker orders. Follow-up questions remain unaccepted until a human
          review is appended.
        </p>
      </section>

      <section className="panel operator-alerts">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Notification only</span>
            <h2>Active operator alerts</h2>
          </div>
          <span
            className={
              alerts.critical_alert_count > 0
                ? "badge badge--danger"
                : "badge badge--neutral"
            }
          >
            {alerts.active_alert_count} active
          </span>
        </div>

        {alerts.alerts.length === 0 ? (
          <p className="empty-alerts">No active operator alerts.</p>
        ) : (
          <div className="alert-list">
            {alerts.alerts.map((alert) => (
              <article className="alert-item" key={alert.alert_id}>
                <div className="alert-item__heading">
                  <div>
                    <span className={alertBadgeClass(alert.severity)}>
                      {alert.severity}
                    </span>
                    <strong>{alert.title}</strong>
                  </div>
                  <code>{alert.alert_id.slice(0, 10)}</code>
                </div>
                <p>{alert.message}</p>
                <small>{alert.recommended_action}</small>
                <div className="alert-lineage">
                  <span>{alert.market ?? "Portfolio"}</span>
                  <span>Session {alert.session_date ?? "pending"}</span>
                  <span>Commit {alert.software_commit}</span>
                </div>
              </article>
            ))}
          </div>
        )}

        <p className="evidence-safety">
          Alerts describe verified state transitions only. They cannot place,
          modify, or close orders.
        </p>
      </section>

      <section className="panel operator-review">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Separate review record</span>
            <h2>Operator annotations</h2>
          </div>
          <span className="badge badge--neutral">
            {annotations.annotation_count} appended
          </span>
        </div>

        <div className="review-layout">
          <form className="annotation-form" onSubmit={submitAnnotation}>
            <label>
              Alert subject
              <select
                disabled={alerts.alerts.length === 0}
                value={annotationSubject || alerts.alerts[0]?.alert_id || ""}
                onChange={(event) => setAnnotationSubject(event.target.value)}
              >
                {alerts.alerts.map((alert) => (
                  <option key={alert.alert_id} value={alert.alert_id}>
                    {alert.severity} · {alert.title}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Review category
              <select
                value={annotationCategory}
                onChange={(event) =>
                  setAnnotationCategory(
                    event.target.value as AnnotationCategory,
                  )
                }
              >
                <option value="REVIEW">Review</option>
                <option value="CONTEXT">Context</option>
                <option value="FOLLOW_UP">Follow up</option>
              </select>
            </label>

            <label className="annotation-note">
              Operator note
              <textarea
                maxLength={2000}
                placeholder="Add evidence context without changing the underlying record."
                value={annotationNote}
                onChange={(event) => {
                  setAnnotationNote(event.target.value);
                  setAnnotationStatus("idle");
                }}
              />
            </label>

            <div className="annotation-actions">
              <button
                className="button"
                type="submit"
                disabled={
                  alerts.alerts.length === 0 ||
                  !annotationNote.trim() ||
                  annotationStatus === "saving"
                }
              >
                {annotationStatus === "saving"
                  ? "Appending…"
                  : "Append annotation"}
              </button>
              <small>
                Append-only. Notes cannot be edited or deleted.
              </small>
            </div>

            {annotationStatus === "saved" && (
              <p className="annotation-message annotation-message--success">
                Annotation appended and hash-chain verified.
              </p>
            )}
            {annotationStatus === "error" && annotationError && (
              <p className="annotation-message annotation-message--error">
                {annotationError}
              </p>
            )}
          </form>

          <div className="annotation-history">
            <h3>Recent annotations</h3>
            {annotations.annotations.length === 0 ? (
              <p>No operator annotations have been appended.</p>
            ) : (
              annotations.annotations
                .slice(-5)
                .reverse()
                .map((annotation) => (
                  <article key={annotation.annotation_id}>
                    <div>
                      <span className="badge badge--neutral">
                        {formatLabel(annotation.category)}
                      </span>
                      <code>#{annotation.sequence}</code>
                    </div>
                    <p>{annotation.note}</p>
                    <small>
                      Alert {annotation.subject_id.slice(0, 10)} · Commit{" "}
                      {annotation.software_commit}
                    </small>
                  </article>
                ))
            )}
          </div>
        </div>

        <p className="evidence-safety">
          Annotations are stored separately and cannot alter the ledger,
          observations, outcomes, strategy, paper positions, or broker state.
        </p>
      </section>

      <section className="panel portfolio-intelligence">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Paper portfolio context</span>
            <h2>Exposure & correlation</h2>
          </div>
          <span
            className={
              portfolio.status === "AVAILABLE"
                ? "badge badge--positive"
                : "badge badge--warning"
            }
          >
            {formatLabel(portfolio.status)}
          </span>
        </div>

        <div className="portfolio-metrics">
          <div>
            <span>Candidate risk</span>
            <strong>{portfolio.candidate_gross_risk_percent.toFixed(2)}%</strong>
            <small>Gross paper risk</small>
          </div>
          <div>
            <span>Shadow risk</span>
            <strong>{portfolio.shadow_gross_risk_percent.toFixed(2)}%</strong>
            <small>Frozen comparison account</small>
          </div>
          <div>
            <span>Correlation coverage</span>
            <strong>
              {portfolio.available_correlation_pair_count} /{" "}
              {portfolio.correlation_pair_count}
            </strong>
            <small>Market pairs interpretable</small>
          </div>
          <div>
            <span>Active paper state</span>
            <strong>
              {portfolio.pending_entry_count} pending ·{" "}
              {portfolio.open_position_count} open
            </strong>
            <small>Broker orders: {portfolio.broker_orders_sent}</small>
          </div>
        </div>

        <div className="exposure-columns">
          <div>
            <h3>Candidate currency legs</h3>
            <div className="exposure-list">
              {portfolio.candidate_currency_exposure.length === 0 ? (
                <span className="empty-exposure">No active exposure</span>
              ) : (
                portfolio.candidate_currency_exposure.map((exposure) => (
                  <span className="exposure-chip" key={exposure.currency}>
                    <strong>{exposure.currency}</strong>
                    {exposure.side} {exposure.absolute_risk_percent.toFixed(2)}%
                  </span>
                ))
              )}
            </div>
          </div>
          <div>
            <h3>Shadow currency legs</h3>
            <div className="exposure-list">
              {portfolio.shadow_currency_exposure.length === 0 ? (
                <span className="empty-exposure">No active exposure</span>
              ) : (
                portfolio.shadow_currency_exposure.map((exposure) => (
                  <span className="exposure-chip" key={exposure.currency}>
                    <strong>{exposure.currency}</strong>
                    {exposure.side} {exposure.absolute_risk_percent.toFixed(2)}%
                  </span>
                ))
              )}
            </div>
          </div>
        </div>

        {portfolio.status === "INSUFFICIENT_DATA" && (
          <div className="correlation-notice">
            <strong>Correlation intentionally withheld</strong>
            <span>
              {maximumAlignedReturns} aligned returns are available;{" "}
              {portfolio.minimum_aligned_returns_required} are required before
              any pair is interpreted.
            </span>
          </div>
        )}

        {portfolio.high_correlation_pairs.length > 0 && (
          <div className="correlation-pairs">
            <h3>High-correlation pairs</h3>
            {portfolio.high_correlation_pairs.map((pair) => (
              <span key={`${pair.left_market}:${pair.right_market}`}>
                {pair.left_market.replace("_", "/")} ↔{" "}
                {pair.right_market.replace("_", "/")}: {pair.correlation}
              </span>
            ))}
          </div>
        )}

        <p className="evidence-safety">
          Exposure is descriptive paper-risk context. It does not resize,
          approve, or execute any position.
        </p>
      </section>

      <section className="panel outcome-explorer">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Verified learning evidence</span>
            <h2>Outcome explorer</h2>
          </div>
          <span
            className={
              outcomes.status === "AVAILABLE"
                ? "badge badge--positive"
                : "badge badge--warning"
            }
          >
            {formatLabel(outcomes.status)}
          </span>
        </div>

        <div className="outcome-metrics">
          <div>
            <span>Verified outcomes</span>
            <strong>
              {outcomes.outcome_count} / {outcomes.minimum_overall_sample}
            </strong>
            <small>Required for overall statistics</small>
          </div>
          <div>
            <span>Eligible groups</span>
            <strong>
              {outcomes.available_group_count} / {outcomes.group_count}
            </strong>
            <small>{outcomes.minimum_group_sample} outcomes per group</small>
          </div>
          <div>
            <span>Mean return</span>
            <strong>
              {outcomes.overall.mean_return_percent === null
                ? "Withheld"
                : `${outcomes.overall.mean_return_percent.toFixed(2)}%`}
            </strong>
            <small>Verified paper outcomes only</small>
          </div>
          <div>
            <span>Win rate</span>
            <strong>
              {outcomes.overall.win_rate_percent === null
                ? "Withheld"
                : `${outcomes.overall.win_rate_percent.toFixed(2)}%`}
            </strong>
            <small>No sparse-sample ranking</small>
          </div>
        </div>

        {outcomes.status === "INSUFFICIENT_DATA" && (
          <div className="outcome-notice">
            <strong>Performance statistics intentionally withheld</strong>
            <span>
              Closed paper outcomes will populate return, excursion, holding
              period, regime, setup, and exit-reason analysis. No estimate is
              produced before the declared sample thresholds are met.
            </span>
          </div>
        )}

        {outcomes.groups.length > 0 && (
          <details className="outcome-groups">
            <summary>Review grouped sample counts</summary>
            <div>
              {outcomes.groups.map((group) => (
                <span key={`${group.dimension}:${group.value}`}>
                  <strong>{formatLabel(group.dimension)}</strong>
                  {group.value} · {group.sample_size} samples ·{" "}
                  {formatLabel(group.status)}
                </span>
              ))}
            </div>
          </details>
        )}

        <p className="evidence-safety">
          Outcome analysis is read-only and cannot modify the frozen strategy,
          paper state, or broker state.
        </p>
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
                warningCount === 0
                  ? "badge badge--positive"
                  : "badge badge--warning"
              }
            >
              {warningCount}
            </span>
          </div>

          {warningCount === 0 ? (
            <p>No warnings reported.</p>
          ) : (
            <>
              {readiness.warnings.length > 0 && (
                <>
                  <h3 className="warning-group-title">
                    Protocol evidence
                  </h3>
                  <ul>
                    {readiness.warnings.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </>
              )}

              {readiness.observation_integrity_warnings
                .length > 0 && (
                <>
                  <h3 className="warning-group-title">
                    Observation evidence
                  </h3>
                  <ul>
                    {readiness.observation_integrity_warnings.map(
                      (item) => <li key={item}>{item}</li>,
                    )}
                  </ul>
                </>
              )}
            </>
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
