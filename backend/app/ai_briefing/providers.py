"""Offline-first evidence analyst providers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol

from app.ai_briefing.models import (
    BriefingDraft,
    EvidenceCitation,
    SanitizedEvidenceSnapshot,
)
from app.ai_briefing.prompt import SYSTEM_INSTRUCTIONS


class BriefingProviderError(RuntimeError):
    """Raised when a provider cannot return a valid structured briefing."""


class EvidenceBriefingProvider(Protocol):
    mode: str
    model: str
    network_calls_made: int

    def generate(self, snapshot: SanitizedEvidenceSnapshot) -> BriefingDraft: ...


class DeterministicEvidenceProvider:
    mode = "OFFLINE"
    model = "deterministic-evidence-analyst-v1"
    network_calls_made = 0

    def generate(self, snapshot: SanitizedEvidenceSnapshot) -> BriefingDraft:
        by_type = {item.evidence_type: item for item in snapshot.evidence_items}
        cockpit = by_type["COCKPIT"]
        portfolio = by_type["PORTFOLIO"]
        outcomes = by_type["OUTCOMES"]
        cockpit_facts = cockpit.facts
        portfolio_facts = portfolio.facts
        outcome_facts = outcomes.facts
        pending = list(cockpit_facts.get("pending_markets") or [])
        outcome_count = int(outcome_facts.get("outcome_count", 0))
        minimum_outcomes = int(outcome_facts.get("minimum_overall_sample", 0))
        available_pairs = int(portfolio_facts.get("available_correlation_pair_count", 0))
        pair_count = int(portfolio_facts.get("correlation_pair_count", 0))
        max_aligned = int(portfolio_facts.get("maximum_aligned_returns_observed", 0))
        min_aligned = int(portfolio_facts.get("minimum_aligned_returns_required", 0))

        headline = (
            "Continue guarded observation; the evidence cannot support a performance conclusion."
            if outcome_count < minimum_outcomes
            else "Outcome evidence is available for human review; live trading remains prohibited."
        )
        what_changed = [
            "The verified cockpit reports "
            f"{cockpit_facts.get('observations_recorded', 0)} observations and "
            f"{outcome_count} populated outcomes.",
            f"Paper state contains {len(pending)} pending "
            f"entr{'y' if len(pending) == 1 else 'ies'} and "
            f"{len(cockpit_facts.get('open_markets') or [])} open positions.",
        ]
        if pending:
            what_changed.append(f"The pending paper market is {', '.join(pending)}.")
        why_waiting = []
        if outcome_count < minimum_outcomes:
            why_waiting.append(
                f"Outcome analysis is withheld at {outcome_count}/{minimum_outcomes} "
                "required completed outcomes."
            )
        if available_pairs < pair_count:
            why_waiting.append(
                "Correlation evidence is incomplete: "
                f"{available_pairs}/{pair_count} pairs are interpretable, with at most "
                f"{max_aligned}/{min_aligned} aligned returns."
            )
        if pending:
            why_waiting.append("The pending paper entry must wait for a later complete candle.")
        missing = []
        if outcome_count < minimum_outcomes:
            missing.append(
                f"At least {minimum_outcomes - outcome_count} more completed outcomes "
                "for overall metrics."
            )
        if available_pairs < pair_count:
            missing.append(
                "More aligned close-to-close returns for portfolio correlation estimates."
            )
        risks = ["Sparse evidence can make apparent patterns unreliable."]
        if pending:
            risks.append(
                "The pending paper entry is evidence to monitor, not authorization to trade."
            )
        questions = [
            "Did the next complete candle resolve the pending paper entry under the frozen policy?",
            "Did any new outcome cross a declared sample threshold without integrity warnings?",
        ]
        return BriefingDraft(
            headline=headline,
            what_changed=what_changed,
            why_waiting=why_waiting,
            missing_evidence=missing,
            risks_to_review=risks,
            next_review_questions=questions,
            citations=[
                EvidenceCitation(
                    evidence_id=cockpit.evidence_id, label="Verified evidence cockpit"
                ),
                EvidenceCitation(evidence_id=portfolio.evidence_id, label="Portfolio intelligence"),
                EvidenceCitation(evidence_id=outcomes.evidence_id, label="Outcome explorer"),
            ],
        )


Transport = Callable[[str, dict[str, str], bytes, float], dict[str, Any]]


def _urlopen_transport(
    url: str, headers: dict[str, str], body: bytes, timeout: float
) -> dict[str, Any]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise BriefingProviderError("Hosted evidence analyst request failed.") from error


class OpenAIResponsesProvider:
    """Optional explicit adapter; it receives only SanitizedEvidenceSnapshot."""

    mode = "OPENAI"
    network_calls_made = 1

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        transport: Transport = _urlopen_transport,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not api_key:
            raise BriefingProviderError("OPENAI_API_KEY is required for hosted briefings.")
        self.api_key = api_key
        self.model = model
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    def generate(self, snapshot: SanitizedEvidenceSnapshot) -> BriefingDraft:
        schema = BriefingDraft.model_json_schema()
        payload = {
            "model": self.model,
            "instructions": SYSTEM_INSTRUCTIONS,
            "input": snapshot.model_dump_json(),
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "evidence_briefing",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        response = self.transport(
            "https://api.openai.com/v1/responses",
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json.dumps(payload).encode("utf-8"),
            self.timeout_seconds,
        )
        text = response.get("output_text")
        if not isinstance(text, str):
            for output in response.get("output", []):
                for content in output.get("content", []):
                    if content.get("type") == "output_text":
                        text = content.get("text")
                        break
        try:
            return BriefingDraft.model_validate_json(text)
        except (TypeError, ValueError) as error:
            raise BriefingProviderError("Hosted analyst returned an invalid briefing.") from error
