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

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from orchestration.state import BRDState, Stage
from agents.specialist_base import (
    fail,
    finish,
    grounding_for,
    invoke_json,
    llm_config_of,
    revision_block,
    revision_issues,
)
from skills.jira_tickets import JiraNotConfigured, search_related_tickets
from skills.llm_factory import get_llm
from skills.rag_retriever import load_persona
from skills.schemas import PocPlan

logger = logging.getLogger(__name__)

AGENT_KEY = "poc_plan"
LLM_NAME = "poc_planner"


@tool
def check_related_jira_tickets(topic: str) -> str:
    """Search this org's Jira project for tickets already related to a
    proposed PoC topic (e.g. 'real-time notification service', 'OAuth
    migration'). Call this once per major PoC angle before finalizing
    poc_goal/modules, so the plan doesn't propose work that's already
    tracked. Returns matching ticket keys, summaries and status, or a
    message saying none were found / Jira isn't configured for this
    deployment."""
    try:
        tickets = search_related_tickets(topic)
    except JiraNotConfigured:
        return "Jira isn't configured for this deployment — no ticket check available; use judgment."
    if not tickets:
        return f"No related tickets found in Jira for '{topic}'."
    return "\n".join(f"{t['key']} [{t['status']}]: {t['summary']}" for t in tickets)


def _gather_jira_findings(llm: Any, user_prompt: str) -> str:
    """Real LLM-native tool-calling: let the model check Jira for tickets
    already covering a proposed PoC topic before it drafts the plan.
    Feature-detected via bind_tools — test doubles (FakeLLM) don't define
    it, so this cleanly no-ops there, the same as tech_stack's radar tool."""
    bind_tools = getattr(llm, "bind_tools", None)
    if bind_tools is None:
        return ""

    llm_with_tools = bind_tools([check_related_jira_tickets])
    messages: list = [
        SystemMessage(content=(
            "Before drafting the PoC, check whether related work is already "
            "tracked. Call check_related_jira_tickets for the main topic and "
            "any distinct alternative framing of it — 1-3 calls is enough. "
            "Do not draft anything here; only call the tool."
        )),
        HumanMessage(content=user_prompt),
    ]
    findings: list[str] = []
    resp = llm_with_tools.invoke(messages)
    hops = 0
    while getattr(resp, "tool_calls", None) and hops < 4:
        messages.append(resp)
        for call in resp.tool_calls:
            result = check_related_jira_tickets.invoke(call["args"])
            findings.append(str(result))
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
        resp = llm_with_tools.invoke(messages)
        hops += 1

    return "\n".join(f"- {f}" for f in dict.fromkeys(findings))

_SYSTEM = """{persona}

Design a time-boxed proof of concept that retires the single biggest technical
risk or unknown before the full build commits.

Rules:
- ONE falsifiable poc_goal (yes/no or number vs threshold).
- Every module maps to a component in the architecture below.
- success_criteria are measurable: metric + threshold + measurement_method.
- Aggressively populate out_of_scope.
- If related Jira tickets are already tracked (see below), don't propose
  work that duplicates them — scope around what's already in flight.

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
        jira_findings = _gather_jira_findings(get_llm(LLM_NAME, llm_config_of(state)), user)
    except Exception as e:  # noqa: BLE001 - tool-calling is a supplementary check, not required
        logger.warning("Jira ticket tool calls failed (%s); continuing without it.", e)
        jira_findings = ""
    if jira_findings:
        logger.info("🎫 Jira tool calls returned %d finding(s)", jira_findings.count("\n") + 1)
        user += f"\n\nRELATED JIRA TICKETS — VERIFIED VIA TOOL CALL:\n{jira_findings}"

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
