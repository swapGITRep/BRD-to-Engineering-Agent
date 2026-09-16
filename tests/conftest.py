"""
tests/conftest.py
─────────────────────────────────────────────────────────────────────────────
Shared fixtures. `fake_llm` returns a callable that builds a FakeLLM preloaded
with queued responses (str or dict); each `.invoke(...)` pops the next one.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import os

# Force LangSmith tracing OFF for the whole test session, before any test
# module (e.g. test_workflow_smoke.py) imports orchestration.langgraph_workflow
# and its module-level load_dotenv() picks up real .env credentials. Without
# this, a real .env with LANGCHAIN_TRACING_V2=true makes every LangGraph
# app.invoke() call in the smoke tests — even with fully-faked LLMs — emit a
# genuine trace to LangSmith (that's how "BRD-SMOKE"/"BRD-EMPTY" show up there
# without ever running a real analysis: pytest, not the app, produced them).
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

import json
from types import SimpleNamespace
from typing import Any

import pytest


class FakeLLM:
    """Minimal stand-in for langchain_openai.ChatOpenAI."""

    def __init__(self, responses: list[Any]):
        self._responses = list(responses)
        self.calls: list[Any] = []

    def invoke(self, messages: Any) -> SimpleNamespace:
        self.calls.append(messages)
        if not self._responses:
            raise AssertionError("FakeLLM: no more queued responses")
        nxt = self._responses.pop(0)
        content = nxt if isinstance(nxt, str) else json.dumps(nxt)
        return SimpleNamespace(content=content)

    @property
    def call_count(self) -> int:
        return len(self.calls)


@pytest.fixture
def fake_llm():
    def _make(*responses: Any) -> FakeLLM:
        return FakeLLM(list(responses))
    return _make


@pytest.fixture
def brd_framework_config():
    """A merged framework_config like load_configs() will produce."""
    return {
        "rubric_weights": {
            "completeness": 0.30, "consistency": 0.25,
            "actionability": 0.25, "groundedness": 0.20,
        },
        "badges": {"green": 0.80, "amber": 0.60},
        "required_sections": {
            "engineering_plan": ["phases", "risks", "milestones", "team_composition"],
        },
        "ingestion": {"min_sections": 1},
        "output": {
            "parsed_dir": "output/parsed",
            "deliverables_dir": "output/deliverables",
            "report_dir": "output/reports",
        },
        "_llm_config": {
            "openai": {"model": "gpt-4.1"},
            "agents": {"brd_ingest": {"model": "gpt-4.1-mini"}},
            "revision": {"max_revisions_per_agent": 2},
        },
    }
