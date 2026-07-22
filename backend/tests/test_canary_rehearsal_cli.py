from app.broker.canary_failure_audit import read_canary_failure_audit
from app.broker.canary_gateway import (
    CanaryFailureContext,
    CanaryGatewayError,
    CanaryRehearsalResult,
)
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


def test_cli_passes_explicit_gbp_budget_to_gateway(monkeypatch, tmp_path):
    captured = []

    class SuccessfulGateway:
        def __init__(self, **kwargs):
            pass

        def rehearse(self, request):
            captured.append(request)
            return CanaryRehearsalResult(
                status="PRACTICE_REHEARSAL_COMPLETE",
                environment="practice",
                rehearsal_id=request.rehearsal_id,
                account_fingerprint="a" * 64,
                instrument="EUR_GBP",
                direction="BUY",
                units=1,
                entry_transaction_id="1",
                trade_id="2",
                close_transaction_id="3",
                network_calls_made=8,
                practice_entry_orders_submitted=1,
                practice_close_orders_submitted=1,
                live_orders_submitted=0,
                position_verified_open=True,
                position_verified_closed=True,
                live_canary_build_enabled=False,
                entry_reference_price="0.8502",
                entry_fill_price="0.85025",
                exit_fill_price="0.85015",
                entry_slippage_price="0.00005",
                entry_slippage_gbp="0.00005",
                realized_pl_gbp="-0.0001",
                financing_gbp="0",
                commission_gbp="0",
                guaranteed_execution_fee_gbp="0",
                net_account_impact_gbp="-0.0001",
            )

    monkeypatch.setenv("OANDA_ENVIRONMENT", "practice")
    monkeypatch.setenv("OANDA_API_TOKEN", "test-token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "999-001-12345678-001")
    monkeypatch.setattr(cli, "OandaCanaryGateway", SuccessfulGateway)
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cli, "AUDIT_PATH", tmp_path / "canary.jsonl")

    invocation = arguments()
    invocation.extend(["--maximum-loss-gbp", "42.5", "--reserved-costs-gbp", "7.25"])
    assert cli.main(invocation) == 0
    assert captured[0].maximum_loss_gbp == 42.5
    assert captured[0].reserved_costs_gbp == 7.25
