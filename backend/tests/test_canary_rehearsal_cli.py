from app.broker.canary_failure_audit import read_canary_failure_audit
from app.broker.canary_gateway import CanaryFailureContext, CanaryGatewayError
from scripts import run_oanda_practice_canary_rehearsal as cli


def arguments(confirmation=cli.CONFIRMATION):
    return [
        "--rehearsal-id",
        "cli-failure-001",
        "--instrument",
        "EUR_USD",
        "--direction",
        "BUY",
        "--stop-loss",
        "1.09",
        "--take-profit",
        "1.12",
        "--confirmation",
        confirmation,
    ]


def test_cli_records_content_safe_gateway_failure(monkeypatch, tmp_path):
    class FailingGateway:
        def __init__(self, **kwargs):
            pass

        def rehearse(self, request):
            raise CanaryGatewayError("Practice quote is stale.")

        def failure_context(self, error):
            return CanaryFailureContext(
                rehearsal_id="cli-failure-001",
                account_fingerprint="a" * 64,
                stage="PRICE_PREFLIGHT",
                failure_type=type(error).__name__,
                failure_message=str(error),
                network_calls_made=3,
                entry_request_attempted=False,
                entry_order_confirmed=False,
                close_request_attempted=False,
                close_order_confirmed=False,
                emergency_close_attempted=False,
                emergency_close_confirmed=False,
                final_reconciliation_confirmed=False,
                operator_action_required=False,
                live_orders_submitted=0,
            )

    failure_path = tmp_path / "failures.jsonl"
    monkeypatch.setenv("OANDA_ENVIRONMENT", "practice")
    monkeypatch.setenv("OANDA_API_TOKEN", "test-token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "999-001-12345678-001")
    monkeypatch.setattr(cli, "OandaCanaryGateway", FailingGateway)
    monkeypatch.setattr(cli, "FAILURE_AUDIT_PATH", failure_path)

    assert cli.main(arguments()) == 1
    records = read_canary_failure_audit(failure_path)
    assert len(records) == 1
    assert records[0]["stage"] == "PRICE_PREFLIGHT"
    assert records[0]["operator_action_required"] is False
    assert records[0]["live_orders_submitted"] == 0


def test_cli_wrong_confirmation_stops_before_gateway(monkeypatch):
    def forbidden_gateway(**kwargs):
        raise AssertionError("gateway must not be constructed")

    monkeypatch.setattr(cli, "OandaCanaryGateway", forbidden_gateway)
    assert cli.main(arguments("WRONG")) == 2
