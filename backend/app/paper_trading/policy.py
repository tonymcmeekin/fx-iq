import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

POLICY_NAME = "validated_close_location_soft_risk"
POLICY_VERSION = "1.0"

BASE_RISK_PERCENT = 0.5
REDUCED_RISK_PERCENT = 0.25
DIRECTIONAL_CLOSE_LOCATION_THRESHOLD = 0.8174

EXPECTED_POLICY_FINGERPRINT = (
    "e7d20e329a40763febff468508a65df15"
    "d519033a37c2db99687384596258720"
)

EXPECTED_VALIDATION_RESULTS_HASH = (
    "50964f9e746310442db6447984e8d187"
    "41231620b39c3add3e3720d412aa53b9"
)

DEFAULT_PROTOCOL_PATH = Path(
    "research_protocols/"
    "prospective_paper_trading_protocol.json"
)

DEFAULT_FINGERPRINT_PATH = Path(
    "research_protocols/"
    "prospective_paper_policy_fingerprint.json"
)

DEFAULT_VALIDATION_RESULTS_PATH = Path(
    "research_results/"
    "untouched_cross_market_validation_results.json"
)


@dataclass(frozen=True)
class CloseLocationRiskDecision:
    policy_name: str
    policy_version: str
    base_risk_percent: float
    adjusted_risk_percent: float
    directional_close_location: float
    threshold: float
    risk_reduced: bool
    reason: str


def sha256_file(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(
        path.read_text()
    )


def frozen_policy_payload(
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


def calculate_policy_fingerprint(
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


def verify_frozen_policy(
    protocol_path: Path = DEFAULT_PROTOCOL_PATH,
    fingerprint_path: Path = DEFAULT_FINGERPRINT_PATH,
    validation_results_path: Path = (
        DEFAULT_VALIDATION_RESULTS_PATH
    ),
) -> str:
    protocol = load_json(
        protocol_path
    )

    fingerprint_record = load_json(
        fingerprint_path
    )

    if protocol["status"] != (
        "PREREGISTERED_NOT_STARTED"
    ):
        raise RuntimeError(
            "Prospective protocol status is not "
            "PREREGISTERED_NOT_STARTED."
        )

    if protocol["mode"] != "SIMULATION_ONLY":
        raise RuntimeError(
            "Prospective protocol is not simulation-only."
        )

    if protocol[
        "live_order_submission_permitted"
    ]:
        raise RuntimeError(
            "Prospective protocol permits live orders."
        )

    policy = protocol[
        "frozen_risk_policy"
    ]

    expected_policy = {
        "policy_name": POLICY_NAME,
        "policy_version": POLICY_VERSION,
        "base_risk_percent": BASE_RISK_PERCENT,
        "reduced_risk_percent": (
            REDUCED_RISK_PERCENT
        ),
        "directional_close_location_threshold": (
            DIRECTIONAL_CLOSE_LOCATION_THRESHOLD
        ),
    }

    for field, expected_value in (
        expected_policy.items()
    ):
        if policy[field] != expected_value:
            raise RuntimeError(
                f"Frozen policy mismatch for {field}: "
                f"expected {expected_value}, "
                f"found {policy[field]}."
            )

    validation_hash = sha256_file(
        validation_results_path
    )

    if validation_hash != (
        EXPECTED_VALIDATION_RESULTS_HASH
    ):
        raise RuntimeError(
            "Preserved validation result hash mismatch."
        )

    if protocol[
        "validated_policy_source"
    ]["validation_results_sha256"] != (
        EXPECTED_VALIDATION_RESULTS_HASH
    ):
        raise RuntimeError(
            "Protocol validation hash does not match "
            "the preserved result."
        )

    payload = frozen_policy_payload(
        protocol
    )

    actual_fingerprint = (
        calculate_policy_fingerprint(
            payload
        )
    )

    recorded_fingerprint = (
        fingerprint_record[
            "policy_fingerprint"
        ]
    )

    if actual_fingerprint != (
        recorded_fingerprint
    ):
        raise RuntimeError(
            "Policy fingerprint record does not match "
            "the prospective protocol."
        )

    if actual_fingerprint != (
        EXPECTED_POLICY_FINGERPRINT
    ):
        raise RuntimeError(
            "Frozen policy fingerprint mismatch."
        )

    return actual_fingerprint


def calculate_validated_close_location_risk(
    directional_close_location: float,
    base_risk_percent: float = BASE_RISK_PERCENT,
) -> CloseLocationRiskDecision:
    close_location = float(
        directional_close_location
    )

    configured_base_risk = float(
        base_risk_percent
    )

    if not 0 <= close_location <= 1:
        raise ValueError(
            "Directional close location must be "
            "between zero and one."
        )

    if configured_base_risk != (
        BASE_RISK_PERCENT
    ):
        raise ValueError(
            "The validated policy requires a frozen "
            "base risk of 0.5 percent."
        )

    risk_reduced = (
        close_location
        <= DIRECTIONAL_CLOSE_LOCATION_THRESHOLD
    )

    if risk_reduced:
        adjusted_risk = (
            REDUCED_RISK_PERCENT
        )

        reason = (
            "Risk reduced because directional close "
            "location is at or below the frozen "
            "validated threshold."
        )
    else:
        adjusted_risk = (
            BASE_RISK_PERCENT
        )

        reason = (
            "Base risk retained because directional "
            "close location is above the frozen "
            "validated threshold."
        )

    return CloseLocationRiskDecision(
        policy_name=POLICY_NAME,
        policy_version=POLICY_VERSION,
        base_risk_percent=(
            BASE_RISK_PERCENT
        ),
        adjusted_risk_percent=(
            adjusted_risk
        ),
        directional_close_location=(
            close_location
        ),
        threshold=(
            DIRECTIONAL_CLOSE_LOCATION_THRESHOLD
        ),
        risk_reduced=risk_reduced,
        reason=reason,
    )
