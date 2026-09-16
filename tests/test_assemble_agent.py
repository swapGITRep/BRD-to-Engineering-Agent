"""
tests/test_assemble_agent.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for agents/assemble_agent.assemble_node.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json

import pytest

from agents.assemble_agent import assemble_node
from orchestration.state import Stage, make_initial_state

PLAN = {
    "phases": [{"name": "Design", "objective": "shape it", "entry_criteria": ["access"],
                "exit_criteria": ["arch signed off"], "deliverables": ["arch doc"]}],
    "risks": [{"risk": "IdP quirks", "likelihood": "high", "impact": "medium",
               "mitigation": "spike", "owner": "TL", "retire_by_phase": "Foundation"}],
    "milestones": [{"name": "beta", "target_week": 10, "depends_on": ["Core Build"]}],
    "team_composition": [{"role": "engineer", "count": 4, "allocation_pct": 100, "phase": "all"}],
    "requirement_coverage": [{"req_id": "R001", "phase": "Core Build"}],
    "assumptions": ["replica exists"], "out_of_scope": ["native app"],
}
SCHEDULE = {
    "alignment_ok": True,
    "phase_effort": [{"phase": "Design", "person_weeks": 3, "confidence": "±1 wk"}],
    "timeline": [{"phase": "Design", "start_week": 0, "end_week": 3, "parallel_with": []}],
    "resource_matrix": [{"role": "engineer", "phase": "Design", "allocation_pct": 50}],
    "critical_path": ["Design", "Core Build", "Hardening"],
    "contingency_pct": 20,
    "total_calendar_weeks": {"optimistic": 14, "likely": 17, "pessimistic": 21},
}
ARCH = {
    "context": "Portal talking to billing-svc and IdP.",
    "components": [{"name": "BFF", "responsibility": "aggregate", "tech_area": "service", "interfaces": ["REST"]}],
    "data_flows": [{"from": "SPA", "to": "BFF", "data": "requests", "protocol": "http", "mode": "sync"}],
    "integrations": [{"system": "billing-svc", "direction": "outbound", "method": "REST"}],
    "nfr_mapping": [{"nfr_category": "performance", "requirement_ids": ["R003"],
                     "tactic": "cache", "verification": "load test"}],
    "key_decisions": [{"decision": "BFF pattern", "rationale": "UI aggregation",
                       "alternatives_rejected": ["direct calls"]}],
    "mermaid": "graph TD; SPA-->BFF; BFF-->Billing;",
}
POC = {
    "poc_goal": "render 100-page report < 60s",
    "hypotheses": ["async wins"], "in_scope": ["render"], "out_of_scope": ["auth"],
    "modules": [{"name": "Renderer", "maps_to_component": "BFF", "boundary": "pdf only",
                 "interfaces": ["fn"], "collaborators": "mocked"}],
    "success_criteria": [{"metric": "runtime", "threshold": "<60s", "measurement_method": "timed"}],
    "duration_weeks": 2, "resources": [{"role": "engineer", "count": 1}],
    "exit_decision_matrix": [{"outcome": "all criteria met", "decision": "proceed"}],
}
TECH = {
    "options": [
        {"name": "Boring Monolith", "shape": "one deployable",
         "layers": {"language": "Python", "framework": "FastAPI", "datastore": "PostgreSQL",
                    "infra": "Container Apps", "ci_cd": "GH Actions", "observability": "App Insights"},
         "scores": {"scalability": 3, "team_familiarity": 5, "integration_risk": 4, "cost": 5, "time_to_market": 5},
         "tradeoffs": "simple but scales vertically first", "best_when": "small team, tight timeline"},
        {"name": "Service + Queue", "shape": "two services + bus",
         "layers": {"language": "Python", "framework": "FastAPI", "datastore": "PostgreSQL",
                    "infra": "Container Apps", "ci_cd": "GH Actions", "observability": "App Insights"},
         "scores": {"scalability": 5, "team_familiarity": 3, "integration_risk": 3, "cost": 3, "time_to_market": 3},
         "tradeoffs": "scales but more ops", "best_when": "spiky load"},
    ],
    "recommendation": {"option_name": "Boring Monolith", "justification": "team fit + timeline",
                       "dominant_constraint": "6-engineer team, 2-quarter deadline"},
}


def _art(agent, content, status="ok", revision=0, citations=None):
    return {"agent": agent, "content": content, "citations": citations or [f"KB:{agent}.md#0"],
            "revision": revision, "self_review": None, "status": status}


def _score(agent, overall, badge, issues=None, rev=0):
    return {"agent": agent, "completeness": overall, "consistency": overall,
            "actionability": overall, "groundedness": overall, "overall": overall,
            "verdict": "pass" if badge == "green" else "revise",
            "issues": issues or [], "badge": badge, "scored_revision": rev}


@pytest.fixture
def state(tmp_path, brd_framework_config):
    brd_framework_config["output"]["report_dir"] = str(tmp_path / "reports")
    s = make_initial_state("BRD-A1", "t-a1", brd_framework_config)
    s["brd_summary"] = "Rebuild the customer portal on Azure."
    s["brd_metadata"] = {"project_name": "Portal Revamp"}
    s["requirements"] = [{"req_id": "R001", "text": "x"}]
    s["brd_sections"] = [{"section_id": "S001"}]
    s["engineering_plan"] = _art("engineering_plan", PLAN)
    s["schedule"] = _art("schedule", SCHEDULE)
    s["architecture"] = _art("architecture", ARCH)
    s["poc_plan"] = _art("poc_plan", POC)
    s["tech_stack"] = _art("tech_stack", TECH)
    s["critic_scores"] = {
        "engineering_plan": _score("engineering_plan", 0.86, "green"),
        "schedule": _score("schedule", 0.72, "amber", ["tighten the contingency rationale"]),
        "architecture": _score("architecture", 0.83, "green"),
        "poc_plan": _score("poc_plan", 0.81, "green"),
        "tech_stack": _score("tech_stack", 0.84, "green"),
    }
    s["quality_badges"] = {"engineering_plan": "green", "schedule": "amber",
                           "architecture": "green", "poc_plan": "green", "tech_stack": "green"}
    return s


# ── Happy path ───────────────────────────────────────────────────────────────
def test_returns_complete_stage(state):
    out = assemble_node(state)
    assert out["current_stage"] == Stage.COMPLETE
    assert out["current_step"] == "assemble_complete"


def test_overall_badge_is_worst(state):
    out = assemble_node(state)
    assert out["quality_badges"]["_overall"] == "amber"      # one amber deliverable


def test_doc_has_all_sections(state):
    doc = assemble_node(state)["brd_response_doc"]
    for heading in ("# BRD Response — Portal Revamp", "## Executive Summary",
                    "## Quality Scorecard", "## Engineering Plan", "## Schedule & Estimates",
                    "## Solution Architecture", "## Proof-of-Concept Plan",
                    "## Technology Stack Options"):
        assert heading in doc


def test_doc_renders_tables_and_mermaid(state):
    doc = assemble_node(state)["brd_response_doc"]
    assert "| Risk | Likelihood | Impact |" in doc
    assert "```mermaid" in doc and "SPA-->BFF" in doc
    assert "Design → Core Build → Hardening" in doc          # critical path
    assert "**Boring Monolith**" in doc                       # recommendation
    assert "| Layer | Choice |" in doc


def test_open_critic_notes_only_for_non_green(state):
    doc = assemble_node(state)["brd_response_doc"]
    assert "## Open Critic Notes" in doc
    assert "tighten the contingency rationale" in doc
    # green deliverables' (empty) issues never appear
    assert doc.count("Open Critic Notes") == 1


def test_saved_to_disk(state, tmp_path):
    assemble_node(state)
    md = tmp_path / "reports" / "BRD-A1_response.md"
    js = tmp_path / "reports" / "BRD-A1_deliverables.json"
    assert md.exists() and js.exists()
    assert "Portal Revamp" in md.read_text()
    assert set(json.loads(js.read_text())) == {
        "engineering_plan", "schedule", "architecture", "poc_plan", "tech_stack"}


def test_manifest_written_for_history(state, tmp_path):
    assemble_node(state)
    mf = json.loads((tmp_path / "reports" / "BRD-A1_manifest.json").read_text())
    assert mf["brd_id"] == "BRD-A1"
    assert mf["project_name"] == "Portal Revamp"
    assert mf["quality_badges"]["_overall"] == "amber"
    assert mf["quality_badges"]["schedule"] == "amber"
    assert mf["section_count"] == 1
    assert mf["requirement_count"] == 1
    assert "generated_at" in mf and "critic_scores" in mf


# ── Revision improvement (before/after) ───────────────────────────────────────
def test_no_revision_improvement_section_when_nothing_revised(state):
    # The default fixture never populated score_history — every agent was
    # only ever scored once. The section must not appear and imply a
    # before/after that never happened.
    doc = assemble_node(state)["brd_response_doc"]
    assert "## Revision Improvement" not in doc


def test_revision_improvement_section_shown_after_a_real_revision(state, tmp_path):
    state["score_history"] = {
        "schedule": [
            _score("schedule", 0.55, "amber", rev=0),
            _score("schedule", 0.86, "green", rev=1),
        ],
    }
    out = assemble_node(state)
    doc = out["brd_response_doc"]

    assert "## Revision Improvement" in doc
    assert "| Schedule & Estimates | 1 | 0.55 | 0.86 | 📈 +0.31 |" in doc
    # only agents actually revised appear — not all five
    assert "Engineering Plan |" not in doc.split("## Revision Improvement")[1].split("##")[0]

    mf = json.loads((tmp_path / "reports" / "BRD-A1_manifest.json").read_text())
    assert mf["revision_improvement"]["schedule"]["revisions"] == 1
    assert mf["revision_improvement"]["schedule"]["delta"] == pytest.approx(0.31)


# ── Degraded inputs ──────────────────────────────────────────────────────────
def test_failed_deliverable_marked_and_rolls_up_red(state):
    state["architecture"] = _art("architecture", {}, status="failed")
    state["quality_badges"]["architecture"] = "red"
    out = assemble_node(state)
    assert "_Not produced" in out["brd_response_doc"]
    assert out["quality_badges"]["_overall"] == "red"


def test_empty_content_does_not_crash(state):
    for a in ("engineering_plan", "schedule", "architecture", "poc_plan", "tech_stack"):
        state[a] = _art(a, {})
    doc = assemble_node(state)["brd_response_doc"]
    assert "_(none)_" in doc
    assert "## Technology Stack Options" in doc


def test_alignment_warning_shown(state):
    state["schedule"]["content"]["alignment_ok"] = False
    state["schedule"]["content"]["alignment_notes"] = "merged Design into Discovery"
    doc = assemble_node(state)["brd_response_doc"]
    assert "not aligned" in doc and "merged Design into Discovery" in doc
