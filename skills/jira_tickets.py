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
from typing import Any, Dict, List

import requests

logger = logging.getLogger(__name__)

_SEARCH_TIMEOUT_SECONDS = 8
_MAX_TOPIC_CHARS = 120
_API_PATH = "/rest/api/3/search"   # Jira Cloud REST API v3


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
    # JQL string literals use double quotes; neutralize any in the input
    # rather than trying to escape them, since a topic is free-form model
    # output, not a trusted query fragment.
    topic = (topic or "").strip()[:_MAX_TOPIC_CHARS].replace('"', "'")
    jql = f'text ~ "{topic}"' if topic else 'text ~ "*"'
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
