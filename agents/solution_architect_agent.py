"""
agents/solution_architect_agent.py
─────────────────────────────────────────────────────────────────────────────
LangGraph node: Solution Architect (Design).

High-level design: components, data flows, NFR mapping (every non_functional
requirement must appear -- enforced deterministically by _check_nfr_coverage),
key decisions, and a Mermaid diagram.

Reads:  requirements, brd_metadata, framework_config
Writes: state["architecture"] (AgentArtifact), advances to Stage.POC
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
from skills.schemas import SolutionArchitecture

logger = logging.getLogger(__name__)

AGENT_KEY = "architecture"
LLM_NAME = "solution_architect"

_SYSTEM = """{persona}

Produce a high-level solution architecture, grounded in the knowledge base
(architecture patterns, NFR catalogue, tech radar, security baseline).

Rules:
- Name every external/referenced system in "context".
- 4-8 components, each with ONE responsibility.
- EVERY non_functional requirement id must appear in "nfr_mapping".
- Apply the security baseline.
- Prefer the simplest topology that meets the NFRs.
- "mermaid": a valid flowchart. ALWAYS wrap node labels in double quotes
  (e.g. A["Web client (SPA)"]); never put raw parentheses/colons/commas in an
  unquoted label. Use simple alphanumeric node ids.

KNOWLEDGE BASE:
{grounding}

Return ONLY this JSON:
{
  "context": "",
  "components": [
    {"name": "", "responsibility": "", "tech_area": "web|service|worker|datastore|queue|integration",
     "interfaces": [""]}
  ],
  "data_flows": [
    {"from": "", "to": "", "data": "", "protocol": "http|grpc|event|file", "mode": "sync|async"}
  ],
  "integrations": [
    {"system": "", "direction": "inbound|outbound|bidirectional", "method": ""}
  ],
  "nfr_mapping": [
    {"nfr_category": "", "requirement_ids": [""], "tactic": "", "verification": ""}
  ],
  "key_decisions": [
    {"decision": "", "rationale": "", "alternatives_rejected": [""]}
  ],
  "mermaid": "graph TD\\n  A[\"Web client\"] --> B[\"BFF\"]\\n  B --> C[\"Order service\"]",
  "citations": ["KB:<doc>#<n>"]
}"""


def solution_architect_node(state: BRDState) -> Dict[str, Any]:
    logger.info("=" * 65)
    logger.info("🏛️  SOLUTION ARCHITECT — components, flows, NFR mapping")
    logger.info("=" * 65)

    persona = load_persona(LLM_NAME)
    grounding = grounding_for(state, AGENT_KEY)
    reqs = routed_requirements(state, AGENT_KEY)
    metadata = state.get("brd_metadata", {})
    nfr_ids = {r.get("req_id") for r in reqs if r.get("type") == "non_functional" and r.get("req_id")}

    user = (
        revision_block(revision_issues(state, AGENT_KEY))
        + f"BRD SUMMARY: {state.get('brd_summary', '')}\n\n"
        f"REFERENCED SYSTEMS: {metadata.get('referenced_systems', [])}\n\n"
        f"REQUIREMENTS:\n{requirements_block(reqs)}"
    )

    try:
        parsed = invoke_json(
            LLM_NAME, state,
            _SYSTEM.replace("{persona}", persona).replace("{grounding}", grounding[:9000]),
            user,
            schema=SolutionArchitecture,
            extra_check=lambda d: _check_nfr_coverage(d, nfr_ids),
        )
    except Exception as e:  # noqa: BLE001
        return fail(AGENT_KEY, state, f"LLM call failed: {e}", Stage.POC)

    return finish(AGENT_KEY, parsed, state, Stage.POC)


def _check_nfr_coverage(parsed: Dict[str, Any], nfr_ids: set) -> list:
    """Cross-agent contract check: every non_functional requirement routed to
    this agent must appear in some nfr_mapping[].requirement_ids entry -- the
    prompt already says "EVERY non_functional requirement id must appear in
    nfr_mapping"; this is what actually enforces it, the same way Schedule's
    _check_phase_alignment and PoC Planner's _check_component_contracts
    enforce their own prompt rules deterministically."""
    if not nfr_ids:
        return []
    covered = {
        rid
        for mapping in parsed.get("nfr_mapping", [])
        for rid in (mapping.get("requirement_ids") or [])
    }
    missing = sorted(nfr_ids - covered)
    if not missing:
        return []
    return [
        f"nfr_mapping is missing non_functional requirement(s) {missing}; "
        f"every non_functional req_id must appear in some nfr_mapping[].requirement_ids entry"
    ]
