from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EquityPoint(BaseModel):
    trade_number: int
    balance: float
    profit_percent: float


class AnalyticsResponseModel(BaseModel):
    """Forward-compatible base model for read-only analytics responses."""

    model_config = ConfigDict(extra="allow")


class AnalyticsSafetyResponse(AnalyticsResponseModel):
    """Invariant safety fields shared by analytics responses."""

    network_calls_made: int = Field(default=0, ge=0)
    files_changed: int = Field(default=0, ge=0)
    ledger_writes_performed: int = Field(default=0, ge=0)
    broker_orders_submitted: int = Field(default=0, ge=0)
    safe_for_live_trading: Literal[False] = False
    protocol_live_trading_permitted: Literal[False] = False


class StrategyPerformanceSummary(AnalyticsResponseModel):
    """Aggregate performance statistics."""

    total_trades: int = Field(default=0, ge=0)
    winning_trades: int = Field(default=0, ge=0)
    losing_trades: int = Field(default=0, ge=0)
    breakeven_trades: int = Field(default=0, ge=0)
    win_rate_percent: float | None = None
    gross_profit_percent: float = 0.0
    gross_loss_percent: float = 0.0
    net_profit_percent: float = 0.0
    profit_factor: float | None = None
    expectancy_percent: float | None = None
    average_win_percent: float | None = None
    average_loss_percent: float | None = None
    largest_winner_percent: float | None = None
    largest_loser_percent: float | None = None
    average_candles_held: float | None = None


class StrategyAttributionResponse(AnalyticsResponseModel):
    """Verified paper-ledger strategy attribution response."""

    schema_version: int = 1
    source: str = "verified_paper_ledger"
    verified_ledger_event_count: int = Field(default=0, ge=0)
    supported_close_event_count: int = Field(default=0, ge=0)
    completed_trade_count: int = Field(default=0, ge=0)
    overall: StrategyPerformanceSummary = Field(default_factory=StrategyPerformanceSummary)
    by_strategy: list[dict[str, Any]] = Field(default_factory=list)
    by_symbol: list[dict[str, Any]] = Field(default_factory=list)
    by_direction: list[dict[str, Any]] = Field(default_factory=list)
    by_exit_reason: list[dict[str, Any]] = Field(default_factory=list)
    ledger_writes_performed: int = Field(default=0, ge=0)
    broker_orders_submitted: int = Field(default=0, ge=0)
    safe_for_live_trading: Literal[False] = False
    protocol_live_trading_permitted: Literal[False] = False


class MarketHealthResponse(AnalyticsResponseModel):
    """Health metadata for one market data series."""

    latest_timestamp: str | None = None
    rows: int = Field(default=0, ge=0)


class ProspectivePaperHealthResponse(AnalyticsResponseModel):
    """Verified prospective paper runtime health response."""

    status: str
    ledger_events: int = Field(default=0, ge=0)
    candidate_balance: float | None = None
    shadow_balance: float | None = None
    broker_orders_sent: int = Field(default=0, ge=0)
    network_calls_made: int = Field(default=0, ge=0)
    files_changed: int = Field(default=0, ge=0)
    open_positions: int = Field(default=0, ge=0)
    pending_entries: int = Field(default=0, ge=0)
    last_completed_session_date: str | None = None
    last_event_type: str | None = None
    last_sequence: int | None = None
    markets: dict[str, MarketHealthResponse] = Field(default_factory=dict)
    transition_journal_present: bool = False
    report_network_calls_made: int = Field(default=0, ge=0)
    report_files_changed: int = Field(default=0, ge=0)
    report_ledger_writes_performed: int = Field(default=0, ge=0)
    report_broker_orders_submitted: int = Field(default=0, ge=0)
    safe_for_live_trading: Literal[False] = False
    protocol_live_trading_permitted: Literal[False] = False


class OperatorStatusResponse(AnalyticsResponseModel):
    """Verified prospective paper operator-status response."""

    status: str
    runtime_health: str | None = None
    performance_status: str | None = None
    rolling_analytics_status: str | None = None
    observation_integrity_status: str | None = None
    evidence_gate_status: str | None = None
    live_trading_decision: str | None = None
    safe_to_continue_paper_observation: bool = False
    completed_sessions: int = Field(default=0, ge=0)
    positions_opened: int = Field(default=0, ge=0)
    positions_closed: int = Field(default=0, ge=0)
    actionable_signals: int = Field(default=0, ge=0)
    observations_recorded: int = Field(default=0, ge=0)
    observation_outcomes_populated: int = Field(default=0, ge=0)
    candidate_balance: float | None = None
    shadow_balance: float | None = None
    candidate_return_percent: float | None = None
    shadow_return_percent: float | None = None
    candidate_max_drawdown_percent: float | None = None
    shadow_max_drawdown_percent: float | None = None
    earliest_eligible_assessment_date: str | None = None
    warnings: list[str] = Field(default_factory=list)
    observation_integrity_warnings: list[str] = Field(
        default_factory=list
    )
    blocking_issues: list[str] = Field(default_factory=list)
    protocol_failed_criteria: list[str] = Field(default_factory=list)
    protocol_unevaluable_criteria: list[str] = Field(default_factory=list)
    protocol_immediate_stop_reasons: list[str] = Field(default_factory=list)
    broker_orders_sent: int = Field(default=0, ge=0)
    network_calls_made: int = Field(default=0, ge=0)
    files_changed: int = Field(default=0, ge=0)
    ledger_writes_performed: int = Field(default=0, ge=0)
    broker_orders_submitted: int = Field(default=0, ge=0)
    safe_for_live_trading: Literal[False] = False
    protocol_live_trading_permitted: Literal[False] = False


class BestStrategyResponse(AnalyticsResponseModel):
    """Best-performing strategy summary."""

    strategy: str | None = None
    net_profit_percent: float | None = None
    total_trades: int | None = Field(default=None, ge=0)
    win_rate_percent: float | None = None


class AnalyticsOverviewSummary(AnalyticsResponseModel):
    """Condensed dashboard summary."""

    candidate_balance: float | None = None
    shadow_balance: float | None = None
    open_positions: int | None = Field(default=None, ge=0)
    pending_entries: int | None = Field(default=None, ge=0)
    completed_trade_count: int = Field(default=0, ge=0)
    net_profit_percent: float | None = None
    win_rate_percent: float | None = None
    best_strategy: BestStrategyResponse | None = None
    last_completed_session_date: str | None = None
    operator_status: str | None = None
    runtime_health: str | None = None
    performance_status: str | None = None
    rolling_analytics_status: str | None = None
    observation_integrity_status: str | None = None
    observations_recorded: int | None = Field(
        default=None,
        ge=0,
    )
    observation_outcomes_populated: int | None = Field(
        default=None,
        ge=0,
    )
    evidence_gate_status: str | None = None
    safe_to_continue_paper_observation: bool | None = None
    earliest_eligible_assessment_date: str | None = None


class AnalyticsOverviewSafety(AnalyticsSafetyResponse):
    """Safety and verification state for the overview response."""

    paper_trading_only: bool = True
    runtime_verified: bool = False
    ledger_verified: bool = False


class AnalyticsOverviewResponse(AnalyticsResponseModel):
    """Combined operator-facing analytics response."""

    schema_version: int
    status: str
    summary: AnalyticsOverviewSummary
    runtime: ProspectivePaperHealthResponse
    operator_status: OperatorStatusResponse
    strategy_attribution: StrategyAttributionResponse
    safety: AnalyticsOverviewSafety
    safe_for_live_trading: Literal[False] = False
    protocol_live_trading_permitted: Literal[False] = False


class AnalyticsErrorResponse(AnalyticsSafetyResponse):
    """Documented analytics conflict response."""

    status: str
    error: str


class ReadinessCountProgress(AnalyticsResponseModel):
    """Progress toward a count-based protocol threshold."""

    current: int = Field(ge=0)
    required: int = Field(ge=0)
    remaining: int = Field(ge=0)
    requirement_met: bool


class ReadinessCalendarProgress(AnalyticsResponseModel):
    """Progress toward the protocol calendar gate."""

    earliest_eligible_assessment_date: str | None = None
    requirement_met: bool


class ReadinessProgressResponse(AnalyticsResponseModel):
    """Protocol progress without invented scoring."""

    completed_sessions: ReadinessCountProgress
    closed_trades: ReadinessCountProgress
    calendar_requirement: ReadinessCalendarProgress


class AnalyticsReadinessResponse(AnalyticsSafetyResponse):
    """Protocol-grounded operator readiness decision."""

    schema_version: int = 1
    status: str
    current_stage: str
    next_stage: str | None = None
    evidence_gate_status: str | None = None
    progress: ReadinessProgressResponse
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    observation_integrity_status: str | None = None
    observations_recorded: int = Field(default=0, ge=0)
    observation_outcomes_populated: int = Field(default=0, ge=0)
    observation_integrity_warnings: list[str] = Field(
        default_factory=list
    )
    failed_criteria: list[str] = Field(default_factory=list)
    unevaluable_criteria: list[str] = Field(default_factory=list)
    immediate_stop_reasons: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    paper_observation_allowed: bool = False
    live_trading_allowed: Literal[False] = False


class AnalyticsReadinessExplanationResponse(AnalyticsSafetyResponse):
    """Deterministic operator readiness briefing."""

    schema_version: int = 1
    status: str
    current_stage: str
    headline: str
    briefing: str
    status_summary: str
    requirement_summary: str
    evidence_summary: str
    progress_summary: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    safety_statement: str
    paper_observation_allowed: bool = False
    live_trading_allowed: Literal[False] = False


class EvidenceCockpitResponse(AnalyticsSafetyResponse):
    """Canonical read-only prospective evidence cockpit."""

    schema_version: int = 1
    status: str
    generated_at_utc: str
    current_software_commit: str
    tracked_source_clean: bool
    current_policy_fingerprint: str
    protocol_mode: Literal["SIMULATION_ONLY"] = "SIMULATION_ONLY"
    live_order_submission_permitted: Literal[False] = False
    runtime_health: str | None = None
    operator_status: str | None = None
    evidence_gate_status: str | None = None
    observation_integrity_status: str | None = None
    candidate_balance: float | None = None
    shadow_balance: float | None = None
    broker_orders_sent: int = Field(default=0, ge=0)
    last_completed_session_date: str | None = None
    next_session_date: str | None = None
    next_action: str
    markets_aligned: bool
    markets: list[dict[str, Any]] = Field(default_factory=list)
    pending_entries: list[dict[str, Any]] = Field(default_factory=list)
    open_positions: list[dict[str, Any]] = Field(default_factory=list)
    observations_recorded: int = Field(default=0, ge=0)
    observation_outcomes_populated: int = Field(default=0, ge=0)
    session_lineage: list[dict[str, Any]] = Field(default_factory=list)
    software_changed_since_last_session: bool
    policy_matches_last_session: bool
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    readiness_next_actions: list[str] = Field(default_factory=list)


class OperatorAlert(AnalyticsResponseModel):
    """One stable notification-only operator alert."""

    alert_id: str
    alert_type: str
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    status: Literal["ACTIVE"] = "ACTIVE"
    title: str
    message: str
    detected_at_utc: str
    evidence_timestamp_utc: str | None = None
    market: str | None = None
    session_date: str | None = None
    software_commit: str
    policy_fingerprint: str
    recommended_action: str
    requires_operator_action: bool = False
    delivery_mode: Literal["NOTIFICATION_ONLY"] = "NOTIFICATION_ONLY"
    order_action_permitted: Literal[False] = False


class OperatorAlertReportResponse(AnalyticsSafetyResponse):
    """Active alerts derived without mutation or external delivery."""

    schema_version: int = 1
    status: str
    generated_at_utc: str
    delivery_mode: Literal["NOTIFICATION_ONLY"] = "NOTIFICATION_ONLY"
    active_alert_count: int = Field(default=0, ge=0)
    critical_alert_count: int = Field(default=0, ge=0)
    warning_alert_count: int = Field(default=0, ge=0)
    alerts: list[OperatorAlert] = Field(default_factory=list)
