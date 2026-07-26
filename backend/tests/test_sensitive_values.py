"""Tests for credential filtering at tool-evidence trust boundaries."""

import pytest

from automail.core.sensitive_values import (
    contains_sensitive_credential,
    sanitize_tool_response_facts,
)


@pytest.mark.parametrize(
    "value",
    [
        "Bearer qa-test-credential-123456",
        "Basic dXNlcjpwYXNzd29yZA==",
        "api_key: ghp_1234567890abcdef",
        "credential: qa-client-password",
        "access token ghp_1234567890abcdef",
        "secret changed to hunter2",
        "sk_live_51QATESTCREDENTIAL123456",
        "AIzaSyA1234567890abcdefghijklmnop",
        "glpat-1234567890abcdef",
        "AKIAABCDEFGHIJKLMNOP",
        "xoxb-12345678-abcdefghijklmnop",
        "SG.1234567890abcdef.abcdefghijklmnop",
        "whsec_1234567890abcdef",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature123",
        "postgresql://qa-user:qa-password@example.test/db",
        "-----BEGIN PRIVATE KEY-----",
        "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCtest",
    ],
)
def test_contains_sensitive_credential_rejects_labels_and_common_formats(
    value: str,
) -> None:
    assert contains_sensitive_credential(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "customer certificate rotation",
        "Awaiting counterparty response",
        "2026-07-19T07:40:00Z",
        "DHL00340434161234567890",
        "INV-9012",
    ],
)
def test_contains_sensitive_credential_keeps_business_facts(value: str) -> None:
    assert contains_sensitive_credential(value) is False


def test_sanitize_tool_response_facts_filters_current_and_historical_shapes() -> None:
    facts = [
        {"path": "status", "value": "active"},
        {"path": "reference", "value": "ghp_1234567890abcdef"},
        {
            "path": "fixture_evidence.result.1",
            "value": "recent_change: client_secret=qa-secret-value",
        },
        {"path": "api_token", "value": "masked"},
    ]

    assert sanitize_tool_response_facts(facts) == [
        {"path": "status", "value": "active"}
    ]
    assert sanitize_tool_response_facts(
        {
            "recent_change": "customer certificate rotation",
            "api_key": "ghp_1234567890abcdef",
        }
    ) == {"recent_change": "customer certificate rotation"}
