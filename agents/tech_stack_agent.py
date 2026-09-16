"""
agents/tech_stack_agent.py
─────────────────────────────────────────────────────────────────────────────
LangGraph node: Tech Stack Recommender (Design).

2-3 genuinely different stack options covering every architecture layer, each
scored on scalability / team familiarity / integration risk / cost /
time-to-market, plus a recommendation tied to the BRD's dominant constraint.

Reads:  architecture, brd_metadata, requirements, framework_config
Writes: state["tech_stack"] (AgentArtifact), advances to Stage.CRITIQUE
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from orchestration.state import BRDState, Stage
from agents.specialist_base import (
    fail,
    finish,
    grounding_for,
    invoke_json,
    llm_config_of,
    requirements_block,
    revision_block,
    revision_issues,
    routed_requirements,
)
from skills.llm_factory import get_llm
from skills.rag_retriever import load_persona
from skills.schemas import TechStack
from skills.tech_radar import lookup_tech_radar_status

logger = logging.getLogger(__name__)

AGENT_KEY = "tech_stack"
LLM_NAME = "tech_stack_recommender"


@tool
def check_tech_radar_status(technology: str) -> str:
    """Look up this org's Tech Radar status for one named technology (e.g.
    'FastAPI', 'Java', 'Postgres'). Returns its status — ADOPT, TRIAL, HOLD,
    or RETIRE — and a short note. Call this for every candidate technology
    before scoring or recommending it; don't guess radar status from memory,
    the radar changes independently of what any model was trained on."""
    entry = lookup_tech_radar_status(technology)
    if not entry:
        return f"'{technology}' is not on the tech radar — no explicit guidance; use judgment and say so."
    return f"{entry['technology']}: {entry['status']} — {entry['note']}"


def _gather_tech_radar_findings(llm: Any, user_prompt: str) -> str:
    """Real LLM-native tool-calling: let the model call check_tech_radar_status
    for the technologies it's weighing, before it drafts the recommendation.
    Feature-detected via bind_tools — test doubles (FakeLLM) don't define it,
    so this cleanly no-ops there and callers fall back to plain KB grounding."""
    bind_tools = getattr(llm, "bind_tools", None)
    if bind_tools is None:
        return ""

    llm_with_tools = bind_tools([check_tech_radar_status])
    messages: list = [
        SystemMessage(content=(
            "Before any recommendation is drafted, gather facts. Call "
            "check_tech_radar_status for every candidate technology you're "
            "weighing for this BRD — aim for 4-8 calls covering language, "
            "framework, datastore, and infra. Do not draft a recommendation "
            "here; only call the tool."
        )),
        HumanMessage(content=user_prompt),
    ]
    findings: list[str] = []
    resp = llm_with_tools.invoke(messages)
    hops = 0
    while getattr(resp, "tool_calls", None) and hops < 6:
        messages.append(resp)
        for call in resp.tool_calls:
            result = check_tech_radar_status.invoke(call["args"])
            findings.append(str(result))
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
        resp = llm_with_tools.invoke(messages)
        hops += 1

    return "\n".join(f"- {f}" for f in dict.fromkeys(findings))  # de-dup, keep order


_SYSTEM = """{persona}

Propose 2-3 technology stack options for this solution and recommend one.

Rules:
- Each option covers every layer: language, framework, datastore, infra, ci_cd, observability.
- Respect the org tech radar (ADOPT preferred; justify TRIAL; never HOLD/RETIRE).
- Options must be genuinely different in shape, not three flavors of one.
- Score each 1-5 on scalability, team_familiarity, integration_risk (5 = low risk),
  cost (5 = low cost), time_to_market (5 = fast).
- The recommendation ties back to the BRD's dominant constraint.

KNOWLEDGE BASE (tech radar, comparable deliveries):
{grounding}

Return ONLY this JSON:
{
  "options": [
    {
      "name": "",
      "shape": "",
      "layers": {"language": "", "framework": "", "datastore": "", "infra": "",
                 "ci_cd": "", "observability": ""},
      "scores": {"scalability": 0, "team_familiarity": 0, "integration_risk": 0,
                 "cost": 0, "time_to_market": 0},
      "tradeoffs": "",
      "best_when": ""
    }
  ],
  "recommendation": {"option_name": "", "justification": "", "dominant_constraint": ""},
  "citations": ["KB:<doc>#<n>"]
}"""


def tech_stack_node(state: BRDState) -> Dict[str, Any]:
    logger.info("=" * 65)
    logger.info("🧰 TECH STACK RECOMMENDER — options + trade-offs")
    logger.info("=" * 65)

    arch = state.get("architecture")
    arch_content = arch["content"] if arch and arch.get("status") == "ok" else {}
    metadata = state.get("brd_metadata", {})

    persona = load_persona(LLM_NAME)
    grounding = grounding_for(state, AGENT_KEY)
    reqs = routed_requirements(state, AGENT_KEY)

    user = (
        revision_block(revision_issues(state, AGENT_KEY))
        + f"BRD SUMMARY: {state.get('brd_summary', '')}\n\n"
        f"ARCHITECTURE COMPONENTS: {arch_content.get('components', [])}\n\n"
        f"CONSTRAINTS & NON-FUNCTIONAL REQUIREMENTS:\n{requirements_block(reqs)}\n\n"
        f"REFERENCED SYSTEMS: {metadata.get('referenced_systems', [])}"
    )

    try:
        radar_findings = _gather_tech_radar_findings(get_llm(LLM_NAME, llm_config_of(state)), user)
    except Exception as e:  # noqa: BLE001 - tool-calling is a supplementary grounding step
        logger.warning("Tech radar tool calls failed (%s); continuing on KB grounding alone.", e)
        radar_findings = ""
    if radar_findings:
        logger.info("📡 Tech radar tool calls returned %d finding(s)", radar_findings.count("\n") + 1)
        user += f"\n\nTECH RADAR — VERIFIED VIA TOOL CALL (trust this over the KB text below):\n{radar_findings}"

    try:
        parsed = invoke_json(
            LLM_NAME, state,
            _SYSTEM.replace("{persona}", persona).replace("{grounding}", grounding[:8000]),
            user,
            schema=TechStack,
            extra_check=_check_radar_compliance,
        )
    except Exception as e:  # noqa: BLE001
        return fail(AGENT_KEY, state, f"LLM call failed: {e}", Stage.CRITIQUE)

    return finish(AGENT_KEY, parsed, state, Stage.CRITIQUE)


def _check_radar_compliance(parsed: Dict[str, Any]) -> list[str]:
    """Scope control: the prompt already says 'never HOLD/RETIRE' — this is
    what actually enforces it, deterministically, against the real radar,
    instead of trusting the model to always follow a prose rule. Every named
    technology across every option's layers is checked for real; a HOLD or
    RETIRE match is a contract violation retried the same way a schema
    violation already is."""
    problems = []
    for option in parsed.get("options", []):
        layers = option.get("layers", {}) or {}
        for layer_name, tech in layers.items():
            if not tech:
                continue
            entry = lookup_tech_radar_status(tech)
            if entry and entry["status"] in ("HOLD", "RETIRE"):
                problems.append(
                    f"option '{option.get('name', '?')}' layer '{layer_name}'='{tech}' is "
                    f"{entry['status']} on the tech radar ({entry['note']}) — never recommend a "
                    f"HOLD/RETIRE technology, per this agent's own rules"
                )
    return problems
