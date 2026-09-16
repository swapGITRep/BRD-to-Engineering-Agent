"""
skills/llm_factory.py
─────────────────────────────────────────────────────────────────────────────
Single place that constructs LLM + embedding clients for every agent.

All agents call `get_llm("<agent_name>", llm_config)` instead of instantiating
ChatOpenAI themselves. Provider is OpenAI (model `gpt-4.1` by default). A
per-agent `model:` override in llm_config.yaml (e.g. brd_ingest -> gpt-4.1-mini)
is the most specific setting and always wins — it's there precisely to run one
agent on a cheaper/different model, so a blanket `OPENAI_MODEL` env var must
not silently defeat it. `OPENAI_MODEL` instead overrides the *default* used by
agents that don't set their own `model:`, ahead of the global `openai:` block.

Parameter resolution is split into a pure function (`resolve_llm_params`) so it
can be unit-tested without importing the OpenAI SDK or hitting the network.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import os
from typing import Any, Dict

DEFAULT_MODEL       = "gpt-4.1"
DEFAULT_EMBED_MODEL = "text-embedding-3-large"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS  = 8192
DEFAULT_TIMEOUT     = 120
DEFAULT_MAX_RETRIES = 3


def resolve_llm_params(agent_name: str, llm_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve the effective LLM parameters for an agent.

    Precedence (highest first):
        1. per-agent block      llm_config["agents"][agent]["model"] — most specific;
                                 e.g. brd_ingest -> gpt-4.1-mini. Always wins when set.
        2. environment variable (OPENAI_MODEL)               — model only; overrides
                                 the default for agents with no per-agent model
        3. global block         llm_config["openai"]
        4. hard-coded defaults

    temperature/max_tokens still follow agent > global > default — there's no
    env var for those.

    Returns a plain dict — no SDK import, no network.
    """
    oa    = (llm_config or {}).get("openai", {}) or {}
    agent = (llm_config or {}).get("agents", {}).get(agent_name, {}) or {}

    model = (
        agent.get("model")
        or os.environ.get("OPENAI_MODEL")
        or oa.get("model")
        or DEFAULT_MODEL
    )

    return {
        "model":       model,
        "temperature": agent.get("temperature", oa.get("temperature", DEFAULT_TEMPERATURE)),
        "max_tokens":  agent.get("max_tokens",  oa.get("max_tokens",  DEFAULT_MAX_TOKENS)),
        "timeout":     oa.get("timeout_seconds", DEFAULT_TIMEOUT),
        "max_retries": oa.get("max_retries",     DEFAULT_MAX_RETRIES),
    }


def resolve_embed_model(llm_config: Dict[str, Any]) -> str:
    """Resolve the embedding model name (env > global block > default)."""
    oa = (llm_config or {}).get("openai", {}) or {}
    return (
        os.environ.get("OPENAI_EMBED_MODEL")
        or oa.get("embed_model")
        or DEFAULT_EMBED_MODEL
    )


def _api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to .env (local) or the Container "
            "App secret (Azure)."
        )
    return key


def get_llm(agent_name: str, llm_config: Dict[str, Any]):
    """
    Return a configured `langchain_openai.ChatOpenAI` for the given agent.

    Imported lazily so tests that only exercise `resolve_llm_params` do not need
    the `langchain-openai` package installed.
    """
    from langchain_openai import ChatOpenAI

    params = resolve_llm_params(agent_name, llm_config)
    base_url = os.environ.get("OPENAI_BASE_URL")  # optional gateway/proxy
    kwargs: Dict[str, Any] = {**params, "api_key": _api_key()}
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


def get_embeddings(llm_config: Dict[str, Any]):
    """Return a configured `langchain_openai.OpenAIEmbeddings` client."""
    from langchain_openai import OpenAIEmbeddings

    kwargs: Dict[str, Any] = {
        "model": resolve_embed_model(llm_config),
        "api_key": _api_key(),
    }
    base_url = os.environ.get("OPENAI_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAIEmbeddings(**kwargs)
