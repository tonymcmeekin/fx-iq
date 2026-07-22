"""Exercise the hosted-AI contract locally without network or persistent writes."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
PAPER_LEDGER_DIRECTORY = BACKEND_DIRECTORY / "paper_ledger"

if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIRECTORY))

from app.ai_briefing.models import (  # noqa: E402
    BriefingGenerateRequest,
    SanitizedEvidenceSnapshot,
)
from app.ai_briefing.providers import (  # noqa: E402
    DeterministicEvidenceProvider,
    OpenAIResponsesProvider,
)
from app.ai_briefing.service import (  # noqa: E402
    build_ai_governance_report,
    generate_and_store_insight,
)
from app.ai_briefing.store import read_insights  # noqa: E402


class SimulatedHostedTrialError(RuntimeError):
    pass


class LocalResponsesTransport:
    """Implement the adapter callback entirely in memory."""

    def __init__(self) -> None:
        self.call_count = 0
        self.request_payload: dict[str, Any] | None = None
        self.authorization_header_present = False

    def __call__(
        self,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> dict[str, Any]:
        if url != "https://api.openai.com/v1/responses" or timeout <= 0:
            raise SimulatedHostedTrialError("Hosted adapter contract was not respected.")
        self.call_count += 1
        self.authorization_header_present = "Authorization" in headers
        self.request_payload = json.loads(body)
        snapshot = SanitizedEvidenceSnapshot.model_validate_json(
            self.request_payload["input"]
        )
        briefing = DeterministicEvidenceProvider().generate(snapshot)
        return {"output_text": briefing.model_dump_json()}


def runtime_metadata(directory: Path) -> tuple[tuple[str, int, int], ...]:
    if not directory.exists():
        return ()
    return tuple(
        sorted(
            (
                str(path.relative_to(directory)),
                path.stat().st_size,
                path.stat().st_mtime_ns,
            )
            for path in directory.rglob("*")
            if path.is_file()
        )
    )


def run_trial(
    *,
    reports: tuple[dict[str, Any], ...] | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    before_runtime = runtime_metadata(PAPER_LEDGER_DIRECTORY)
    transport = LocalResponsesTransport()
    provider = OpenAIResponsesProvider(
        api_key="simulated-local-adapter",
        model="simulated-hosted-contract-v1",
        transport=transport,
    )
    resolved_now = now_utc or datetime.now(UTC)

    with tempfile.TemporaryDirectory(prefix="trade-iq-ai-trial-") as directory:
        temporary = Path(directory)
        insight_path = temporary / "insights.jsonl"
        rejection_path = temporary / "rejections.jsonl"
        annotation_path = temporary / "annotations.jsonl"
        generated = generate_and_store_insight(
            BriefingGenerateRequest(
                idempotency_key="simulated-hosted-trial",
                provider_mode="OPENAI",
                external_transmission_confirmed=True,
            ),
            insight_path=insight_path,
            rejection_path=rejection_path,
            reports=reports,
            provider=provider,
            now_utc=resolved_now,
        )
        insights = read_insights(insight_path)
        governance = build_ai_governance_report(
            insight_path=insight_path,
            rejection_path=rejection_path,
            annotation_path=annotation_path,
        )
        payload = transport.request_payload or {}
        input_text = str(payload.get("input", ""))
        checks = {
            "adapter_called_once": transport.call_count == 1,
            "authorization_contract_present": transport.authorization_header_present,
            "request_storage_disabled": payload.get("store") is False,
            "structured_output_required": (
                payload.get("text", {}).get("format", {}).get("type") == "json_schema"
            ),
            "sanitized_snapshot_used": (
                "oanda_account_id" not in input_text
                and "operator_note" not in input_text
                and generated["safety"]["credentials_included"] is False
                and generated["safety"]["raw_market_data_included"] is False
            ),
            "quality_gate_passed": generated["insight"]["quality_gate"]["status"] == "PASS",
            "temporary_chain_verified": len(insights) == 1,
            "human_review_required": governance["status"] == "REVIEW_REQUIRED",
            "broker_orders_zero": generated["safety"]["broker_orders_submitted"] == 0,
        }

    after_runtime = runtime_metadata(PAPER_LEDGER_DIRECTORY)
    checks["persistent_runtime_unchanged"] = before_runtime == after_runtime
    if not all(checks.values()):
        failures = [name for name, passed in checks.items() if not passed]
        raise SimulatedHostedTrialError("Simulated hosted trial failed: " + ", ".join(failures))
    return {
        "status": "PASS",
        "external_network_calls_made": 0,
        "adapter_requests_made": transport.call_count,
        "persistent_runtime_files_changed": 0,
        "broker_orders_submitted": 0,
        "request_storage_enabled": False,
        "quality_gate": "PASS",
        "governance_status": governance["status"],
        "checks": checks,
    }


def main() -> int:
    try:
        run_trial()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"SIMULATED HOSTED AI TRIAL: FAIL\n{error}")
        return 1
    print("SIMULATED HOSTED AI TRIAL: PASS")
    print("External network calls: 0")
    print("Persistent runtime files changed: 0")
    print("Broker orders submitted: 0")
    print("OpenAI request storage: disabled")
    print("Deterministic quality gate: PASS")
    print("Temporary insight chain: verified")
    print("Human review gate: required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
