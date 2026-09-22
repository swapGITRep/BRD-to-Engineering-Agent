"""
tests/test_jira_tickets.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for skills/jira_tickets.py. requests.get is always stubbed here —
unlike skills/tech_radar.py's local file lookup, this one is a real network
call, so it can never run "for real" in a unit test.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import pytest

import skills.jira_tickets as jt


@pytest.fixture(autouse=True)
def _clear_jira_env(monkeypatch):
    for var in ("JIRA_SITE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT"):
        monkeypatch.delenv(var, raising=False)


def _set_config(monkeypatch, project=""):
    monkeypatch.setenv("JIRA_SITE_URL", "https://swapi4u.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "swapi4u@gmail.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "fake-token")
    if project:
        monkeypatch.setenv("JIRA_PROJECT", project)


class _FakeResponse:
    def __init__(self, payload, status_ok=True):
        self._payload = payload
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise RuntimeError("simulated 401")

    def json(self):
        return self._payload


# ── Config ───────────────────────────────────────────────────────────────────
class TestConfig:

    def test_missing_config_raises(self):
        with pytest.raises(jt.JiraNotConfigured):
            jt.search_related_tickets("anything")

    def test_partial_config_still_raises(self, monkeypatch):
        monkeypatch.setenv("JIRA_SITE_URL", "https://swapi4u.atlassian.net")
        # JIRA_EMAIL / JIRA_API_TOKEN left unset
        with pytest.raises(jt.JiraNotConfigured):
            jt.search_related_tickets("anything")


# ── JQL building ─────────────────────────────────────────────────────────────
class TestBuildJql:

    def test_no_project_is_unscoped(self):
        jql = jt._build_jql("oauth migration", "")
        assert jql == '(text ~ "oauth" OR text ~ "migration") ORDER BY created DESC'

    def test_project_with_spaces_is_quoted(self):
        jql = jt._build_jql("oauth migration", "Agent Development Team")
        assert jql == ('project = "Agent Development Team" AND '
                        '(text ~ "oauth" OR text ~ "migration") ORDER BY created DESC')

    def test_keywords_are_ORed_not_ANDed(self):
        # Live-caught: a topic phrase like "fuzzy matching and exception
        # queue for reconciliation" returned zero results against a real
        # ticket that plainly covered the same work, because AND-of-words
        # requires every word to hit and that ticket never says "exception"
        # or "queue". OR-of-keywords means one strong hit is enough.
        jql = jt._build_jql("fuzzy matching and exception queue for reconciliation", "")
        assert jql == ('(text ~ "fuzzy" OR text ~ "matching" OR text ~ "exception" '
                        'OR text ~ "queue" OR text ~ "reconciliation") ORDER BY created DESC')

    def test_stopwords_and_short_words_are_dropped(self):
        jql = jt._build_jql("a spike on the API for us", "")
        assert jql == '(text ~ "spike" OR text ~ "API") ORDER BY created DESC'

    def test_double_quotes_in_topic_are_neutralized(self):
        # The regex-based word extraction naturally strips punctuation
        # (including a raw ") rather than carrying it into a keyword value,
        # which would otherwise break the JQL string literal.
        jql = jt._build_jql('the "real-time" service', "")
        assert jql == ('(text ~ "real" OR text ~ "time" OR text ~ "service")'
                        ' ORDER BY created DESC')

    def test_empty_topic_matches_everything(self):
        assert jt._build_jql("", "") == 'text ~ "*" ORDER BY created DESC'

    def test_only_stopwords_matches_everything(self):
        assert jt._build_jql("a the of for", "") == 'text ~ "*" ORDER BY created DESC'

    def test_topic_is_truncated(self):
        long_topic = " ".join(["word" + str(i) for i in range(100)])
        jql = jt._build_jql(long_topic, "")
        assert jql.count(" OR ") == jt._MAX_KEYWORDS - 1


# ── search_related_tickets ────────────────────────────────────────────────────
class TestSearchRelatedTickets:

    def test_returns_parsed_tickets(self, monkeypatch):
        _set_config(monkeypatch, project="Agent Development Team")
        captured = {}

        def fake_get(url, params, auth, headers, timeout):
            captured["url"] = url
            captured["params"] = params
            captured["auth"] = auth
            return _FakeResponse({"issues": [
                {"key": "ADT-7", "fields": {"summary": "Prototype matching engine",
                                            "status": {"name": "In Progress"}}},
                {"key": "ADT-9", "fields": {"summary": "Spike on OAuth", "status": {"name": "Done"}}},
            ]})

        monkeypatch.setattr(jt.requests, "get", fake_get)
        out = jt.search_related_tickets("matching engine")

        assert out == [
            {"key": "ADT-7", "summary": "Prototype matching engine", "status": "In Progress"},
            {"key": "ADT-9", "summary": "Spike on OAuth", "status": "Done"},
        ]
        assert captured["url"] == "https://swapi4u.atlassian.net/rest/api/3/search/jql"
        assert captured["auth"] == ("swapi4u@gmail.com", "fake-token")
        assert "Agent Development Team" in captured["params"]["jql"]

    def test_no_issues_returns_empty_list(self, monkeypatch):
        _set_config(monkeypatch)
        monkeypatch.setattr(jt.requests, "get", lambda *a, **k: _FakeResponse({"issues": []}))
        assert jt.search_related_tickets("nothing like this exists") == []

    def test_request_failure_returns_empty_list_not_raise(self, monkeypatch):
        _set_config(monkeypatch)

        def raising_get(*a, **k):
            raise ConnectionError("simulated network failure")

        monkeypatch.setattr(jt.requests, "get", raising_get)
        assert jt.search_related_tickets("anything") == []

    def test_http_error_status_returns_empty_list_not_raise(self, monkeypatch):
        _set_config(monkeypatch)
        monkeypatch.setattr(jt.requests, "get",
                            lambda *a, **k: _FakeResponse({}, status_ok=False))
        assert jt.search_related_tickets("anything") == []

    def test_missing_fields_degrade_gracefully(self, monkeypatch):
        # A malformed/partial issue object (missing "fields" or "status")
        # must not crash the parse.
        _set_config(monkeypatch)
        monkeypatch.setattr(jt.requests, "get",
                            lambda *a, **k: _FakeResponse({"issues": [{"key": "ADT-1"}]}))
        out = jt.search_related_tickets("anything")
        assert out == [{"key": "ADT-1", "summary": "", "status": "?"}]

    def test_max_results_is_passed_through(self, monkeypatch):
        _set_config(monkeypatch)
        seen = {}
        monkeypatch.setattr(jt.requests, "get",
                            lambda url, params, **k: (seen.update(params), _FakeResponse({"issues": []}))[1])
        jt.search_related_tickets("x", max_results=2)
        assert seen["maxResults"] == 2
