"""
tests/test_workflow_smoke.py
─────────────────────────────────────────────────────────────────────────────
End-to-end smoke test of the compiled LangGraph workflow with every LLM call
and RAG lookup stubbed. Asserts the pipeline reaches assemble with all five
deliverables + badges, and that the Critic revision loop terminates.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import agents.brd_ingest_agent as ingest_mod
import agents.critic_agent as critic_mod
import agents.engineering_plan_agent as plan_mod
import agents.orchestrator_agent as orch_mod
import agents.poc_planner_agent as poc_mod
import agents.specialist_base as base
import agents.tech_stack_agent as tech_mod
import orchestration.langgraph_workflow as wf
from orchestration.state import SPECIALIST_AGENTS, Stage, make_initial_state

BRD_TEXT = """# 1. Overview
Project Atlas replaces the legacy reporting stack for the analytics team.

# 2. Functional Requirements
The system must export reports as PDF. The system must email reports on a schedule.

# 3. Non-Functional Requirements
Report generation must finish within 60 seconds for a 100-page report.

# 4. Constraints
Hosting must stay within the existing Azure subscription.
"""

# One constant deliverable that satisfies every agent's required_sections.
_DELIVERABLE = {
    "phases": [{"name": "Design"}], "risks": [{"risk": "integration"}],
    "milestones": [{"name": "beta", "target_week": 8}],
    "team_composition": [{"role": "engineer", "count": 3}],
    "requirement_coverage": [{"req_id": "R001", "phase": "Design"}],
    "assumptions": ["ledger read replica exists"],
    "phase_effort": [{"phase": "Design", "person_weeks": 2}],
    "timeline": [{"phase": "Design", "start_week": 0, "end_week": 2}],
    "resource_matrix": [{"role": "engineer", "phase": "Design", "allocation_pct": 100}],
    "critical_path": ["Design"], "alignment_ok": True,
    "context": "Atlas", "components": [{"name": "ReportSvc", "responsibility": "render"}],
    "data_flows": [{"from": "ReportSvc", "to": "Blob", "data": "pdf", "protocol": "file", "mode": "async"}],
    "nfr_mapping": [{"nfr_category": "performance", "requirement_ids": ["R003"], "tactic": "async"}],
    "key_decisions": [{"decision": "async rendering", "rationale": "SLA"}],
    "mermaid": "graph TD; A-->B;",
    "poc_goal": "render 100-page report < 60s", "hypotheses": ["async wins"],
    "in_scope": ["render path"], "out_of_scope": ["native app", "auth"],
    "modules": [{"name": "Renderer", "maps_to_component": "ReportSvc"}],
    "success_criteria": [{"metric": "runtime", "threshold": "<60s", "measurement_method": "timed run"}],
    "duration_weeks": 2, "resources": [{"role": "engineer", "count": 1}],
    "exit_decision_matrix": [{"outcome": "all criteria met", "decision": "proceed"}],
    "options": [{"name": "Monolith"}, {"name": "Service+Queue"}],
    "recommendation": {"option_name": "Monolith", "justification": "team fit"},
    "citations": ["KB:tech_radar.md#0", "KB:estimation_heuristics.md#0"],
}

_GOOD_SCORE = {"completeness": 0.88, "consistency": 0.85, "actionability": 0.86,
               "groundedness": 0.82, "issues": []}


class ConstantLLM:
    def __init__(self, content: str):
        self._content = content

    def invoke(self, _messages):
        return SimpleNamespace(content=self._content)


class FakeRetriever:
    def retrieve_for_agent(self, *_a, **_k):
        return "[KB:tech_radar.md#0]\nPostgreSQL is the ADOPT default OLTP store."

    def resolve_citations(self, refs):
        return {r: "Supporting knowledge-base text for the cited claim." for r in refs}


def _fake_get_llm(agent_name, _llm_config=None):
    if agent_name == "orchestrator":
        return ConstantLLM("Atlas replaces the legacy analytics reporting stack on Azure.")
    if agent_name == "critic":
        return ConstantLLM(json.dumps(_GOOD_SCORE))
    if agent_name == "brd_ingest":
        return ConstantLLM(json.dumps({"requirements": [
            {"text": "The system must export reports as PDF.", "type": "functional", "priority": "must"}
        ]}))
    return ConstantLLM(json.dumps(_DELIVERABLE))     # any specialist / reflection


@pytest.fixture(autouse=True)
def _stub_everything(monkeypatch):
    # tech_mod and poc_mod each call get_llm() directly too (not just through
    # invoke_json/base) for their own tool-calling steps (tech radar, Jira).
    # ConstantLLM has no bind_tools(), so both cleanly no-op here — real
    # tool-calling has its own dedicated tests in test_specialist_agents.py.
    # An unpatched module here doesn't fail fast: get_llm() falls through to
    # a REAL ChatOpenAI + a real network call if a genuine OPENAI_API_KEY is
    # present (e.g. from a local .env) — it looks like a slow test, not an
    # error, so it's easy to miss. Live-caught: this exact thing happened
    # when the Jira tool was added and poc_mod was forgotten here.
    for mod in (base, plan_mod, critic_mod, orch_mod, ingest_mod, tech_mod, poc_mod):
        monkeypatch.setattr(mod, "get_llm", _fake_get_llm, raising=False)
    monkeypatch.setattr(base, "get_retriever", lambda *a, **k: FakeRetriever())
    monkeypatch.setattr(critic_mod, "get_retriever", lambda *a, **k: FakeRetriever())


@pytest.fixture
def framework_config(tmp_path):
    cfg = wf.load_configs()
    cfg["output"] = {
        "parsed_dir": str(tmp_path / "parsed"),
        "deliverables_dir": str(tmp_path / "deliverables"),
        "report_dir": str(tmp_path / "reports"),
    }
    return cfg


def _run(framework_config):
    app = wf.build_workflow()          # no checkpointer
    initial = make_initial_state("BRD-SMOKE", "t-smoke", framework_config, brd_raw_text=BRD_TEXT)
    return app.invoke(initial, {"recursion_limit": wf.RECURSION_LIMIT})


# ── Tests ────────────────────────────────────────────────────────────────────
def test_pipeline_reaches_complete(framework_config):
    final = _run(framework_config)
    assert final["current_stage"] == Stage.COMPLETE
    assert final["current_step"] == "assemble_complete"


def test_all_five_deliverables_present(framework_config):
    final = _run(framework_config)
    for agent in SPECIALIST_AGENTS:
        art = final[agent]
        assert art is not None and art["status"] == "ok"
        assert art["content"]


def test_badges_assigned_and_green(framework_config):
    final = _run(framework_config)
    for agent in SPECIALIST_AGENTS:
        assert final["quality_badges"][agent] == "green"
    assert final["quality_badges"]["_overall"] == "green"


def test_response_doc_built(framework_config):
    final = _run(framework_config)
    doc = final["brd_response_doc"]
    assert "# BRD Response" in doc
    assert "Quality Scorecard" in doc
    assert "Solution Architecture" in doc


def test_reflection_recorded_on_plan(framework_config):
    final = _run(framework_config)
    assert final["engineering_plan"]["self_review"] is not None


def test_ingest_failure_aborts(framework_config):
    app = wf.build_workflow()
    initial = make_initial_state("BRD-EMPTY", "t-e", framework_config, brd_raw_text="")
    final = app.invoke(initial, {"recursion_limit": wf.RECURSION_LIMIT})
    assert final["current_stage"] == Stage.FAILED
    assert final.get("engineering_plan") is None


def test_revision_loop_terminates(framework_config, monkeypatch):
    # Force the critic to always want a revision; the per-agent budget must stop it.
    bad = {"completeness": 0.4, "consistency": 0.4, "actionability": 0.4,
           "groundedness": 0.4, "issues": ["needs work"]}

    def _always_revise(agent_name, _cfg=None):
        if agent_name == "critic":
            return ConstantLLM(json.dumps(bad))
        return _fake_get_llm(agent_name, _cfg)

    for mod in (base, plan_mod, critic_mod, orch_mod, ingest_mod, tech_mod, poc_mod):
        monkeypatch.setattr(mod, "get_llm", _always_revise, raising=False)

    final = _run(framework_config)
    assert final["current_stage"] == Stage.COMPLETE
    # every specialist hit its revision ceiling
    max_rev = framework_config["_llm_config"]["revision"]["max_revisions_per_agent"]
    for agent in SPECIALIST_AGENTS:
        assert final["revision_counts"][agent] == max_rev
        assert final["quality_badges"][agent] == "red"
