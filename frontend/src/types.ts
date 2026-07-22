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
