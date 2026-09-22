"""
skills/jira_tickets.py
─────────────────────────────────────────────────────────────────────────────
Searches a real Jira Cloud project for tickets related to a topic. Backs the
PoC Planner's check_related_jira_tickets tool (see agents/poc_planner_agent.py)
— a real JQL search against the org's actual Jira, not a mock, the same
"real lookup, not a mock" posture skills/tech_radar.py already has.

Config (env vars; JIRA_API_TOKEN is a secret, the rest aren't):
  JIRA_SITE_URL   e.g. https://yourcompany.atlassian.net
  JIRA_EMAIL      the Atlassian account email the API token belongs to
  JIRA_API_TOKEN  the API token itself — never logged, never returned to the model
  JIRA_PROJECT    project name or key to scope the search to, e.g. "Agent
                   Development Team" or "ADT" — optional; unscoped if blank

Missing config is not an error callers need to handle specially beyond
catching JiraNotConfigured — the tool wrapper turns that into a plain string
the model can act on, the same best-effort posture grounding_for() already
has for RAG retrieval. A network/API failure is different: it's logged and
reported as "no related tickets found" rather than surfaced as an error,
since a transient Jira outage shouldn't look like "definitely nothing
related exists" to a human reading the tool's own log line, but also
shouldn't block the PoC Planner from finishing.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List

import requests

logger = logging.getLogger(__name__)

_SEARCH_TIMEOUT_SECONDS = 8
_MAX_TOPIC_CHARS = 120
_MAX_KEYWORDS = 6
# /rest/api/3/search was deprecated by Atlassian in May 2025 and is now fully
# retired -- live-caught: it returns HTTP 410 Gone, not a deprecation
# warning. /rest/api/3/search/jql is its replacement; same query params and
# response shape (issues[], each with key/fields), just token- instead of
# offset-paginated -- irrelevant here since max_results already caps the
# single page this tool ever needs.
_API_PATH = "/rest/api/3/search/jql"

# Common words dropped before building the query -- keeping them would either
# do nothing (Jira's own tokenizer already ignores most of these) or, worse,
# force a coincidental match on a word like "for" that says nothing about
# relevance.
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "into", "is", "it", "of", "on", "or", "that", "the", "this", "to",
    "using", "via", "was", "were", "with",
}


class JiraNotConfigured(Exception):
    """JIRA_SITE_URL / JIRA_EMAIL / JIRA_API_TOKEN aren't all set."""


def _config() -> Dict[str, str]:
    site  = os.environ.get("JIRA_SITE_URL", "").rstrip("/")
    email = os.environ.get("JIRA_EMAIL", "")
    token = os.environ.get("JIRA_API_TOKEN", "")
    if not (site and email and token):
        raise JiraNotConfigured("JIRA_SITE_URL / JIRA_EMAIL / JIRA_API_TOKEN not all set")
    return {"site": site, "email": email, "token": token,
            "project": os.environ.get("JIRA_PROJECT", "")}


def _build_jql(topic: str, project: str) -> str:
    # `text ~ "several words"` is AND-of-words, not a loose "contains any of
    # these" match (confirmed against real Jira, live: a topic phrase like
    # "fuzzy matching and exception queue for reconciliation" returned zero
    # results against a ticket that plainly covers the same work, purely
    # because that one ticket's text never says "exception" or "queue" --
    # every word in the phrase has to hit, so one off-topic word the model
    # added sinks the whole query). A model's topic phrasing rarely lines up
    # word-for-word with an existing ticket, so match on ANY significant
    # keyword (OR) instead of ALL of them (AND) -- recall matters more than
    # precision here, since a human or the model itself reads the results.
    words = re.findall(r"[A-Za-z0-9]+", (topic or "")[:_MAX_TOPIC_CHARS])
    keywords = [w for w in words if len(w) > 2 and w.lower() not in _STOPWORDS][:_MAX_KEYWORDS]
    if keywords:
        jql = "(" + " OR ".join(f'text ~ "{kw}"' for kw in keywords) + ")"
    else:
        jql = 'text ~ "*"'
    if project:
        jql = f'project = "{project.replace(chr(34), chr(39))}" AND {jql}'
    return jql + " ORDER BY created DESC"


def search_related_tickets(topic: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Real JQL search against Jira Cloud. Raises JiraNotConfigured if the
    required env vars aren't set; returns [] (logged, not raised) for any
    network/API/parse failure, so a transient Jira problem degrades to
    "nothing found" for the caller rather than failing the PoC Planner."""
    cfg = _config()   # raises JiraNotConfigured — let the caller handle that distinctly
    jql = _build_jql(topic, cfg["project"])
    try:
        resp = requests.get(
            f"{cfg['site']}{_API_PATH}",
            params={"jql": jql, "maxResults": max_results, "fields": "summary,status"},
            auth=(cfg["email"], cfg["token"]),
            headers={"Accept": "application/json"},
            timeout=_SEARCH_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        issues = resp.json().get("issues", [])
    except Exception as e:  # noqa: BLE001 - a Jira/network problem must not fail the caller
        logger.warning("Jira search failed (%s); treating as no related tickets found.", e)
        return []

    return [_to_summary(issue) for issue in issues]


def _to_summary(issue: Dict[str, Any]) -> Dict[str, str]:
    fields = issue.get("fields") or {}
    status = fields.get("status") or {}
    return {
        "key":     issue.get("key", "?"),
        "summary": fields.get("summary", ""),
        "status":  status.get("name", "?"),
    }
