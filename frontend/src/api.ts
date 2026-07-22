import type {
  AiInsightAppendResponse,
  AiInsightListResponse,
  AnnotationAppendResponse,
  AnnotationCategory,
  AnnotationListResponse,
  DashboardData,
  DecisionEvaluationResponse,
  EvidenceCockpitResponse,
  EvidenceBriefingResponse,
  OperatorAlertReportResponse,
  OutcomeExplorerResponse,
  PortfolioIntelligenceResponse,
  ReadinessExplanationResponse,
  ReadinessResponse,
  ScannerResult,
  ScannerSource,
} from "./types";

interface CandlePayload {
  symbol: string;
  timeframe: string;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

async function requestJson<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(`/api${path}`, options);

  if (!response.ok) {
    let detail = "";

    try {
      const body = (await response.json()) as {
        detail?: unknown;
      };

      detail = body.detail
        ? `: ${JSON.stringify(body.detail)}`
        : "";
    } catch {
      detail = "";
    }

    throw new Error(
      `${path} returned ${response.status}${detail}`,
    );
  }

  return (await response.json()) as T;
}

function buildDecisionPayload() {
  const candles: CandlePayload[] = [];
  const start = new Date("2026-01-01T00:00:00.000Z");

  for (let index = 0; index < 50; index += 1) {
    const close = 1.1 + index * 0.0006;
    const timestamp = new Date(
      start.getTime() + index * 60 * 60 * 1000,
    );

    candles.push({
      symbol: "EUR_USD",
      timeframe: "H1",
      timestamp: timestamp.toISOString(),
      open: close - 0.0002,
      high: close + 0.0003,
      low: close - 0.0003,
      close,
      volume: 1000 + index,
    });
  }

  const recentCandles = candles.slice(-20);
  const previousHigh = Math.max(
    ...recentCandles.map((candle) => candle.high),
  );
  const entryPrice = previousHigh + 0.001;
  const breakoutTimestamp = new Date(
    start.getTime() + 50 * 60 * 60 * 1000,
  );

  candles.push({
    symbol: "EUR_USD",
    timeframe: "H1",
    timestamp: breakoutTimestamp.toISOString(),
    open: entryPrice - 0.0004,
    high: entryPrice + 0.0003,
    low: entryPrice - 0.0005,
    close: entryPrice,
    volume: 1400,
  });

  return {
    strategy_name: "atr_breakout",
    candles,
    entry_price: entryPrice,
    stop_loss: entryPrice - 0.002,
    take_profit: entryPrice + 0.004,
    base_risk_percent: 0.5,
    minimum_risk_reward: 1.5,
    minimum_regime_confidence: 0.6,
  };
}

export async function fetchDecisionEvaluation(): Promise<DecisionEvaluationResponse> {
  return requestJson<DecisionEvaluationResponse>(
    "/decision/evaluate",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(buildDecisionPayload()),
    },
  );
}

export async function fetchDashboardData(
  scannerSource: ScannerSource = "synthetic",
): Promise<DashboardData> {
  const [readiness, explanation, cockpit, alerts, portfolio, outcomes, annotations, aiBriefing, aiInsights, decision, scanner] =
    await Promise.all([
      requestJson<ReadinessResponse>("/analytics/readiness"),
      requestJson<ReadinessExplanationResponse>(
        "/analytics/readiness-explanation",
      ),
      requestJson<EvidenceCockpitResponse>(
        "/analytics/evidence-cockpit",
      ),
      requestJson<OperatorAlertReportResponse>("/analytics/alerts"),
      requestJson<PortfolioIntelligenceResponse>(
        "/analytics/portfolio-intelligence",
      ),
      requestJson<OutcomeExplorerResponse>(
        "/analytics/outcome-explorer",
      ),
      fetchOperatorAnnotations(),
      requestJson<EvidenceBriefingResponse>("/ai/evidence-briefing"),
      fetchAiInsights(),
      fetchDecisionEvaluation(),
      fetchScannerOpportunities(scannerSource),
    ]);

  return {
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
  };
}

export async function fetchAiInsights(): Promise<AiInsightListResponse> {
  return requestJson<AiInsightListResponse>("/ai/evidence-insights");
}

export async function saveOfflineAiInsight(
  idempotencyKey: string,
): Promise<AiInsightAppendResponse> {
  return requestJson<AiInsightAppendResponse>("/ai/evidence-briefing", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      idempotency_key: idempotencyKey,
      provider_mode: "OFFLINE",
    }),
  });
}

export async function fetchOperatorAnnotations(): Promise<AnnotationListResponse> {
  return requestJson<AnnotationListResponse>(
    "/operator-review/annotations",
  );
}

export async function createOperatorAnnotation(input: {
  idempotency_key: string;
  subject_id: string;
  category: AnnotationCategory;
  note: string;
  subject_type?: "ALERT" | "AI_INSIGHT";
}): Promise<AnnotationAppendResponse> {
  return requestJson<AnnotationAppendResponse>(
    "/operator-review/annotations",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...input,
        subject_type: input.subject_type ?? "ALERT",
      }),
    },
  );
}


export async function fetchScannerOpportunities(
  source: ScannerSource = "synthetic",
): Promise<ScannerResult> {
  const query = source === "oanda" ? "?source=oanda" : "";

  return requestJson<ScannerResult>(
    `/scanner/opportunities${query}`,
  );
}
