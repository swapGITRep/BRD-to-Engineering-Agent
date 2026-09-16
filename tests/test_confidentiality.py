"""
tests/test_confidentiality.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for skills/confidentiality.scan_and_redact — the deterministic
guardrail wired into brd_ingest_node (see test_brd_ingest_agent.py for the
integration test proving a secret never reaches an LLM call).
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import pytest

from skills.confidentiality import scan_and_redact


class TestCredentials:

    def test_aws_access_key(self):
        text, findings = scan_and_redact("AWS key AKIAIOSFODNN7EXAMPLE leaked in a log.")
        assert "AKIAIOSFODNN7EXAMPLE" not in text
        assert "[REDACTED:AWS_ACCESS_KEY]" in text
        assert findings == ["1 AWS access key redacted"]

    def test_openai_style_key_with_hyphens(self):
        # Modern project-scoped keys ("sk-proj-...") contain hyphens in the
        # body — a naive [A-Za-z0-9]-only pattern misses these.
        text, findings = scan_and_redact(
            "leaked key sk-proj-abc123def456ghi789jklmnopqrstuvwxyz in a log line"
        )
        assert "sk-proj-" not in text
        assert findings == ["1 OpenAI-style API key redacted"]

    def test_github_token(self):
        text, findings = scan_and_redact("token: ghp_" + "a" * 36)
        assert "[REDACTED:GITHUB_TOKEN]" in text or "[REDACTED:SECRET]" in text
        assert findings

    def test_private_key_block(self):
        text, findings = scan_and_redact(
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA\n-----END RSA PRIVATE KEY-----"
        )
        assert text == "[REDACTED:PRIVATE_KEY]"
        assert findings == ["1 private key block redacted"]

    def test_credential_url(self):
        text, findings = scan_and_redact("postgres://admin:hunter2@db.internal:5432/prod")
        assert "hunter2" not in text
        assert "admin" not in text
        assert "[REDACTED:CREDENTIAL_URL]" in text
        assert findings == ["1 credential URL redacted"]

    def test_bearer_token(self):
        text, findings = scan_and_redact("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")
        assert "eyJ" not in text
        assert findings == ["1 bearer token redacted"]

    @pytest.mark.parametrize("label", ["api_key", "API-KEY", "secret", "password", "passwd", "access_token"])
    def test_labeled_secret_assignment(self, label):
        text, findings = scan_and_redact(f"{label}: Sup3r$ecretValue2024")
        assert "Sup3r$ecretValue2024" not in text
        assert "[REDACTED:SECRET]" in text
        assert findings == ["1 labeled secret value redacted"]
        assert label in text  # the label itself is kept — only the value is redacted

    def test_prose_mentioning_password_is_not_redacted(self):
        text, findings = scan_and_redact(
            "Passwords must be hashed using bcrypt with a per-user salt."
        )
        assert findings == []
        assert text == "Passwords must be hashed using bcrypt with a per-user salt."

    def test_prose_mentioning_api_key_is_not_redacted(self):
        text, findings = scan_and_redact("The API key must be rotated every 90 days per policy.")
        assert findings == []

    def test_labeled_value_that_is_also_a_recognized_credential_shape_is_not_double_counted(self):
        # "api_key: sk-proj-..." matches BOTH the OpenAI-key credential pattern
        # AND the labeled-assignment pattern. It must be redacted exactly
        # once, not re-redacted (and double-counted) by the second pass
        # matching the first pass's own placeholder.
        text, findings = scan_and_redact(
            "api_key: sk-proj-abc123def456ghi789jklmnopqrstuvwxyz"
        )
        assert "sk-proj-" not in text
        assert text.count("REDACTED") == 1
        assert findings == ["1 OpenAI-style API key redacted"]


class TestPII:

    def test_email(self):
        text, findings = scan_and_redact("Sponsor: jane.doe@company.com. Target go-live: Q3.")
        assert "jane.doe@company.com" not in text
        assert "[REDACTED:EMAIL]" in text
        assert findings == ["1 email address redacted"]

    def test_ssn(self):
        text, findings = scan_and_redact("SSN on file: 123-45-6789 for verification.")
        assert "123-45-6789" not in text
        assert findings == ["1 SSN redacted"]

    def test_card_number_valid_luhn(self):
        text, findings = scan_and_redact("Test card 4242-4242-4242-4242 was used in staging.")
        assert "4242-4242-4242-4242" not in text
        assert "[REDACTED:CARD_NUMBER]" in text
        assert findings == ["1 card number redacted"]

    def test_card_shaped_but_luhn_invalid_is_not_redacted(self):
        text, findings = scan_and_redact("Order id 1234-5678-9012-3456 is not a card.")
        assert findings == []
        assert "1234-5678-9012-3456" in text


class TestOrdinaryContentUnaffected:

    def test_requirement_sentence(self):
        text, findings = scan_and_redact(
            "3.1 The system must ingest settlement files from Stripe and PayPal."
        )
        assert findings == []
        assert "Stripe" in text and "PayPal" in text

    def test_nfr_with_numbers_and_dashes(self):
        text, findings = scan_and_redact(
            "4.1 Uptime must be 99.5% during business hours (07:00-19:00 UK)."
        )
        assert findings == []

    def test_empty_and_none_input(self):
        assert scan_and_redact("") == ("", [])
        assert scan_and_redact(None) == (None, [])


class TestMultipleFindings:

    def test_several_kinds_in_one_document(self):
        text, findings = scan_and_redact(
            "Sponsor: jane@co.com\n"
            "Backup contact: john@co.com\n"
            "AWS key AKIAIOSFODNN7EXAMPLE must be rotated.\n"
        )
        assert "jane@co.com" not in text and "john@co.com" not in text
        assert "AKIAIOSFODNN7EXAMPLE" not in text
        assert any("2 email addresses" in f for f in findings)
        assert any("AWS access key" in f for f in findings)

    def test_findings_never_contain_the_matched_value(self):
        _, findings = scan_and_redact("password: TopSecret123456 and email a@b.com")
        joined = " ".join(findings)
        assert "TopSecret123456" not in joined
        assert "a@b.com" not in joined
