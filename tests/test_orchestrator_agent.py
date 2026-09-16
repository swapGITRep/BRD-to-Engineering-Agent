"""
tests/test_orchestrator_agent.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for agents/orchestrator_agent.orchestrator_node.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import pytest

import agents.orchestrator_agent as mod
from orchestration.state import SPECIALIST_AGENTS, Stage, make_initial_state

SECTIONS = [
    {"section_id": "S001", "title": "Overview", "level": 1, "raw_text": "x", "page_range": ""},
    {"section_id": "S002", "title": "Functional Requirements", "level": 1, "raw_text": "x", "page_range": ""},
    {"section_id": "S003", "title": "Non-Functional Requirements", "level": 1, "raw_text": "x", "page_range": ""},
    {"section_id": "S004", "title": "Constraints", "level": 1, "raw_text": "x", "page_range": ""},
]
REQUIREMENTS = [
    {"req_id": "R001", "section_id": "S002", "text": "export PDF", "type": "functional",
     "nfr_category": None, "priority": "must", "ambiguity_flag": False},
    {"req_id": "R002", "section_id": "S003", "text": "p95 < 300ms", "type": "non_functional",
     "nfr_category": "performance", "priority": "must", "ambiguity_flag": False},
    {"req_id": "R003", "section_id": "S004", "text": "must stay on Azure", "type": "constraint",
     "nfr_category": None, "priority": "must", "ambiguity_flag": False},
    {"req_id": "R004", "section_id": "S002", "text": "reports should be nice", "type": "functional",
     "nfr_category": None, "priority": "could", "ambiguity_flag": True},
]


@pytest.fixture
def state(brd_framework_config):
    s = make_initial_state("BRD-O1", "t-o1", brd_framework_config)
    s["brd_sections"] = SECTIONS
    s["requirements"] = REQUIREMENTS
    s["brd_metadata"] = {"project_name": "Atlas", "business_goals": ["cut reporting effort in half"]}
    return s


def test_plan_is_all_specialists_in_order(state, fake_llm, monkeypatch):
    monkeypatch.setattr(mod, "get_llm", lambda *a, **k: fake_llm("Atlas replaces reporting."))
    out = mod.orchestrator_node(state)
    assert out["agent_plan"] == list(SPECIALIST_AGENTS)
    assert out["current_stage"] == Stage.PLAN
    assert out["current_step"] == "orchestration_complete"


def test_routing_map_has_entry_per_agent(state, fake_llm, monkeypatch):
    monkeypatch.setattr(mod, "get_llm", lambda *a, **k: fake_llm("summary"))
    rmap = mod.orchestrator_node(state)["routing_map"]
    assert set(rmap) == set(SPECIALIST_AGENTS)
    assert all(rmap[a] for a in SPECIALIST_AGENTS)


def test_architecture_routes_to_nfr_and_constraint_sections(state, fake_llm, monkeypatch):
    monkeypatch.setattr(mod, "get_llm", lambda *a, **k: fake_llm("summary"))
    rmap = mod.orchestrator_node(state)["routing_map"]
    assert "S003" in rmap["architecture"]      # NFR
    assert "S004" in rmap["architecture"]      # constraint
    assert "S004" in rmap["tech_stack"]
    assert "S002" in rmap["poc_plan"]          # ambiguous functional req -> risky


def test_summary_uses_llm(state, fake_llm, monkeypatch):
    monkeypatch.setattr(mod, "get_llm", lambda *a, **k: fake_llm("Atlas modernizes reporting for analytics."))
    out = mod.orchestrator_node(state)
    assert out["brd_summary"] == "Atlas modernizes reporting for analytics."


def test_summary_fallback_when_llm_raises(state, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no key")
    monkeypatch.setattr(mod, "get_llm", boom)
    out = mod.orchestrator_node(state)
    assert out["brd_summary"] == "Atlas: cut reporting effort in half"


def test_revision_reentry_is_passthrough(state, monkeypatch):
    called = []
    monkeypatch.setattr(mod, "get_llm", lambda *a, **k: called.append(1))
    state["pending_revision"] = "schedule"
    out = mod.orchestrator_node(state)
    assert out["current_stage"] == Stage.ORCHESTRATE
    assert out["current_step"] == "revision_routed:schedule"
    assert "routing_map" not in out          # no re-planning
    assert called == []                       # no LLM call


def test_works_with_no_requirements(state, fake_llm, monkeypatch):
    monkeypatch.setattr(mod, "get_llm", lambda *a, **k: fake_llm("summary"))
    state["requirements"] = []
    rmap = mod.orchestrator_node(state)["routing_map"]
    # falls back to all section ids
    assert rmap["engineering_plan"] == ["S001", "S002", "S003", "S004"]
