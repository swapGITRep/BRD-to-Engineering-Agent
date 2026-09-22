"""
agents/schedule_estimator_agent.py
─────────────────────────────────────────────────────────────────────────────
LangGraph node: Schedule Estimator (Planning).

Consumes the engineering plan's phases + team composition and the estimation
heuristics KB. Produces effort, timeline, resource matrix, critical path — and
an `alignment_ok` flag if it had to deviate from the plan's phases.

Reads:  engineering_plan, requirements, framework_config
Writes: state["schedule"] (AgentArtifact), advances to Stage.ARCHITECTURE
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
    requirements_block,
    revision_block,
    revision_issues,
    routed_requirements,
)
from skills.rag_retriever import load_persona
from skills.schemas import Schedule

logger = logging.getLogger(__name__)

AGENT_KEY = "schedule"
LLM_NAME = "schedule_estimator"

_SYSTEM = """{persona}

Produce a defensible schedule from the engineering plan below. Do NOT invent new
phases; use the plan's phase names/order. If you must deviate, set
"alignment_ok": false and explain in "alignment_notes".

Two specific invented phases to never use, however tempting: a buffer/slack
phase named something like "Contingency" — that belongs in "contingency_pct",
not a fake phase row; and a catch-all phase named "All" in resource_matrix to
mean "this role works across every phase" — instead, add one resource_matrix
row per real phase that role is actually allocated to.

KNOWLEDGE BASE (estimation heuristics, comparable deliveries):
{grounding}

Return ONLY this JSON:
{
  "alignment_ok": true,
  "alignment_notes": "",
  "phase_effort": [
    {"phase": "", "person_weeks": 0, "confidence": "optimistic|likely|pessimistic ranges as text"}
  ],
  "timeline": [
    {"phase": "", "start_week": 0, "end_week": 0, "parallel_with": [""]}
  ],
  "resource_matrix": [
    {"role": "", "phase": "", "allocation_pct": 0}
  ],
  "critical_path": [""],
  "contingency_pct": 0,
  "total_calendar_weeks": {"optimistic": 0, "likely": 0, "pessimistic": 0},
  "citations": ["KB:<doc>#<n>"]
}"""


def schedule_estimator_node(state: BRDState) -> Dict[str, Any]:
    logger.info("=" * 65)
    logger.info("🗓️  SCHEDULE ESTIMATOR — effort, timeline, resourcing")
    logger.info("=" * 65)

    plan = state.get("engineering_plan")
    plan_content = plan["content"] if plan and plan.get("status") == "ok" else {}
    if not plan_content:
        logger.warning("⚠️ No engineering plan available — estimating from requirements only.")
    known_phases = {p.get("name") for p in plan_content.get("phases", []) if p.get("name")}

    persona = load_persona(LLM_NAME)
    grounding = grounding_for(state, AGENT_KEY)
    reqs = routed_requirements(state, AGENT_KEY)

    user = (
        revision_block(revision_issues(state, AGENT_KEY))
        + f"BRD SUMMARY: {state.get('brd_summary', '')}\n\n"
        f"ENGINEERING PLAN:\n"
        f"phases={plan_content.get('phases', [])}\n"
        f"team_composition={plan_content.get('team_composition', [])}\n\n"
        f"REQUIREMENTS:\n{requirements_block(reqs)}"
    )

    try:
        parsed = invoke_json(
            LLM_NAME, state,
            _SYSTEM.replace("{persona}", persona).replace("{grounding}", grounding[:8000]),
            user,
            schema=Schedule,
            extra_check=lambda d: _check_phase_alignment(d, known_phases),
        )
    except Exception as e:  # noqa: BLE001
        return fail(AGENT_KEY, state, f"LLM call failed: {e}", Stage.ARCHITECTURE)

    return finish(AGENT_KEY, parsed, state, Stage.ARCHITECTURE)


def _check_phase_alignment(parsed: Dict[str, Any], known_phases: set) -> list:
    """Cross-agent contract check: every phase referenced in phase_effort,
    timeline, or resource_matrix should name a real Engineering Plan phase —
    the prompt already says "do NOT invent new phases"; this is what actually
    enforces it. Skipped when alignment_ok=False, since a deliberate,
    explained deviation (a genuinely new phase name) is then the expected
    behavior, not a mistake to correct."""
    if not known_phases or not parsed.get("alignment_ok", True):
        return []
    known_lower = {p.lower() for p in known_phases}
    problems, seen = [], set()
    for section, items in (
        ("phase_effort", parsed.get("phase_effort", [])),
        ("timeline", parsed.get("timeline", [])),
        ("resource_matrix", parsed.get("resource_matrix", [])),
    ):
        for item in items:
            phase = (item.get("phase") or "").strip()
            if phase and phase.lower() not in known_lower and phase not in seen:
                seen.add(phase)
                problems.append(
                    f"{section} references phase '{phase}' which is not in the engineering "
                    f"plan's phases (valid: {sorted(known_phases)}); either use a real phase "
                    f"name or set alignment_ok=false and explain the deviation in alignment_notes"
                )
    return problems
