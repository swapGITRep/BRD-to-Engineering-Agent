"""
tests/test_llm_factory.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for LLM parameter resolution. Exercises the pure functions only —
no OpenAI SDK import, no network.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import pytest

from skills.llm_factory import (
    DEFAULT_EMBED_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    resolve_embed_model,
    resolve_llm_params,
)


LLM_CONFIG = {
    "openai": {
        "model": "gpt-4.1",
        "embed_model": "text-embedding-3-large",
        "temperature": 0.2,
        "max_tokens": 8192,
        "timeout_seconds": 90,
        "max_retries": 5,
    },
    "agents": {
        "brd_ingest": {"temperature": 0.0, "model": "gpt-4.1-mini"},
        "engineering_plan_generator": {"temperature": 0.3},
    },
}


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for var in ("OPENAI_MODEL", "OPENAI_EMBED_MODEL"):
        monkeypatch.delenv(var, raising=False)


class TestResolveLlmParams:

    def test_unknown_agent_uses_global_block(self):
        p = resolve_llm_params("nobody", LLM_CONFIG)
        assert p["model"] == "gpt-4.1"
        assert p["temperature"] == 0.2
        assert p["max_tokens"] == 8192
        assert p["timeout"] == 90
        assert p["max_retries"] == 5

    def test_per_agent_temperature_override(self):
        p = resolve_llm_params("engineering_plan_generator", LLM_CONFIG)
        assert p["temperature"] == 0.3
        assert p["model"] == "gpt-4.1"        # falls back to global

    def test_per_agent_model_override(self):
        p = resolve_llm_params("brd_ingest", LLM_CONFIG)
        assert p["model"] == "gpt-4.1-mini"
        assert p["temperature"] == 0.0

    def test_per_agent_model_wins_over_env_var(self, monkeypatch):
        # Regression: OPENAI_MODEL is commonly set in .env as a general
        # default. It must NOT silently defeat an explicit per-agent
        # override (that's the whole point of e.g. brd_ingest -> gpt-4.1-mini).
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-2025")
        p = resolve_llm_params("brd_ingest", LLM_CONFIG)
        assert p["model"] == "gpt-4.1-mini"

    def test_env_var_overrides_default_for_agents_without_a_model_override(self, monkeypatch):
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-2025")
        p = resolve_llm_params("engineering_plan_generator", LLM_CONFIG)
        assert p["model"] == "gpt-4.1-2025"

    def test_env_var_used_when_config_has_no_global_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-2025")
        p = resolve_llm_params("nobody", {})
        assert p["model"] == "gpt-4.1-2025"

    def test_empty_config_falls_back_to_defaults(self):
        p = resolve_llm_params("engineering_plan_generator", {})
        assert p["model"] == DEFAULT_MODEL
        assert p["temperature"] == DEFAULT_TEMPERATURE
        assert p["max_tokens"] == DEFAULT_MAX_TOKENS

    def test_none_config_does_not_raise(self):
        p = resolve_llm_params("x", None)
        assert p["model"] == DEFAULT_MODEL


class TestResolveEmbedModel:

    def test_from_config(self):
        assert resolve_embed_model(LLM_CONFIG) == "text-embedding-3-large"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
        assert resolve_embed_model(LLM_CONFIG) == "text-embedding-3-small"

    def test_default(self):
        assert resolve_embed_model({}) == DEFAULT_EMBED_MODEL
