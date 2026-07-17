import { useMemo, useState } from "react";

import type {
  DecisionClassification,
  ScannerOpportunity,
  ScannerResult,
} from "../types";

type DecisionFilter = "ALL" | DecisionClassification;
type TimeframeFilter = "ALL" | string;

interface MarketScannerProps {
  scanner: ScannerResult;
}

function formatLabel(value: string): string {
  return value
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatSymbol(symbol: string): string {
  return symbol.replace("_", "/");
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

function opportunityClass(
  opportunity: ScannerOpportunity,
): string {
  return [
    "scanner-row",
    `scanner-row--${opportunity.decision.toLowerCase()}`,
  ].join(" ");
}

export function MarketScanner({
  scanner,
}: MarketScannerProps) {
  const [decisionFilter, setDecisionFilter] =
    useState<DecisionFilter>("ALL");
  const [timeframeFilter, setTimeframeFilter] =
    useState<TimeframeFilter>("ALL");
  const [selectedRank, setSelectedRank] = useState<number | null>(
    scanner.opportunities[0]?.rank ?? null,
  );

  const timeframes = useMemo(
    () =>
      Array.from(
        new Set(
          scanner.opportunities.map(
            (opportunity) => opportunity.timeframe,
          ),
        ),
      ).sort(),
    [scanner.opportunities],
  );

  const filteredOpportunities = useMemo(
    () =>
      scanner.opportunities.filter((opportunity) => {
        const decisionMatches =
          decisionFilter === "ALL" ||
          opportunity.decision === decisionFilter;

        const timeframeMatches =
          timeframeFilter === "ALL" ||
          opportunity.timeframe === timeframeFilter;

        return decisionMatches && timeframeMatches;
      }),
    [
      decisionFilter,
      timeframeFilter,
      scanner.opportunities,
    ],
  );

  const selectedOpportunity =
    scanner.opportunities.find(
      (opportunity) => opportunity.rank === selectedRank,
    ) ??
    filteredOpportunities[0] ??
    null;

  return (
    <section className="scanner-panel">
      <div className="scanner-heading">
        <div>
          <span className="eyebrow">Market universe</span>
          <h2>Opportunity scanner</h2>
          <p>
            Deterministic ranking across configured symbols and
            timeframes.
          </p>
        </div>

        <div className="scanner-summary">
          <div>
            <span>Evaluated</span>
            <strong>{scanner.evaluated_markets}</strong>
          </div>

          <div>
            <span>Allow</span>
            <strong>{scanner.allow_count}</strong>
          </div>

          <div>
            <span>Watch</span>
            <strong>{scanner.watch_count}</strong>
          </div>

          <div>
            <span>Reject</span>
            <strong>{scanner.reject_count}</strong>
          </div>
        </div>
      </div>

      <div className="scanner-filters">
        <label>
          <span>Decision</span>
          <select
            value={decisionFilter}
            onChange={(event) =>
              setDecisionFilter(
                event.target.value as DecisionFilter,
              )
            }
          >
            <option value="ALL">All decisions</option>
            <option value="ALLOW">Allow</option>
            <option value="WATCH">Watch</option>
            <option value="REJECT">Reject</option>
          </select>
        </label>

        <label>
          <span>Timeframe</span>
          <select
            value={timeframeFilter}
            onChange={(event) =>
              setTimeframeFilter(event.target.value)
            }
          >
            <option value="ALL">All timeframes</option>
            {timeframes.map((timeframe) => (
              <option key={timeframe} value={timeframe}>
                {timeframe}
              </option>
            ))}
          </select>
        </label>

        <span className="badge badge--neutral">
          {filteredOpportunities.length} shown
        </span>
      </div>

      <div className="scanner-layout">
        <div className="scanner-table-wrapper">
          <table className="scanner-table">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Market</th>
                <th>Timeframe</th>
                <th>Direction</th>
                <th>Decision</th>
                <th>Confidence</th>
                <th>R:R</th>
                <th>Regime</th>
              </tr>
            </thead>

            <tbody>
              {filteredOpportunities.map((opportunity) => (
                <tr
                  className={opportunityClass(opportunity)}
                  key={`${opportunity.symbol}-${opportunity.timeframe}`}
                  onClick={() =>
                    setSelectedRank(opportunity.rank)
                  }
                >
                  <td>#{opportunity.rank}</td>
                  <td>
                    <strong>
                      {formatSymbol(opportunity.symbol)}
                    </strong>
                  </td>
                  <td>{opportunity.timeframe}</td>
                  <td>{opportunity.direction}</td>
                  <td>
                    <span
                      className={decisionBadgeClass(
                        opportunity.decision,
                      )}
                    >
                      {opportunity.decision}
                    </span>
                  </td>
                  <td>
                    {opportunity.confidence_score.toFixed(2)}%
                  </td>
                  <td>
                    {opportunity.risk_reward_ratio.toFixed(2)}:1
                  </td>
                  <td>
                    {formatLabel(opportunity.market_regime)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {filteredOpportunities.length === 0 && (
            <div className="scanner-empty">
              No opportunities match the selected filters.
            </div>
          )}
        </div>

        <aside className="scanner-detail">
          {selectedOpportunity ? (
            <>
              <div className="panel-heading">
                <div>
                  <span className="eyebrow">
                    Selected opportunity
                  </span>
                  <h3>
                    {formatSymbol(selectedOpportunity.symbol)}{" "}
                    {selectedOpportunity.timeframe}
                  </h3>
                </div>

                <span
                  className={decisionBadgeClass(
                    selectedOpportunity.decision,
                  )}
                >
                  {selectedOpportunity.decision}
                </span>
              </div>

              <div className="scanner-detail-metrics">
                <div>
                  <span>Direction</span>
                  <strong>{selectedOpportunity.direction}</strong>
                </div>

                <div>
                  <span>Confidence</span>
                  <strong>
                    {selectedOpportunity.confidence_score.toFixed(
                      2,
                    )}
                    %
                  </strong>
                </div>

                <div>
                  <span>Risk / reward</span>
                  <strong>
                    {selectedOpportunity.risk_reward_ratio.toFixed(
                      2,
                    )}
                    :1
                  </strong>
                </div>

                <div>
                  <span>Adjusted risk</span>
                  <strong>
                    {selectedOpportunity.adjusted_risk_percent.toFixed(
                      2,
                    )}
                    %
                  </strong>
                </div>
              </div>

              <p>{selectedOpportunity.explanation}</p>

              <dl className="scanner-detail-list">
                <div>
                  <dt>Strategy</dt>
                  <dd>
                    {formatLabel(
                      selectedOpportunity.strategy_name,
                    )}
                  </dd>
                </div>

                <div>
                  <dt>Regime</dt>
                  <dd>
                    {formatLabel(
                      selectedOpportunity.market_regime,
                    )}
                  </dd>
                </div>

                <div>
                  <dt>Warnings</dt>
                  <dd>{selectedOpportunity.warning_count}</dd>
                </div>

                <div>
                  <dt>Blocking reasons</dt>
                  <dd>
                    {selectedOpportunity.blocking_reason_count}
                  </dd>
                </div>

                <div>
                  <dt>Paper trade approved</dt>
                  <dd>
                    {selectedOpportunity.approved_for_paper_trade
                      ? "Yes"
                      : "No"}
                  </dd>
                </div>
              </dl>
            </>
          ) : (
            <p>Select an opportunity to inspect it.</p>
          )}
        </aside>
      </div>

      <div className="safety-strip">
        <div>
          <span>Paper trading only</span>
          <strong>
            {scanner.paper_trading_only ? "Enabled" : "Disabled"}
          </strong>
        </div>

        <div>
          <span>Live trading</span>
          <strong>
            {scanner.live_trading_allowed
              ? "Enabled"
              : "Disabled"}
          </strong>
        </div>

        <div>
          <span>Broker orders</span>
          <strong>{scanner.broker_orders_submitted}</strong>
        </div>

        <div>
          <span>Network calls</span>
          <strong>{scanner.network_calls_made}</strong>
        </div>

        <div>
          <span>Ledger writes</span>
          <strong>{scanner.ledger_writes_performed}</strong>
        </div>
      </div>
    </section>
  );
}
