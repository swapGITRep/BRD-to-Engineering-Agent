"""
agents/specialist_base.py
─────────────────────────────────────────────────────────────────────────────
Shared plumbing for the five specialist agents (Capability 3).

Each specialist node:
  1. gathers routed requirements + RAG grounding + persona
  2. builds a system + user prompt (its own schema)
  3. calls the LLM, parses JSON, wraps it in an AgentArtifact
  4. saves output/deliverables/<agent>.json and returns a state delta

`finish()` also detects a revision run (state["pending_revision"] == agent_key)
and, in that case, clears pending_revision and routes the pipeline back to the
Critic (current_step "<agent>_revised") instead of the next specialist.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Type

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from orchestration.state import AgentArtifact, ArtifactStatus, BRDState, Stage, resolve_output_dir
from skills.json_utils import invoke_validated_json
from skills.llm_factory import get_llm
from skills.rag_retriever import get_retriever

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Context gathering
# ─────────────────────────────────────────────────────────────────────────────
def llm_config_of(state: BRDState) -> Dict[str, Any]:
    return state.get("framework_config", {}).get("_llm_config", {})


def routed_requirements(state: BRDState, agent_key: str) -> List[Dict[str, Any]]:
    """Requirements in the sections the orchestrator routed to this agent."""
    reqs = state.get("requirements", [])
    target = set(state.get("routing_map", {}).get(agent_key, []))
    if not target:
        return reqs
    picked = [r for r in reqs if r.get("section_id") in target]
    return picked or reqs


def grounding_for(state: BRDState, agent_key: str) -> str:
    """RAG grounding context for this agent (best-effort)."""
    try:
        retriever = get_retriever(llm_config_of(state))
        return retriever.retrieve_for_agent(
            agent_key,
            state.get("brd_summary", "") or _first_line(state),
            routed_requirements(state, agent_key),
        )
    except Exception as e:  # noqa: BLE001 - grounding is best-effort
        logger.warning("Grounding retrieval failed for %s: %s", agent_key, e)
        return "(no knowledge-base context available)"


def _first_line(state: BRDState) -> str:
    md = state.get("brd_metadata", {})
    return md.get("project_name") or "this BRD"


def revision_issues(state: BRDState, agent_key: str) -> List[str]:
    """Critic issues to fix on a revision run, or []."""
    score = state.get("critic_scores", {}).get(agent_key)
    if score and score.get("verdict") == "revise":
        return list(score.get("issues", []))
    return []


def requirements_block(reqs: List[Dict[str, Any]], limit: int = 60) -> str:
    lines = []
    for r in reqs[:limit]:
        tag = r.get("type", "functional")
        if r.get("nfr_category"):
            tag += f"/{r['nfr_category']}"
        flag = " [AMBIGUOUS]" if r.get("ambiguity_flag") else ""
        lines.append(f"- ({r.get('req_id', '?')}, {tag}, {r.get('priority', 'should')}){flag} {r.get('text', '')}")
    return "\n".join(lines) or "(no structured requirements)"


def revision_block(issues: List[str]) -> str:
    if not issues:
        return ""
    body = "\n".join(f"- {i}" for i in issues)
    return f"YOU ARE REVISING A PRIOR VERSION. FIX THESE ISSUES:\n{body}\n\n"


# ─────────────────────────────────────────────────────────────────────────────
# LLM call
# ─────────────────────────────────────────────────────────────────────────────
def invoke_json(
    llm_agent_name: str,
    state: BRDState,
    system_prompt: str,
    user_prompt: str,
    *,
    schema: Optional[Type[BaseModel]] = None,
    extra_check: Optional[Callable[[Dict[str, Any]], List[str]]] = None,
) -> Dict[str, Any]:
    """Call the LLM, parse its JSON reply, and (optionally) validate it.

    For a large structured output (the engineering plan routinely runs
    10k+ characters), an occasional stray comma or unescaped quote from the
    model is expected, not a real failure — so a malformed reply is retried
    once, feeding the exact problem back to the model, before giving up and
    letting the caller's except-block mark the agent failed.

    `schema`, when given, is a pydantic model (see skills/schemas.py) the
    parsed JSON must satisfy — a missing required field or wrong type is a
    validation failure retried the same way a JSON syntax error already is,
    not a silent pass-through to finish(). `extra_check`, when given, runs
    against the (schema-validated) dict and returns a list of problem
    strings — used for checks a schema can't express, like a cross-agent
    contract (e.g. the PoC Planner's modules must map to real architecture
    components). Both share the single retry budget in
    skills/json_utils.py::invoke_validated_json."""
    llm = get_llm(llm_agent_name, llm_config_of(state))
    return invoke_validated_json(
        llm,
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        schema=schema,
        extra_check=extra_check,
        label=llm_agent_name,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Result wrapping
# ─────────────────────────────────────────────────────────────────────────────
def finish(
    agent_key: str,
    parsed: Dict[str, Any],
    state: BRDState,
    next_stage: str,
    *,
    self_review: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Wrap parsed LLM output in an AgentArtifact, persist it, return a state delta."""
    citations = parsed.pop("citations", []) or []
    revision = int(state.get("revision_counts", {}).get(agent_key, 0))
    was_revision = state.get("pending_revision") == agent_key

    artifact = AgentArtifact(
        agent=agent_key,
        content=parsed,
        citations=list(citations),
        revision=revision,
        self_review=self_review,
        status=ArtifactStatus.OK,
    )
    _save(agent_key, artifact, state)
    logger.info("✅ %s complete (revision %d, %d citations)", agent_key, revision, len(citations))

    delta: Dict[str, Any] = {
        agent_key:       artifact,
        "current_stage": Stage.CRITIQUE if was_revision else next_stage,
        "current_step":  f"{agent_key}_{'revised' if was_revision else 'complete'}",
        "errors":        state.get("errors", []),
    }
    if was_revision:
        delta["pending_revision"] = None
    return delta


def fail(agent_key: str, state: BRDState, error_msg: str, next_stage: str) -> Dict[str, Any]:
    """Record a hard failure but keep the pipeline moving (non-blocking policy)."""
    logger.error("❌ %s failed: %s", agent_key, error_msg)
    artifact = AgentArtifact(
        agent=agent_key, content={}, citations=[], revision=0,
        self_review=None, status=ArtifactStatus.FAILED,
    )
    was_revision = state.get("pending_revision") == agent_key
    delta: Dict[str, Any] = {
        agent_key:       artifact,
        "current_stage": Stage.CRITIQUE if was_revision else next_stage,
        "current_step":  f"{agent_key}_failed",
        "errors":        state.get("errors", []) + [f"{agent_key}: {error_msg}"],
    }
    if was_revision:
        delta["pending_revision"] = None
    return delta


def _save(agent_key: str, artifact: AgentArtifact, state: BRDState) -> None:
    out_dir = resolve_output_dir(
        state.get("framework_config", {}).get("output", {}).get("deliverables_dir", "output/deliverables")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {**artifact, "brd_id": state.get("brd_id", ""),
               "saved_at": datetime.now(timezone.utc).isoformat()}
    (out_dir / f"{agent_key}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
