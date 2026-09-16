"""
agents/poc_planner_agent.py
─────────────────────────────────────────────────────────────────────────────
LangGraph node: PoC Planner (Design).

Consumes the architecture (modules map 1:1 to components) and the plan's risk
register. Produces a time-boxed PoC with measurable success criteria and an
exit decision matrix.

Reads:  architecture, engineering_plan, requirements, framework_config
Writes: state["poc_plan"] (AgentArtifact), advances to Stage.TECH_STACK
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from orchestration.state import BRDState, Stage
from agents.specialist_base import (
    fail,
    finish,
    grounding_for,
    invoke_json,
    revision_block,
    revision_issues,
)
from skills.rag_retriever import load_persona
from skills.schemas import PocPlan

logger = logging.getLogger(__name__)

AGENT_KEY = "poc_plan"
LLM_NAME = "poc_planner"

_SYSTEM = """{persona}

Design a time-boxed proof of concept that retires the single biggest technical
risk or unknown before the full build commits.

Rules:
- ONE falsifiable poc_goal (yes/no or number vs threshold).
- Every module maps to a component in the architecture below.
- success_criteria are measurable: metric + threshold + measurement_method.
- Aggressively populate out_of_scope.

KNOWLEDGE BASE:
{grounding}

Return ONLY this JSON:
{
  "poc_goal": "",
  "hypotheses": [""],
  "in_scope": [""],
  "out_of_scope": [""],
  "modules": [
    {"name": "", "maps_to_component": "", "boundary": "", "interfaces": [""], "collaborators": "real|mocked"}
  ],
  "success_criteria": [
    {"metric": "", "threshold": "", "measurement_method": ""}
  ],
  "duration_weeks": 0,
  "resources": [{"role": "", "count": 0}],
  "exit_decision_matrix": [
    {"outcome": "all criteria met|partially met|not met", "decision": ""}
  ],
  "citations": ["KB:<doc>#<n>"]
}"""


def poc_planner_node(state: BRDState) -> Dict[str, Any]:
    logger.info("=" * 65)
    logger.info("🧪 POC PLANNER — scope, measurable criteria, module boundaries")
    logger.info("=" * 65)

    arch = state.get("architecture")
    arch_content = arch["content"] if arch and arch.get("status") == "ok" else {}
    plan = state.get("engineering_plan")
    risks = plan["content"].get("risks", []) if plan and plan.get("status") == "ok" else []

    persona = load_persona(LLM_NAME)
    grounding = grounding_for(state, AGENT_KEY)
    known_components = {c.get("name") for c in arch_content.get("components", []) if c.get("name")}

    user = (
        revision_block(revision_issues(state, AGENT_KEY))
        + f"BRD SUMMARY: {state.get('brd_summary', '')}\n\n"
        f"ARCHITECTURE COMPONENTS: {arch_content.get('components', [])}\n\n"
        f"KEY DECISIONS: {arch_content.get('key_decisions', [])}\n\n"
        f"PLAN RISK REGISTER: {risks}"
    )

    try:
        parsed = invoke_json(
            LLM_NAME, state,
            _SYSTEM.replace("{persona}", persona).replace("{grounding}", grounding[:8000]),
            user,
            schema=PocPlan,
            extra_check=lambda d: _check_component_contracts(d, known_components),
        )
    except Exception as e:  # noqa: BLE001
        return fail(AGENT_KEY, state, f"LLM call failed: {e}", Stage.TECH_STACK)

    return finish(AGENT_KEY, parsed, state, Stage.TECH_STACK)


def _check_component_contracts(parsed: Dict[str, Any], known_components: set) -> list[str]:
    """Cross-agent contract check: every module.maps_to_component must name a
    real Solution Architect component, not just a plausible-sounding one. The
    prompt already says this ("every module maps to a component in the
    architecture below") — this is what actually enforces it. Case-insensitive
    so a superficial casing difference doesn't burn the one retry the schema
    validation also shares."""
    if not known_components:
        return []  # architecture failed/produced no components — nothing to check against
    known_lower = {c.lower() for c in known_components}
    problems = []
    for m in parsed.get("modules", []):
        target = (m.get("maps_to_component") or "").strip()
        if target and target.lower() not in known_lower:
            problems.append(
                f"module '{m.get('name', '?')}' maps_to_component='{target}' does not match any "
                f"architecture component (valid: {sorted(known_components)})"
            )
    return problems
