"""
agents/critic_agent.py
─────────────────────────────────────────────────────────────────────────────
LangGraph node: Critic (Validation & Evaluation — Capability 4).

One node scores every "dirty" deliverable (no score yet, revised since last
scored, or any artifact after a revision run) on four dimensions:

  completeness · consistency (cross-artifact) · actionability · groundedness

`overall` and `verdict` are computed in Python from configured weights — the LLM
supplies the dimension scores and the issue list, not the arithmetic.

Revision loop: among artifacts whose verdict is "revise", route back to the
EARLIEST one (pipeline order) that still has revision budget; increment its
counter and set state["pending_revision"]. When none remain, go to assemble.

Reads:  all five deliverables, requirements, framework_config, critic_scores
Writes: state["critic_scores"], state["quality_badges"], state["revision_counts"],
        state["pending_revision"], state["current_stage"], state["current_step"]
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from agents.specialist_base import invoke_json
from orchestration.state import (
    SPECIALIST_AGENTS,
    BRDState,
    CriticScore,
    Stage,
    Verdict,
    badge_for_score,
    revision_improvement,
)
from skills.rag_retriever import get_retriever, load_persona
from skills.schemas import CriticDimensions

logger = logging.getLogger(__name__)

LLM_NAME = "critic"

_DEFAULT_WEIGHTS = {
    "completeness": 0.30, "consistency": 0.25, "actionability": 0.25, "groundedness": 0.20,
}

_SYSTEM = """{persona}

Score ONE deliverable. Return ONLY this JSON (scores are 0.0-1.0):
{
  "completeness": 0.0,
  "consistency": 0.0,
  "actionability": 0.0,
  "groundedness": 0.0,
  "issues": ["specific, actionable instruction for the authoring agent"]
}
Do not compute an overall score or a verdict — that is done downstream.
Keep issues sharp: 2-5 items, each fixable."""


# ─────────────────────────────────────────────────────────────────────────────
# Node
# ─────────────────────────────────────────────────────────────────────────────
def critic_node(state: BRDState) -> Dict[str, Any]:
    logger.info("=" * 65)
    logger.info("🧪 CRITIC — scoring deliverables, enforcing revision loop")
    logger.info("=" * 65)

    framework_config = state.get("framework_config", {})
    llm_config       = framework_config.get("_llm_config", {})
    weights          = _normalize_weights(framework_config.get("rubric_weights", _DEFAULT_WEIGHTS))
    min_pass         = float(
        framework_config.get("revision", {}).get("min_pass_score")
        or llm_config.get("revision", {}).get("min_pass_score", 0.75)
    )
    max_revisions    = int(llm_config.get("revision", {}).get("max_revisions_per_agent", 2))

    scores   = dict(state.get("critic_scores", {}))
    badges   = dict(state.get("quality_badges", {}))
    # Every score ever computed for an artifact, in order — critic_scores[agent]
    # only ever holds the latest, so this is the only place a before/after
    # revision delta can be read from.
    history  = {k: list(v) for k, v in state.get("score_history", {}).items()}
    just_revised = state.get("current_step", "").endswith("_revised")

    dirty = _dirty_agents(state, scores, force_all=just_revised)
    logger.info("   scoring: %s", ", ".join(dirty) or "(nothing new)")

    persona = load_persona(LLM_NAME)
    badges_cfg = framework_config.get("badges", {})
    for agent in dirty:
        score = _score_artifact(agent, state, persona, weights, min_pass, badges_cfg)
        scores[agent] = score
        badges[agent] = score["badge"]
        history.setdefault(agent, []).append(score)
        logger.info(
            "   %-18s overall=%.2f verdict=%s badge=%s",
            agent, score["overall"], score["verdict"], score["badge"],
        )
        if len(history[agent]) > 1:
            prev, delta = history[agent][-2]["overall"], score["overall"] - history[agent][-2]["overall"]
            logger.info(
                "   %-18s revision %d: %.2f → %.2f (%+.2f)",
                agent, score.get("scored_revision", 0), prev, score["overall"], delta,
            )

    # ── Revision routing ─────────────────────────────────────────────────
    revision_counts = dict(state.get("revision_counts", {}))
    target = _pick_revision_target(scores, revision_counts, max_revisions)

    if target:
        revision_counts[target] = revision_counts.get(target, 0) + 1
        logger.warning(
            "🔁 Routing back to '%s' for revision %d/%d",
            target, revision_counts[target], max_revisions,
        )
        return {
            "critic_scores":    scores,
            "score_history":    history,
            "quality_badges":   badges,
            "revision_counts":  revision_counts,
            "pending_revision": target,
            "current_stage":    Stage.CRITIQUE,
            "current_step":     f"critic_revise:{target}",
            "errors":           state.get("errors", []),
        }

    accepted = {a: s["badge"] for a, s in scores.items()}
    logger.info("✅ Critic complete — badges: %s", accepted)
    for agent, delta in revision_improvement(history).items():
        logger.info(
            "   📈 %-18s %d revision(s): %.2f → %.2f (%+.2f)",
            agent, delta["revisions"], delta["first_overall"], delta["last_overall"], delta["delta"],
        )
    return {
        "critic_scores":    scores,
        "score_history":    history,
        "quality_badges":   badges,
        "revision_counts":  revision_counts,
        "pending_revision": None,
        "current_stage":    Stage.ASSEMBLE,
        "current_step":     "critic_complete",
        "errors":           state.get("errors", []),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dirty tracking
# ─────────────────────────────────────────────────────────────────────────────
def _dirty_agents(state: BRDState, scores: Dict[str, CriticScore], force_all: bool) -> List[str]:
    out: List[str] = []
    for agent in SPECIALIST_AGENTS:
        art = state.get(agent)
        if not art:
            continue
        if art.get("status") == "failed":
            out.append(agent)
            continue
        prev = scores.get(agent)
        if prev is None or force_all or prev.get("scored_revision") != art.get("revision", 0):
            out.append(agent)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────
def _score_artifact(
    agent: str,
    state: BRDState,
    persona: str,
    weights: Dict[str, float],
    min_pass: float,
    badges_cfg: Dict[str, Any],
) -> CriticScore:
    art = state.get(agent) or {}
    revision = int(art.get("revision", 0))

    if art.get("status") == "failed":
        return _make_score(
            agent, {"completeness": 0.0, "consistency": 0.0, "actionability": 0.0, "groundedness": 0.0},
            ["Agent failed to produce output — re-run required."],
            weights, min_pass, revision, badges_cfg,
        )

    missing = _missing_sections(agent, art.get("content", {}), state)
    citation_texts = _resolve_citations(art.get("citations", []))

    user = _score_prompt(agent, art, state, missing, citation_texts)
    try:
        # schema=CriticDimensions gives the Critic's own output the same
        # validate-and-one-retry bar the five specialists already have — a
        # reply missing a dimension or shaped wrong is retried with the exact
        # problem fed back, not silently coerced by .get(k, 0.5) with no
        # second attempt.
        raw = invoke_json(LLM_NAME, state, _SYSTEM.replace("{persona}", persona), user,
                           schema=CriticDimensions)
    except Exception as e:  # noqa: BLE001 - a scoring failure should not crash the pipeline
        logger.warning("Critic scoring failed for %s: %s", agent, e)
        raw = {"completeness": 0.5, "consistency": 0.5, "actionability": 0.5,
               "groundedness": 0.5, "issues": [f"Critic could not score this artifact ({e})."]}

    dims = {k: _clamp(raw.get(k, 0.5)) for k in _DEFAULT_WEIGHTS}
    issues = list(raw.get("issues", []) or [])

    # Deterministic overrides
    if missing:
        dims["completeness"] = min(dims["completeness"], 0.45)
        issues.append(f"Missing/empty required sections: {', '.join(missing)}.")
    if not art.get("citations"):
        dims["groundedness"] = min(dims["groundedness"], 0.5)
        issues.append("No knowledge-base citations provided; ground claims in retrieved KB material.")

    return _make_score(agent, dims, issues, weights, min_pass, revision, badges_cfg)


def _make_score(
    agent: str,
    dims: Dict[str, float],
    issues: List[str],
    weights: Dict[str, float],
    min_pass: float,
    revision: int,
    badges_cfg: Dict[str, Any],
) -> CriticScore:
    overall = round(sum(dims[k] * weights[k] for k in weights), 4)
    verdict = Verdict.REVISE if (overall < min_pass or any(v < 0.5 for v in dims.values())) else Verdict.PASS
    badge = badge_for_score(overall, {"badges": badges_cfg})
    return CriticScore(
        agent=agent,
        completeness=dims["completeness"],
        consistency=dims["consistency"],
        actionability=dims["actionability"],
        groundedness=dims["groundedness"],
        overall=overall,
        verdict=verdict,
        issues=issues[:6],
        badge=badge,
        scored_revision=revision,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Revision target selection
# ─────────────────────────────────────────────────────────────────────────────
def _pick_revision_target(
    scores: Dict[str, CriticScore],
    revision_counts: Dict[str, int],
    max_revisions: int,
) -> str | None:
    for agent in SPECIALIST_AGENTS:            # pipeline order = priority
        s = scores.get(agent)
        if not s or s["verdict"] != Verdict.REVISE:
            continue
        if revision_counts.get(agent, 0) < max_revisions:
            return agent
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _normalize_weights(w: Dict[str, float]) -> Dict[str, float]:
    w = {k: float(w.get(k, _DEFAULT_WEIGHTS[k])) for k in _DEFAULT_WEIGHTS}
    total = sum(w.values()) or 1.0
    return {k: v / total for k, v in w.items()}


def _clamp(x: Any) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.5


def _missing_sections(agent: str, content: Dict[str, Any], state: BRDState) -> List[str]:
    required = state.get("framework_config", {}).get("required_sections", {}).get(agent, [])
    return [k for k in required if not content.get(k)]


def _resolve_citations(refs: List[str]) -> Dict[str, str]:
    if not refs:
        return {}
    try:
        return get_retriever().resolve_citations(refs)
    except Exception as e:  # noqa: BLE001
        logger.warning("Citation resolution failed: %s", e)
        return {r: "" for r in refs}


def _score_prompt(
    agent: str,
    art: Dict[str, Any],
    state: BRDState,
    missing: List[str],
    citation_texts: Dict[str, str],
) -> str:
    others = {
        a: (state.get(a) or {}).get("content", {})
        for a in SPECIALIST_AGENTS if a != agent and state.get(a)
    }
    cite_block = "\n\n".join(
        f"{ref}:\n{txt[:1200] if txt else '(REFERENCE NOT FOUND IN KB)'}"
        for ref, txt in citation_texts.items()
    ) or "(no citations supplied)"

    return (
        f"DELIVERABLE TYPE: {agent}\n"
        f"REQUIRED SECTIONS: {state.get('framework_config', {}).get('required_sections', {}).get(agent, [])}\n"
        f"MISSING/EMPTY SECTIONS (pre-checked): {missing or 'none'}\n\n"
        f"BRD SUMMARY: {state.get('brd_summary', '')}\n\n"
        f"BRD REQUIREMENTS:\n"
        + "\n".join(f"- ({r.get('req_id')}) {r.get('text')}" for r in state.get("requirements", [])[:40])
        + f"\n\nTHIS DELIVERABLE:\n{json.dumps(art.get('content', {}), indent=2)[:6000]}\n\n"
        f"OTHER DELIVERABLES (for consistency checking):\n{json.dumps(others, indent=2)[:6000]}\n\n"
        f"CITED KNOWLEDGE-BASE MATERIAL (judge groundedness against this):\n{cite_block}"
    )
