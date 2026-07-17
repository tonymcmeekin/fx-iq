from app.decision.models import DecisionEvaluationRequest
from app.scanner.engine import (
    build_sample_scan_requests,
    scan_opportunities,
    scan_sample_opportunities,
)


def test_sample_scanner_evaluates_multiple_markets():
    result = scan_sample_opportunities()

    assert result.evaluated_markets == 8
    assert len(result.opportunities) == 8
    assert (
        result.allow_count
        + result.watch_count
        + result.reject_count
        == result.evaluated_markets
    )


def test_sample_scanner_ranks_allow_before_reject():
    result = scan_sample_opportunities()

    priorities = {
        "ALLOW": 0,
        "WATCH": 1,
        "REJECT": 2,
    }

    ranking = [
        priorities[opportunity.decision]
        for opportunity in result.opportunities
    ]

    assert ranking == sorted(ranking)


def test_sample_scanner_ranks_confidence_descending_within_decision():
    result = scan_sample_opportunities()

    for decision in ("ALLOW", "WATCH", "REJECT"):
        scores = [
            opportunity.confidence_score
            for opportunity in result.opportunities
            if opportunity.decision == decision
        ]

        assert scores == sorted(scores, reverse=True)


def test_sample_scanner_assigns_sequential_ranks():
    result = scan_sample_opportunities()

    assert [
        opportunity.rank
        for opportunity in result.opportunities
    ] == list(range(1, 9))


def test_sample_scanner_is_read_only():
    result = scan_sample_opportunities()

    assert result.paper_trading_only is True
    assert result.live_trading_allowed is False
    assert result.broker_orders_submitted == 0
    assert result.network_calls_made == 0
    assert result.ledger_writes_performed == 0

    for opportunity in result.opportunities:
        assert opportunity.paper_trading_only is True
        assert opportunity.live_trading_allowed is False
        assert opportunity.broker_orders_submitted == 0
        assert opportunity.network_calls_made == 0
        assert opportunity.ledger_writes_performed == 0


def test_scanner_uses_existing_decision_requests():
    requests = build_sample_scan_requests()

    assert len(requests) == 8
    assert all(
        isinstance(request, DecisionEvaluationRequest)
        for request in requests
    )


def test_scanner_accepts_explicit_request_list():
    requests = build_sample_scan_requests()[:2]

    result = scan_opportunities(requests)

    assert result.evaluated_markets == 2
    assert len(result.opportunities) == 2
