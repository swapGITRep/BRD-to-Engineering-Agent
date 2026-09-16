"""
skills/confidentiality.py
─────────────────────────────────────────────────────────────────────────────
Confidentiality guardrail: scans BRD text for likely credentials and PII and
redacts them in place, before the text ever reaches an LLM call.

Wired into agents/brd_ingest_agent.py, the single point every entry path
(UI upload, paste, sample, CLI, the eval harness) funnels through before any
downstream agent runs — redacting once there protects every path uniformly,
rather than duplicating the check per entry point. Every specialist's
grounding, generation, and everything persisted to disk downstream all read
the already-redacted state["brd_text"].

Deterministic, regex-based — no LLM call. That matters twice over: it can't
itself leak the very data it's meant to protect (nothing sensitive is ever
sent anywhere to check it), and it can't be argued out of catching something
by how a prompt is worded.

`scan_and_redact()` returns (redacted_text, findings) — findings are
human-readable counts ("2 email address(es) redacted"), safe to log or
display; they never include the matched value itself.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class _Pattern:
    label: str
    regex: "re.Pattern[str]"
    placeholder: str


# ── Credentials & secrets — high-confidence, low-false-positive patterns ────
_CREDENTIAL_PATTERNS: List[_Pattern] = [
    _Pattern("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
             "[REDACTED:AWS_ACCESS_KEY]"),
    _Pattern("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
             "[REDACTED:GITHUB_TOKEN]"),
    _Pattern("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
             "[REDACTED:SLACK_TOKEN]"),
    _Pattern("OpenAI-style API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
             "[REDACTED:API_KEY]"),
    _Pattern("private key block", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----[\s\S]+?"
        r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
    ), "[REDACTED:PRIVATE_KEY]"),
    _Pattern("credential URL", re.compile(
        r"\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:/@'\"]+:[^\s:/@'\"]+@[^\s/'\"]+"
    ), "[REDACTED:CREDENTIAL_URL]"),
    _Pattern("bearer token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.]{20,}"),
             "Bearer [REDACTED:TOKEN]"),
]

# A labeled assignment ("api_key: ...", "password=...") — requires an actual
# ':'/'=' assignment immediately after the label, so ordinary prose ("Passwords
# must be hashed with bcrypt") never matches. The label itself is kept; only
# the value is redacted, so the requirement stays readable. The value
# excludes '[' / ']' so this never re-matches a placeholder a credential
# pattern above already redacted (e.g. "api_key: [REDACTED:API_KEY]") —
# without that, a value that was both a labeled assignment AND a recognized
# credential shape got redacted twice and double-counted in the findings.
_LABELED_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|password|passwd|access[_-]?token)\b(\s*[:=]\s*)['\"]?([^\s'\"\[\]]{12,})['\"]?"
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD_RE = re.compile(r"\b(?:\d{4}[ -]?){3}\d{1,4}\b")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def scan_and_redact(text: str) -> Tuple[str, List[str]]:
    """Redact likely credentials and PII from `text`. Returns
    (redacted_text, findings) — findings never contain the matched value."""
    if not text:
        return text, []

    findings: List[str] = []
    out = text

    for pat in _CREDENTIAL_PATTERNS:
        out, n = pat.regex.subn(pat.placeholder, out)
        if n:
            findings.append(f"{n} {pat.label}{'s' if n != 1 else ''} redacted")

    out, n = _LABELED_SECRET_RE.subn(r"\1\2[REDACTED:SECRET]", out)
    if n:
        findings.append(f"{n} labeled secret value{'s' if n != 1 else ''} redacted")

    out, n = _EMAIL_RE.subn("[REDACTED:EMAIL]", out)
    if n:
        findings.append(f"{n} email address{'es' if n != 1 else ''} redacted")

    out, n = _SSN_RE.subn("[REDACTED:SSN]", out)
    if n:
        findings.append(f"{n} SSN{'s' if n != 1 else ''} redacted")

    card_count = 0

    def _card_sub(m: "re.Match[str]") -> str:
        nonlocal card_count
        digits = re.sub(r"[ -]", "", m.group(0))
        if len(digits) in (13, 14, 15, 16) and _luhn_ok(digits):
            card_count += 1
            return "[REDACTED:CARD_NUMBER]"
        return m.group(0)

    out = _CARD_RE.sub(_card_sub, out)
    if card_count:
        findings.append(f"{card_count} card number{'s' if card_count != 1 else ''} redacted")

    return out, findings
