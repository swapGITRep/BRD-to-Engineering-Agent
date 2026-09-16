"""
agents/engineering_plan_agent.py
─────────────────────────────────────────────────────────────────────────────
LangGraph node: Engineering Plan Generator (Planning).

Draft → Reflection self-review → Revise, all in one node. The reflection notes
are stored on the artifact as `self_review`.

Reads:  requirements, routing_map, brd_summary, framework_config
Writes: state["engineering_plan"] (AgentArtifact), advances to Stage.SCHEDULE
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from orchestration.state import BRDState, Stage
from agents.specialist_base import (
    finish,
    fail,
    grounding_for,
    invoke_json,
    requirements_block,
    revision_block,
    revision_issues,
    routed_requirements,
)
from skills.rag_retriever import load_persona
from skills.schemas import EngineeringPlan, ReflectionReview

logger = logging.getLogger(__name__)

AGENT_KEY = "engineering_plan"
LLM_NAME = "engineering_plan_generator"

_SCHEMA = """Return ONLY this JSON:
{
  "phases": [
    {"name": "", "objective": "", "entry_criteria": [""], "exit_criteria": [""], "deliverables": [""]}
  ],
  "risks": [
    {"risk": "", "likelihood": "low|medium|high", "impact": "low|medium|high",
     "mitigation": "", "owner": "", "retire_by_phase": ""}
  ],
  "milestones": [
    {"name": "", "target_week": 0, "depends_on": [""]}
  ],
  "team_composition": [
    {"role": "", "count": 0, "allocation_pct": 0, "phase": ""}
  ],
  "requirement_coverage": [
    {"req_id": "", "phase": ""}
  ],
  "assumptions": [""],
  "out_of_scope": [""],
  "citations": ["KB:<doc>#<n>"]
}"""

_DRAFT_SYSTEM = """{persona}

You produce a phased engineering plan from a parsed BRD, grounded in the
knowledge base below. Cite KB sources you rely on in the "citations" array.

KNOWLEDGE BASE:
{grounding}

""" + _SCHEMA

_REFLECT_SYSTEM = """You are the same Engineering Manager reviewing your own draft plan.
Be harsh. Check:
- phase coverage: does every BRD requirement map to a phase deliverable? list unmapped req_ids.
- risk register: are external dependencies and unknowns from the BRD captured?
- milestones: does each milestone's depends_on point at real phases/deliverables?
- team realism: does team_composition fit the BRD's stated team size / skills?
- assumptions & out_of_scope: are the BRD's restated?

Return ONLY JSON:
{"issues": ["specific, actionable fix"], "verdict": "ok" | "revise"}"""

_REVISE_SYSTEM = """{persona}

Revise your engineering plan to resolve every issue listed. Keep everything that
was already good. Return the SAME JSON schema as before (including "citations").

KNOWLEDGE BASE:
{grounding}

""" + _SCHEMA


def engineering_plan_node(state: BRDState) -> Dict[str, Any]:
    logger.info("=" * 65)
    logger.info("📐 ENGINEERING PLAN GENERATOR — draft → reflect → revise")
    logger.info("=" * 65)

    persona = load_persona(LLM_NAME)
    grounding = grounding_for(state, AGENT_KEY)
    reqs = routed_requirements(state, AGENT_KEY)
    prior_issues = revision_issues(state, AGENT_KEY)

    user = (
        revision_block(prior_issues)
        + f"BRD SUMMARY: {state.get('brd_summary', '')}\n\n"
        f"REQUIREMENTS:\n{requirements_block(reqs)}\n\n"
        f"METADATA: {state.get('brd_metadata', {})}"
    )

    try:
        # 1. draft
        draft = invoke_json(
            LLM_NAME, state,
            _DRAFT_SYSTEM.replace("{persona}", persona).replace("{grounding}", grounding[:9000]),
            user,
            schema=EngineeringPlan,
        )
        # 2. reflect
        review = _reflect(state, draft)
        logger.info("🪞 Reflection verdict=%s (%d issue(s))", review.get("verdict"), len(review.get("issues", [])))
        # 3. revise (only if the self-review asks for it)
        if review.get("verdict") == "revise" and review.get("issues"):
            revise_user = (
                "ISSUES TO FIX:\n" + "\n".join(f"- {i}" for i in review["issues"])
                + f"\n\nDRAFT PLAN:\n{draft}\n\nORIGINAL REQUIREMENTS:\n{requirements_block(reqs)}"
            )
            final = invoke_json(
                LLM_NAME, state,
                _REVISE_SYSTEM.replace("{persona}", persona).replace("{grounding}", grounding[:9000]),
                revise_user,
                schema=EngineeringPlan,
            )
        else:
            final = draft
    except Exception as e:  # noqa: BLE001
        return fail(AGENT_KEY, state, f"LLM call failed: {e}", Stage.SCHEDULE)

    return finish(AGENT_KEY, final, state, Stage.SCHEDULE, self_review=review)


def _reflect(state: BRDState, draft: Dict[str, Any]) -> Dict[str, Any]:
    try:
        # schema=ReflectionReview brings this call up to the same
        # validate-and-one-retry bar the draft/revise calls already have,
        # instead of trusting review.setdefault() to paper over a malformed
        # reply with no second attempt.
        return invoke_json(LLM_NAME, state, _REFLECT_SYSTEM, f"DRAFT PLAN:\n{draft}",
                            schema=ReflectionReview)
    except Exception as e:  # noqa: BLE001 - reflection is advisory
        logger.warning("Reflection step failed (%s); skipping revise", e)
        return {"issues": [], "verdict": "ok"}
