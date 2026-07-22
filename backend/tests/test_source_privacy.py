"""Repository guard against committing account identifiers or API secrets."""

from pathlib import Path

from app.safety.source_privacy import scan_source_text, scan_tracked_source

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_sensitive_literals_are_detected_without_retaining_values():
    account_id = "101" + "-004-12345678-001"
    api_key = "sk-" + "liveexamplevalue1234567890"
    token_assignment = "OANDA_API_" + "TOKEN=live-provider-token"
    private_key_header = "-----BEGIN " + "PRIVATE KEY-----"
    text = "\n".join((account_id, api_key, token_assignment, private_key_header))

    findings = scan_source_text("example.env", text)

    assert [finding.rule for finding in findings] == [
        "oanda_account_identifier",
        "openai_api_key",
        "configured_sensitive_environment_value",
        "private_key_block",
    ]
    assert all(not hasattr(finding, "matched_value") for finding in findings)


def test_documented_placeholders_and_reserved_test_accounts_are_allowed():
    text = "\n".join(
        (
            "OANDA_API_TOKEN=replace_with_your_practice_api_token",
            "OPENAI_API_KEY=<secret>",
            "OANDA_ACCOUNT_ID=999-999-00000000-999",
        )
    )

    assert scan_source_text(".env.example", text) == []


def test_current_tracked_source_contains_no_sensitive_literals():
    assert scan_tracked_source(REPOSITORY_ROOT) == []
