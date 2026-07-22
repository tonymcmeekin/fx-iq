export interface CountProgress {
  current: number;
  required: number;
  remaining: number;
  requirement_met: boolean;
}

export interface CalendarProgress {
  earliest_eligible_assessment_date: string | null;
  requirement_met: boolean;
}

export interface ReadinessResponse {
  status: string;
  current_stage: string;
  progress: {
    completed_sessions: CountProgress;
    closed_trades: CountProgress;
    calendar_requirement: CalendarProgress;
  };
  blocking_issues: string[];
  warnings: string[];
  observation_integrity_status: string | null;
  observations_recorded: number;
  observation_outcomes_populated: number;
  observation_integrity_warnings: string[];
  failed_criteria: string[];
  unevaluable_criteria: string[];
  immediate_stop_reasons: string[];
  next_actions: string[];
  paper_observation_allowed: boolean;
  live_trading_allowed: boolean;
}

export interface ReadinessExplanationResponse {
  headline: string;
  briefing: string;
  progress_summary: string[];
  safety_statement: string;
}

export interface EvidenceMarket {
  market: string;
  latest_complete_timestamp: string | null;
  stored_candles: number;
}

export interface EvidencePosition {
  market: string;
  direction: string | null;
  signal_candle_timestamp?: string | null;
  entry_timestamp?: string | null;
  candidate_risk_percent: number | null;
}

export interface SessionLineage {
  session_date: string;
  software_commit: string | null;
  policy_fingerprint: string | null;
  receipt_status: string;
}

export interface EvidenceCockpitResponse {
  status: string;
  generated_at_utc: string;
  current_software_commit: string;
  tracked_source_clean: boolean;
  current_policy_fingerprint: string;
  protocol_mode: "SIMULATION_ONLY";
  live_order_submission_permitted: false;
  runtime_health: string | null;
  operator_status: string | null;
  evidence_gate_status: string | null;
  observation_integrity_status: string | null;
  candidate_balance: number | null;
  shadow_balance: number | null;
  broker_orders_sent: number;
  last_completed_session_date: string | null;
  next_session_date: string | null;
  next_action: string;
  markets_aligned: boolean;
  markets: EvidenceMarket[];
  pending_entries: EvidencePosition[];
  open_positions: EvidencePosition[];
  observations_recorded: number;
  observation_outcomes_populated: number;
  session_lineage: SessionLineage[];
  software_changed_since_last_session: boolean;
  policy_matches_last_session: boolean;
  blocking_issues: string[];
  warnings: string[];
  readiness_next_actions: string[];
  safe_for_live_trading: false;
  protocol_live_trading_permitted: false;
}

export type OperatorAlertSeverity = "INFO" | "WARNING" | "CRITICAL";

export interface OperatorAlert {
  alert_id: string;
  alert_type: string;
  severity: OperatorAlertSeverity;
  title: string;
  message: string;
  detected_at_utc: string;
  evidence_timestamp_utc: string | null;
  market: string | null;
  session_date: string | null;
  software_commit: string;
  policy_fingerprint: string;
  recommended_action: string;
  requires_operator_action: boolean;
  delivery_mode: "NOTIFICATION_ONLY";
  order_action_permitted: false;
}

export interface OperatorAlertReportResponse {
  status: string;
  generated_at_utc: string;
  delivery_mode: "NOTIFICATION_ONLY";
  active_alert_count: number;
  critical_alert_count: number;
  warning_alert_count: number;
  alerts: OperatorAlert[];
  safe_for_live_trading: false;
  protocol_live_trading_permitted: false;
}

export interface CurrencyExposure {
  currency: string;
  signed_risk_percent: number;
  side: "LONG" | "SHORT" | "FLAT";
  absolute_risk_percent: number;
}

export interface MarketCorrelation {
  left_market: string;
  right_market: string;
  aligned_return_count: number;
  minimum_return_count: number;
  status: "AVAILABLE" | "INSUFFICIENT_DATA";
  correlation: number | null;
  absolute_correlation: number | null;
  strength: string;
}

export interface PortfolioIntelligenceResponse {
  status: string;
  generated_at_utc: string;
  methodology: string;
  minimum_aligned_returns_required: number;
  market_count: number;
  correlation_pair_count: number;
  available_correlation_pair_count: number;
  high_correlation_pair_count: number;
  pending_entry_count: number;
  open_position_count: number;
  candidate_gross_risk_percent: number;
  shadow_gross_risk_percent: number;
  candidate_currency_gross_exposure_percent: number;
  shadow_currency_gross_exposure_percent: number;
  positions: EvidencePosition[];
  candidate_currency_exposure: CurrencyExposure[];
  shadow_currency_exposure: CurrencyExposure[];
  correlations: MarketCorrelation[];
  high_correlation_pairs: MarketCorrelation[];
  broker_orders_sent: number;
  safe_for_live_trading: false;
  protocol_live_trading_permitted: false;
}

export interface OutcomeMetrics {
  sample_size: number;
  minimum_sample_size: number;
  status: "AVAILABLE" | "INSUFFICIENT_DATA";
  mean_return_percent: number | null;
  median_return_percent: number | null;
  win_rate_percent: number | null;
  profit_factor: number | null;
  mean_favourable_excursion_percent: number | null;
  mean_adverse_excursion_percent: number | null;
  mean_candles_held: number | null;
}

export interface OutcomeGroup extends OutcomeMetrics {
  dimension: string;
  value: string;
}

export interface OutcomeExplorerResponse {
  status: "AVAILABLE" | "INSUFFICIENT_DATA";
  generated_at_utc: string;
  minimum_overall_sample: number;
  minimum_group_sample: number;
  outcome_count: number;
  available_group_count: number;
  group_count: number;
  overall: OutcomeMetrics;
  distribution: Record<string, unknown>;
  groups: OutcomeGroup[];
  integrity_status: string;
  integrity_warnings: string[];
  safe_for_live_trading: false;
  protocol_live_trading_permitted: false;
}

export type AnnotationCategory = "CONTEXT" | "REVIEW" | "FOLLOW_UP";

export interface OperatorAnnotation {
  sequence: number;
  annotation_id: string;
  created_at_utc: string;
  subject_type:
    | "ALERT"
    | "SESSION"
    | "OBSERVATION"
    | "OUTCOME"
    | "AI_INSIGHT";
  subject_id: string;
  subject_session_date: string | null;
  category: AnnotationCategory;
  note: string;
  software_commit: string;
  policy_fingerprint: string;
  previous_hash: string;
  record_hash: string;
}

export interface AnnotationListResponse {
  status: "HEALTHY";
  annotation_count: number;
  annotations: OperatorAnnotation[];
  safe_for_live_trading: false;
  protocol_live_trading_permitted: false;
}

export interface AnnotationAppendResponse {
  status: "CREATED" | "EXISTING";
  created: boolean;
  annotation: OperatorAnnotation;
  files_changed: number;
  ledger_writes_performed: number;
  broker_orders_submitted: number;
  safe_for_live_trading: false;
  protocol_live_trading_permitted: false;
}

export interface EvidenceCitation {
  evidence_id: string;
  label: string;
}

export interface EvidenceBriefingResponse {
  status: "READY";
  generated_at_utc: string;
  provider_mode: "OFFLINE" | "OPENAI";
  model: string;
  prompt_fingerprint: string;
  input_fingerprint: string;
  hosted_provider_available: boolean;
  briefing: {
    headline: string;
    what_changed: string[];
    why_waiting: string[];
    missing_evidence: string[];
    risks_to_review: string[];
    next_review_questions: string[];
    citations: EvidenceCitation[];
  };
  quality_gate: {
    status: "PASS" | "FAIL";
    citations_valid: boolean;
    core_evidence_cited: boolean;
    sparse_evidence_acknowledged: boolean;
    prohibited_trading_language_absent: boolean;
    sensitive_identifier_patterns_absent: boolean;
    failures: string[];
  };
  safety: {
    input_sanitized: true;
    credentials_included: false;
    annotation_text_included: false;
    raw_market_data_included: false;
    trading_action_permitted: false;
    network_calls_made: number;
    files_changed: number;
    ledger_writes_performed: number;
    broker_orders_submitted: number;
    safe_for_live_trading: false;
    protocol_live_trading_permitted: false;
  };
}

export interface AiInsightRecord {
  sequence: number;
  insight_id: string;
  idempotency_key: string;
  created_at_utc: string;
  provider_mode: "OFFLINE" | "OPENAI";
  model: string;
  prompt_fingerprint: string;
  input_fingerprint: string;
  briefing: EvidenceBriefingResponse["briefing"];
  quality_gate: EvidenceBriefingResponse["quality_gate"];
  previous_hash: string;
  record_hash: string;
}

export interface AiInsightListResponse {
  status: "HEALTHY";
  insight_count: number;
  insights: AiInsightRecord[];
  safety: EvidenceBriefingResponse["safety"];
}

export interface AiInsightAppendResponse {
  status: "CREATED" | "EXISTING";
  created: boolean;
  insight: AiInsightRecord;
  safety: EvidenceBriefingResponse["safety"];
}

export interface AiGovernanceResponse {
  status: "HEALTHY" | "REVIEW_REQUIRED" | "INTEGRITY_ERROR";
  insight_count: number;
  reviewed_insight_count: number;
  unreviewed_insight_count: number;
  hosted_insight_count: number;
  rejected_output_count: number;
  hosted_rejected_output_count: number;
  latest_rejection_at_utc: string | null;
  orphaned_review_count: number;
  unreviewed_insight_ids: string[];
  orphaned_review_subject_ids: string[];
  model_fingerprints: string[];
  prompt_fingerprints: string[];
  review_rule: string;
  safety: EvidenceBriefingResponse["safety"];
}

export interface AiProviderReadinessResponse {
  status: "READY" | "DISABLED" | "INCOMPLETE";
  offline_provider_ready: true;
  hosted_provider_requested: boolean;
  api_key_configured: boolean;
  model_configured: boolean;
  configured_model: string | null;
  endpoint: "https://api.openai.com/v1/responses";
  request_storage_enabled: false;
  idempotent_replay_protection: true;
  rejected_request_replay_protection: true;
  sanitized_input_only: true;
  explicit_generation_required: true;
  required_settings: string[];
  blocking_reasons: string[];
  safety: EvidenceBriefingResponse["safety"];
}

export interface CanaryReadinessResponse {
  status: "NO_EVIDENCE" | "REHEARSING" | "REHEARSAL_TARGET_MET" | "ACTION_REQUIRED" | "INTEGRITY_ERROR";
  rehearsal_count: number;
  qualifying_rehearsal_count: number;
  gslo_rehearsal_count: number;
  failed_rehearsal_count: number;
  unresolved_failure_count: number;
  required_rehearsals: number;
  remaining_rehearsals: number;
  operational_rehearsal_target_met: boolean;
  all_positions_verified_closed: boolean;
  practice_entry_orders_submitted: number;
  practice_close_orders_submitted: number;
  live_orders_submitted: 0;
  latest_rehearsal_id: string | null;
  latest_completed_at_utc: string | null;
  latest_instrument: string | null;
  latest_failure_at_utc: string | null;
  latest_failure_stage: string | null;
  latest_loss_budget_gbp: string | null;
  latest_worst_case_loss_gbp: string | null;
  latest_gslo_premium_gbp: string | null;
  live_canary_build_enabled: false;
  live_execution_locked: true;
  live_trading_allowed: false;
  network_calls_made: 0;
  files_changed: 0;
  blocking_issues: string[];
  next_actions: string[];
}

export interface SimulatedHostedTrialResponse {
  status: "PASS";
  executed_at_utc: string;
  mode: "LOCAL_IN_PROCESS";
  external_network_calls_made: 0;
  adapter_requests_made: 1;
  persistent_runtime_files_changed: 0;
  broker_orders_submitted: 0;
  request_storage_enabled: false;
  quality_gate: "PASS";
  governance_status: "REVIEW_REQUIRED";
  checks: Record<string, boolean>;
}

export type DecisionClassification = "ALLOW" | "WATCH" | "REJECT";

export type ScannerSource = "synthetic" | "oanda";

export interface DecisionComponentScores {
  signal_quality: number;
  trend_alignment: number;
  regime_confidence: number;
  volatility_suitability: number;
  risk_reward: number;
}

export interface DecisionRiskAssessment {
  requested_risk_percent: number;
  adjusted_risk_percent: number;
  risk_multiplier: number;
  risk_reward_ratio: number;
  policy_version: string;
  reasons: string[];
}

export interface DecisionEvaluationResponse {
  symbol: string;
  strategy_name: string;
  direction: string;
  decision: DecisionClassification;
  approved_for_paper_trade: boolean;
  confidence_score: number;
  market_regime: string;
  regime_volatility: string;
  component_scores: DecisionComponentScores;
  risk_assessment: DecisionRiskAssessment;
  blocking_reasons: string[];
  warnings: string[];
  explanation: string;
  paper_trading_only: boolean;
  live_trading_allowed: boolean;
  broker_orders_submitted: number;
  network_calls_made: number;
  ledger_writes_performed: number;
}

export interface DashboardData {
  readiness: ReadinessResponse;
  explanation: ReadinessExplanationResponse;
  cockpit: EvidenceCockpitResponse;
  alerts: OperatorAlertReportResponse;
  portfolio: PortfolioIntelligenceResponse;
  outcomes: OutcomeExplorerResponse;
  annotations: AnnotationListResponse;
  aiBriefing: EvidenceBriefingResponse;
  aiInsights: AiInsightListResponse;
  aiGovernance: AiGovernanceResponse;
  aiProviderReadiness: AiProviderReadinessResponse;
  canaryReadiness: CanaryReadinessResponse;
  decision: DecisionEvaluationResponse;
  scanner: ScannerResult;
}

export interface ScannerOpportunity {
  rank: number;
  symbol: string;
  timeframe: string;
  strategy_name: string;
  direction: string;
  decision: DecisionClassification;
  confidence_score: number;
  risk_reward_ratio: number;
  market_regime: string;
  regime_volatility: string;
  adjusted_risk_percent: number;
  approved_for_paper_trade: boolean;
  warning_count: number;
  blocking_reason_count: number;
  explanation: string;
  paper_trading_only: boolean;
  live_trading_allowed: boolean;
  broker_orders_submitted: number;
  network_calls_made: number;
  ledger_writes_performed: number;
}

export interface ScannerResult {
  scanner_version: string;
  opportunities: ScannerOpportunity[];
  evaluated_markets: number;
  allow_count: number;
  watch_count: number;
  reject_count: number;
  paper_trading_only: boolean;
  live_trading_allowed: boolean;
  broker_orders_submitted: number;
  network_calls_made: number;
  ledger_writes_performed: number;
}
