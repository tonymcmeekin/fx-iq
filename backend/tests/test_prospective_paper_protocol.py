import hashlib
import json
from pathlib import Path


PROTOCOL_PATH = Path(
    "research_protocols/"
    "prospective_paper_trading_protocol.json"
)

FINGERPRINT_PATH = Path(
    "research_protocols/"
    "prospective_paper_policy_fingerprint.json"
)

VALIDATION_RESULTS_PATH = Path(
    "research_results/"
    "untouched_cross_market_validation_results.json"
)

EXPECTED_VALIDATION_HASH = (
    "50964f9e746310442db6447984e8d187"
    "41231620b39c3add3e3720d412aa53b9"
)


def load_json(path: Path) -> dict:
    return json.loads(
        path.read_text()
    )


def canonical_frozen_payload(
    protocol: dict,
) -> dict:
    return {
        "markets": protocol["markets"],
        "market_data": {
            "granularity": protocol[
                "market_data"
            ]["granularity"],
            "price_component": protocol[
                "market_data"
            ]["price_component"],
            "complete_candles_only": protocol[
                "market_data"
            ]["complete_candles_only"],
        },
        "frozen_strategy": protocol[
            "frozen_strategy"
        ],
        "frozen_risk_policy": protocol[
            "frozen_risk_policy"
        ],
        "portfolio_controls": protocol[
            "portfolio_controls"
        ],
        "shadow_control": protocol[
            "shadow_control"
        ],
        "execution_simulation": protocol[
            "execution_simulation"
        ],
    }


def calculate_fingerprint(
    payload: dict,
) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def test_protocol_is_preregistered_not_started():
    protocol = load_json(
        PROTOCOL_PATH
    )

    assert protocol["status"] == (
        "PREREGISTERED_NOT_STARTED"
    )

    assert protocol["mode"] == (
        "SIMULATION_ONLY"
    )

    assert (
        protocol[
            "live_order_submission_permitted"
        ]
        is False
    )


def test_validation_result_hash_is_preserved():
    actual_hash = hashlib.sha256(
        VALIDATION_RESULTS_PATH.read_bytes()
    ).hexdigest()

    assert actual_hash == EXPECTED_VALIDATION_HASH

    protocol = load_json(
        PROTOCOL_PATH
    )

    assert protocol[
        "validated_policy_source"
    ]["validation_results_sha256"] == (
        EXPECTED_VALIDATION_HASH
    )


def test_prospective_markets_are_frozen():
    protocol = load_json(
        PROTOCOL_PATH
    )

    assert protocol["markets"] == [
        "EUR_GBP",
        "EUR_JPY",
        "GBP_JPY",
        "AUD_JPY",
        "CAD_JPY",
        "AUD_CAD",
    ]


def test_validated_close_location_policy_is_frozen():
    protocol = load_json(
        PROTOCOL_PATH
    )

    policy = protocol[
        "frozen_risk_policy"
    ]

    assert policy[
        "base_risk_percent"
    ] == 0.5

    assert policy[
        "reduced_risk_percent"
    ] == 0.25

    assert policy[
        "directional_close_location_threshold"
    ] == 0.8174

    assert (
        policy[
            "risk_may_increase_above_base"
        ]
        is False
    )

    assert (
        policy[
            "trade_selection_may_change"
        ]
        is False
    )


def test_strategy_configuration_is_frozen():
    protocol = load_json(
        PROTOCOL_PATH
    )

    strategy = protocol[
        "frozen_strategy"
    ]

    assert strategy[
        "strategy_name"
    ] == "atr_breakout"

    assert strategy[
        "stop_loss_percent"
    ] == 1.5

    assert strategy[
        "take_profit_percent"
    ] == 3.0

    assert strategy[
        "spread_pips"
    ] == 1.0

    assert strategy[
        "slippage_pips"
    ] == 0.5


def test_minimum_duration_and_trade_count_are_both_required():
    protocol = load_json(
        PROTOCOL_PATH
    )

    period = protocol[
        "prospective_period"
    ]

    assert period[
        "minimum_calendar_days"
    ] == 365

    assert period[
        "minimum_closed_trades"
    ] == 50

    assert (
        period[
            "both_minimums_required"
        ]
        is True
    )


def test_live_orders_are_forbidden_everywhere():
    protocol = load_json(
        PROTOCOL_PATH
    )

    assert (
        protocol[
            "live_order_submission_permitted"
        ]
        is False
    )

    assert (
        protocol[
            "execution_simulation"
        ]["broker_orders_sent"]
        is False
    )

    assert protocol[
        "paper_test_pass_criteria"
    ]["live_orders_sent_allowed"] == 0


def test_append_only_hash_chained_ledger_is_required():
    protocol = load_json(
        PROTOCOL_PATH
    )

    ledger = protocol[
        "append_only_ledger"
    ]

    assert ledger["format"] == "JSONL"

    assert (
        ledger[
            "event_hash_chain_required"
        ]
        is True
    )

    assert (
        ledger[
            "duplicate_event_ids_forbidden"
        ]
        is True
    )

    assert (
        ledger[
            "existing_events_may_not_be_modified_or_deleted"
        ]
        is True
    )


def test_candidate_must_beat_fixed_shadow():
    protocol = load_json(
        PROTOCOL_PATH
    )

    assert protocol[
        "shadow_control"
    ]["enabled"] is True

    assert protocol[
        "paper_test_pass_criteria"
    ][
        "candidate_return_must_exceed_shadow_fixed_return"
    ] is True

    assert protocol[
        "paper_test_pass_criteria"
    ][
        "trade_sequence_must_equal_shadow"
    ] is True


def test_policy_fingerprint_matches_protocol():
    protocol = load_json(
        PROTOCOL_PATH
    )

    fingerprint_record = load_json(
        FINGERPRINT_PATH
    )

    expected_payload = (
        canonical_frozen_payload(
            protocol
        )
    )

    assert fingerprint_record[
        "frozen_payload"
    ] == expected_payload

    assert fingerprint_record[
        "policy_fingerprint"
    ] == calculate_fingerprint(
        expected_payload
    )
