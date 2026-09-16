"""
agents/orchestrator_agent.py
─────────────────────────────────────────────────────────────────────────────
LangGraph node: Orchestrator (Orchestration).

  - Builds the specialist run order (agent_plan) and a routing_map that points
    each agent at the BRD sections most relevant to it.
  - Produces a short brd_summary used for RAG queries and the final report.
  - On revision re-entry (state["pending_revision"] set) it is a pure
    pass-through: no re-planning, no LLM call.

Reads:  state["brd_sections"], state["requirements"], state["brd_metadata"]
Writes: state["agent_plan"], state["routing_map"], state["brd_summary"],
        state["revision_counts"], state["current_stage"], state["current_step"]
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage

from orchestration.state import SPECIALIST_AGENTS, BRDState, Stage
from skills.llm_factory import get_llm

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM = (
    "You summarize a Business Requirements Document for an engineering leadership "
    "audience in 2-3 sentences: what is being built, the primary business goal, "
    "and the headline scope or constraint. No preamble, just the summary."
)


def orchestrator_node(state: BRDState) -> Dict[str, Any]:
    pending = state.get("pending_revision")
    if pending:
        logger.info("🧭 ORCHESTRATOR — revision re-entry, routing to '%s'", pending)
        return {
            "current_stage": Stage.ORCHESTRATE,
            "current_step":  f"revision_routed:{pending}",
            "errors":        state.get("errors", []),
        }

    logger.info("=" * 65)
    logger.info("🧭 ORCHESTRATOR — planning specialist run + section routing")
    logger.info("=" * 65)

    framework_config = state.get("framework_config", {})
    llm_config       = framework_config.get("_llm_config", {})
    sections         = state.get("brd_sections", [])
    requirements     = state.get("requirements", [])
    metadata         = state.get("brd_metadata", {})

    if not requirements:
        logger.warning("⚠️ No classified requirements — agents will work from sections only.")

    agent_plan  = list(SPECIALIST_AGENTS)
    routing_map = _build_routing_map(sections, requirements)
    brd_summary = _summarize(sections, requirements, metadata, llm_config)

    logger.info("📋 Summary: %s", brd_summary)
    for agent in agent_plan:
        logger.info("   %-18s → %d section(s)", agent, len(routing_map.get(agent, [])))

    # Ensure every specialist has a revision counter (defensive; factory seeds them).
    revision_counts = {a: state.get("revision_counts", {}).get(a, 0) for a in SPECIALIST_AGENTS}

    return {
        "agent_plan":      agent_plan,
        "routing_map":     routing_map,
        "brd_summary":     brd_summary,
        "revision_counts": revision_counts,
        "current_stage":   Stage.PLAN,
        "current_step":    "orchestration_complete",
        "errors":          state.get("errors", []),
        "messages": state.get("messages", []) + [
            {"role": "assistant", "content": f"Orchestration: {len(agent_plan)} specialists queued"}
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Routing
# ─────────────────────────────────────────────────────────────────────────────
def _build_routing_map(
    sections: List[Dict[str, Any]],
    requirements: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Point each specialist at the section_ids most relevant to it.

    Every agent falls back to all requirement-bearing sections (or all sections
    if none carry requirements) so nothing is ever starved of context.
    """
    all_section_ids = [s["section_id"] for s in sections]

    def sids(pred) -> List[str]:
        return sorted({r["section_id"] for r in requirements if pred(r)})

    req_sids        = sids(lambda r: True) or all_section_ids
    functional      = sids(lambda r: r.get("type") == "functional")
    non_functional  = sids(lambda r: r.get("type") == "non_functional")
    constraints     = sids(lambda r: r.get("type") in ("constraint", "assumption"))
    risky           = sids(lambda r: r.get("ambiguity_flag") or r.get("priority") == "must")

    def merge(*groups: List[str]) -> List[str]:
        out = sorted({sid for g in groups for sid in g})
        return out or req_sids

    return {
        "engineering_plan": req_sids,
        "schedule":         req_sids,
        "architecture":     merge(functional, non_functional, constraints),
        "poc_plan":         merge(risky, constraints, non_functional),
        "tech_stack":       merge(non_functional, constraints),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
def _summarize(
    sections: List[Dict[str, Any]],
    requirements: List[Dict[str, Any]],
    metadata: Dict[str, Any],
    llm_config: Dict[str, Any],
) -> str:
    fallback = _fallback_summary(requirements, metadata)
    context = (
        f"PROJECT: {metadata.get('project_name') or 'unnamed'}\n"
        f"GOALS: {'; '.join(metadata.get('business_goals', [])[:4])}\n"
        f"SECTIONS: {', '.join(s['title'] for s in sections[:15])}\n"
        f"KEY REQUIREMENTS:\n"
        + "\n".join(f"- {r['text']}" for r in requirements[:12])
    )
    try:
        llm = get_llm("orchestrator", llm_config)
        resp = llm.invoke([
            SystemMessage(content=_SUMMARY_SYSTEM),
            HumanMessage(content=context),
        ])
        text = (resp.content or "").strip()
        return text or fallback
    except Exception as e:  # noqa: BLE001 - summary is best-effort
        logger.warning("Orchestrator summary LLM failed (%s); using fallback", e)
        return fallback


def _fallback_summary(requirements: List[Dict[str, Any]], metadata: Dict[str, Any]) -> str:
    name = metadata.get("project_name") or "This BRD"
    goals = metadata.get("business_goals", [])
    if goals:
        return f"{name}: {goals[0]}"
    if requirements:
        return f"{name} covering: " + "; ".join(r["text"] for r in requirements[:3])
    return f"{name} (no structured summary available)."
