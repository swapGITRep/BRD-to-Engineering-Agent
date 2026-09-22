"""
tests/test_specialist_agents.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for the five specialist agents. LLM + RAG grounding are stubbed.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import agents.engineering_plan_agent as plan_mod
import agents.poc_planner_agent as poc_mod
import agents.schedule_estimator_agent as sched_mod
import agents.solution_architect_agent as arch_mod
import agents.specialist_base as base
import agents.tech_stack_agent as tech_mod
from orchestration.state import Stage, make_initial_state

GROUNDING = "[KB:engineering_plan_template.md#0]\nphases have entry/exit criteria."

REQUIREMENTS = [
    {"req_id": "R001", "section_id": "S002", "text": "export PDF", "type": "functional",
     "nfr_category": None, "priority": "must", "ambiguity_flag": False},
    {"req_id": "R002", "section_id": "S003", "text": "p95 < 300ms", "type": "non_functional",
     "nfr_category": "performance", "priority": "must", "ambiguity_flag": False},
]


@pytest.fixture
def state(tmp_path, brd_framework_config):
    brd_framework_config["output"]["deliverables_dir"] = str(tmp_path / "deliverables")
    s = make_initial_state("BRD-S1", "t-s1", brd_framework_config)
    s["requirements"] = REQUIREMENTS
    s["brd_summary"] = "Atlas modernizes reporting."
    s["brd_metadata"] = {"project_name": "Atlas", "referenced_systems": ["billing-svc"]}
    s["routing_map"] = {k: ["S002", "S003"] for k in
                        ("engineering_plan", "schedule", "architecture", "poc_plan", "tech_stack")}
    s["agent_plan"] = ["engineering_plan", "schedule", "architecture", "poc_plan", "tech_stack"]
    return s


def _artifact(agent, content):
    return {"agent": agent, "content": content, "citations": [], "revision": 0,
            "self_review": None, "status": "ok"}


def _patch_llm(monkeypatch, fake):
    # engineering_plan_agent's _reflect() now goes through invoke_json (and
    # so through base.get_llm) instead of calling get_llm directly — patching
    # base alone covers draft, reflect, and revise.
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)


class _ToolCallingFakeLLM:
    """Unlike the shared FakeLLM, this supports bind_tools()/tool_calls —
    used only to exercise tech_stack_agent's real tool-calling path. Queue
    a {"_tool_calls": [...]} item for a turn where the model calls a tool,
    or a plain str/dict for a normal content response."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls: list = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        nxt = self._responses.pop(0)
        if isinstance(nxt, dict) and "_tool_calls" in nxt:
            return SimpleNamespace(content="", tool_calls=nxt["_tool_calls"])
        content = nxt if isinstance(nxt, str) else json.dumps(nxt)
        return SimpleNamespace(content=content, tool_calls=None)

    @property
    def call_count(self) -> int:
        return len(self.calls)


# ── Engineering Plan Generator ───────────────────────────────────────────────
class TestEngineeringPlan:

    def test_draft_then_reflection_ok(self, state, fake_llm, monkeypatch):
        monkeypatch.setattr(plan_mod, "grounding_for", lambda *a, **k: GROUNDING)
        draft = {"phases": [{"name": "Design"}], "risks": [], "milestones": [],
                 "team_composition": [], "citations": ["KB:engineering_plan_template.md#0"]}
        fake = fake_llm(draft, {"issues": [], "verdict": "ok"})
        _patch_llm(monkeypatch, fake)

        out = plan_mod.engineering_plan_node(state)

        assert fake.call_count == 2                       # draft + reflect, no revise
        assert out["current_stage"] == Stage.SCHEDULE
        assert out["current_step"] == "engineering_plan_complete"
        art = out["engineering_plan"]
        assert art["status"] == "ok"
        assert art["citations"] == ["KB:engineering_plan_template.md#0"]
        assert art["self_review"] == {"issues": [], "verdict": "ok"}
        assert "citations" not in art["content"]

    def test_reflection_triggers_revise(self, state, fake_llm, monkeypatch):
        monkeypatch.setattr(plan_mod, "grounding_for", lambda *a, **k: GROUNDING)
        draft = {"phases": [], "risks": [], "milestones": [], "team_composition": []}
        review = {"issues": ["R001 is not mapped to any phase"], "verdict": "revise"}
        revised = {"phases": [{"name": "Build"}], "risks": [], "milestones": [],
                   "team_composition": [], "requirement_coverage": [{"req_id": "R001", "phase": "Build"}]}
        fake = fake_llm(draft, review, revised)
        _patch_llm(monkeypatch, fake)

        out = plan_mod.engineering_plan_node(state)

        assert fake.call_count == 3
        # schema validation normalizes the content (fills in defaulted fields
        # the fixture omitted), so check what changed rather than exact equality
        assert out["engineering_plan"]["content"]["phases"][0]["name"] == "Build"
        assert out["engineering_plan"]["self_review"]["verdict"] == "revise"

    def test_llm_failure_is_non_blocking(self, state, fake_llm, monkeypatch):
        # invoke_json retries an invalid-JSON reply once before giving up —
        # queue two bad replies so the retry itself is also exercised here.
        monkeypatch.setattr(plan_mod, "grounding_for", lambda *a, **k: GROUNDING)
        fake = fake_llm("not json", "still not json")
        _patch_llm(monkeypatch, fake)
        out = plan_mod.engineering_plan_node(state)
        assert fake.call_count == 2                            # draft + one retry, then give up
        assert out["engineering_plan"]["status"] == "failed"
        assert out["current_stage"] == Stage.SCHEDULE          # pipeline still advances
        assert any("engineering_plan" in e for e in out["errors"])

    def test_invalid_json_is_retried_once_then_succeeds(self, state, fake_llm, monkeypatch):
        # The common real-world glitch: a large draft comes back with one
        # stray syntax error. invoke_json should retry with the parse error
        # fed back and succeed, rather than failing the whole agent.
        monkeypatch.setattr(plan_mod, "grounding_for", lambda *a, **k: GROUNDING)
        draft = {"phases": [{"name": "Design"}], "risks": [], "milestones": [],
                 "team_composition": [], "citations": ["KB:engineering_plan_template.md#0"]}
        fake = fake_llm("{not valid json", draft, {"issues": [], "verdict": "ok"})
        _patch_llm(monkeypatch, fake)

        out = plan_mod.engineering_plan_node(state)

        assert fake.call_count == 3                            # bad draft, retry, reflect
        assert out["engineering_plan"]["status"] == "ok"
        assert out["current_stage"] == Stage.SCHEDULE

    def test_schema_violation_is_retried_once_then_succeeds(self, state, fake_llm, monkeypatch):
        # Syntactically valid JSON that's still structurally wrong (missing
        # the required "phases" key) must be caught by schema validation,
        # not silently reach finish() with an incomplete artifact.
        monkeypatch.setattr(plan_mod, "grounding_for", lambda *a, **k: GROUNDING)
        missing_phases = {"risks": [], "milestones": [], "team_composition": []}
        good = {"phases": [{"name": "Design"}], "risks": [], "milestones": [],
                "team_composition": [], "citations": []}
        fake = fake_llm(missing_phases, good, {"issues": [], "verdict": "ok"})
        _patch_llm(monkeypatch, fake)

        out = plan_mod.engineering_plan_node(state)

        assert fake.call_count == 3                            # bad draft, retry, reflect
        assert out["engineering_plan"]["status"] == "ok"
        assert out["engineering_plan"]["content"]["phases"][0]["name"] == "Design"


# ── Schedule Estimator ───────────────────────────────────────────────────────
class TestSchedule:

    def test_happy_path_reads_plan(self, state, fake_llm, monkeypatch):
        monkeypatch.setattr(sched_mod, "grounding_for", lambda *a, **k: GROUNDING)
        state["engineering_plan"] = _artifact("engineering_plan",
                                              {"phases": [{"name": "Design"}], "team_composition": []})
        fake = fake_llm({"alignment_ok": True, "phase_effort": [{"phase": "Design", "person_weeks": 2}],
                         "timeline": [], "resource_matrix": [], "critical_path": []})
        monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)

        out = sched_mod.schedule_estimator_node(state)
        assert out["current_stage"] == Stage.ARCHITECTURE
        assert out["schedule"]["content"]["alignment_ok"] is True
        assert "Design" in str(fake.calls[0])                  # plan phases fed into prompt

    def test_invented_phase_is_retried_once_then_succeeds(self, state, fake_llm, monkeypatch):
        # The prompt already says "do NOT invent new phases" — this is what
        # actually enforces it. A phase absent from the real engineering plan
        # must be caught and retried, not silently accepted.
        monkeypatch.setattr(sched_mod, "grounding_for", lambda *a, **k: GROUNDING)
        state["engineering_plan"] = _artifact("engineering_plan",
                                              {"phases": [{"name": "Design"}], "team_composition": []})
        invented_phase = {"alignment_ok": True,
                           "phase_effort": [{"phase": "Discovery", "person_weeks": 2}],
                           "timeline": [], "resource_matrix": [], "critical_path": []}
        correct = {"alignment_ok": True, "phase_effort": [{"phase": "Design", "person_weeks": 2}],
                   "timeline": [], "resource_matrix": [], "critical_path": []}
        fake = fake_llm(invented_phase, correct)
        monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)

        out = sched_mod.schedule_estimator_node(state)

        assert fake.call_count == 2                            # invented phase, retry
        assert out["schedule"]["status"] == "ok"
        assert out["schedule"]["content"]["phase_effort"][0]["phase"] == "Design"
        assert "Discovery" in str(fake.calls[1])                # the mismatch was fed back

    def test_deliberate_deviation_with_alignment_ok_false_is_not_flagged(self, state, fake_llm, monkeypatch):
        # A new phase name is fine when the agent explains it's a real,
        # documented deviation — the contract check should not fight that.
        monkeypatch.setattr(sched_mod, "grounding_for", lambda *a, **k: GROUNDING)
        state["engineering_plan"] = _artifact("engineering_plan",
                                              {"phases": [{"name": "Design"}], "team_composition": []})
        deviated = {"alignment_ok": False, "alignment_notes": "Split Design into two phases.",
                    "phase_effort": [{"phase": "Design-API", "person_weeks": 1},
                                      {"phase": "Design-UI", "person_weeks": 1}],
                    "timeline": [], "resource_matrix": [], "critical_path": []}
        fake = fake_llm(deviated)
        monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)

        out = sched_mod.schedule_estimator_node(state)

        assert fake.call_count == 1                            # no retry — deviation was declared
        assert out["schedule"]["status"] == "ok"


# ── Solution Architect ───────────────────────────────────────────────────────
class TestArchitect:

    def test_happy_path(self, state, fake_llm, monkeypatch):
        monkeypatch.setattr(arch_mod, "grounding_for", lambda *a, **k: GROUNDING)
        fake = fake_llm({"context": "x", "components": [{"name": "API"}], "data_flows": [],
                         "nfr_mapping": [{"nfr_category": "performance", "requirement_ids": ["R002"]}],
                         "key_decisions": [], "mermaid": "graph TD; A-->B;"})
        monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
        out = arch_mod.solution_architect_node(state)
        assert out["current_stage"] == Stage.POC
        # schema validation normalizes the content (fills in defaulted fields
        # the fixture omitted), so check what changed rather than exact equality
        assert out["architecture"]["content"]["components"][0]["name"] == "API"


# ── PoC Planner ──────────────────────────────────────────────────────────────
class TestPoc:

    def test_reads_architecture_components(self, state, fake_llm, monkeypatch):
        monkeypatch.setattr(poc_mod, "grounding_for", lambda *a, **k: GROUNDING)
        state["architecture"] = _artifact("architecture",
                                          {"components": [{"name": "MatchEngine"}], "key_decisions": []})
        state["engineering_plan"] = _artifact("engineering_plan", {"risks": [{"risk": "perf"}]})
        fake = fake_llm({"poc_goal": "match 500k in 30m", "modules": [{"name": "m", "maps_to_component": "MatchEngine"}],
                         "success_criteria": [{"metric": "runtime", "threshold": "<30m", "measurement_method": "run"}],
                         "exit_decision_matrix": []})
        monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
        # poc_mod also calls get_llm() directly for the Jira tool-calling step
        # (not just through invoke_json/base) — FakeLLM has no bind_tools(),
        # so this cleanly no-ops and the test stays deterministic either way;
        # the patch just keeps it from reaching a real client if .env got
        # loaded earlier in the same test session.
        monkeypatch.setattr(poc_mod, "get_llm", lambda *a, **k: fake)
        out = poc_mod.poc_planner_node(state)
        assert out["current_stage"] == Stage.TECH_STACK
        assert "MatchEngine" in str(fake.calls[0])

    def test_component_mismatch_is_retried_once_then_succeeds(self, state, fake_llm, monkeypatch):
        # The cross-agent contract check: a module.maps_to_component that
        # names a component the Solution Architect never produced must be
        # caught and retried, not silently accepted as a plausible answer.
        monkeypatch.setattr(poc_mod, "grounding_for", lambda *a, **k: GROUNDING)
        state["architecture"] = _artifact("architecture",
                                          {"components": [{"name": "MatchEngine"}], "key_decisions": []})
        state["engineering_plan"] = _artifact("engineering_plan", {"risks": []})
        wrong_component = {"poc_goal": "g", "modules": [{"name": "m", "maps_to_component": "GhostService"}],
                            "success_criteria": [], "exit_decision_matrix": []}
        correct = {"poc_goal": "g", "modules": [{"name": "m", "maps_to_component": "MatchEngine"}],
                   "success_criteria": [], "exit_decision_matrix": []}
        fake = fake_llm(wrong_component, correct)
        monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
        monkeypatch.setattr(poc_mod, "get_llm", lambda *a, **k: fake)

        out = poc_mod.poc_planner_node(state)

        assert fake.call_count == 2                            # wrong component, retry
        assert out["poc_plan"]["status"] == "ok"
        assert out["poc_plan"]["content"]["modules"][0]["maps_to_component"] == "MatchEngine"
        assert "GhostService" in str(fake.calls[1])             # the mismatch was fed back

    def test_jira_tool_is_called_and_findings_reach_the_prompt(self, state, monkeypatch):
        # Real LLM-native tool-calling: the model requests
        # check_related_jira_tickets, and its finding must reach the final
        # prompt before the PoC is drafted. search_related_tickets itself is
        # stubbed here (unlike tech_stack's radar tool, this one is a real
        # network call, not a local file lookup, so it can't be exercised
        # "for real" in a unit test) — this test is about the tool-calling
        # plumbing, not the Jira HTTP client (see tests/test_jira_tickets.py).
        monkeypatch.setattr(poc_mod, "grounding_for", lambda *a, **k: GROUNDING)
        state["architecture"] = _artifact("architecture",
                                          {"components": [{"name": "API"}], "key_decisions": []})
        monkeypatch.setattr(poc_mod, "search_related_tickets", lambda topic, max_results=5: [
            {"key": "ADT-7", "summary": "Prototype the matching engine", "status": "In Progress"},
        ])

        tool_call = [{"name": "check_related_jira_tickets", "args": {"topic": "matching engine PoC"}, "id": "call_1"}]
        final = {"poc_goal": "g", "modules": [{"name": "m", "maps_to_component": "API"}],
                 "success_criteria": [], "exit_decision_matrix": []}
        fake = _ToolCallingFakeLLM(
            {"_tool_calls": tool_call},   # 1: model asks to check the topic
            {"_tool_calls": None},        # 2: model is done gathering facts
            final,                        # 3: invoke_json's final JSON answer
        )
        monkeypatch.setattr(poc_mod, "get_llm", lambda *a, **k: fake)
        monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)

        out = poc_mod.poc_planner_node(state)

        assert out["poc_plan"]["status"] == "ok"
        assert "ADT-7" in str(fake.calls[-1])                   # the finding reached the final prompt
        assert "In Progress" in str(fake.calls[-1])

    def test_jira_not_configured_does_not_block_the_plan(self, state, monkeypatch):
        # No JIRA_* env vars set in the test environment — search_related_tickets
        # raises JiraNotConfigured for real (not stubbed), and the tool must
        # report that gracefully rather than raising out of the node.
        monkeypatch.setattr(poc_mod, "grounding_for", lambda *a, **k: GROUNDING)
        state["architecture"] = _artifact("architecture",
                                          {"components": [{"name": "API"}], "key_decisions": []})
        for var in ("JIRA_SITE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
            monkeypatch.delenv(var, raising=False)

        tool_call = [{"name": "check_related_jira_tickets", "args": {"topic": "x"}, "id": "call_1"}]
        final = {"poc_goal": "g", "modules": [{"name": "m", "maps_to_component": "API"}],
                 "success_criteria": [], "exit_decision_matrix": []}
        fake = _ToolCallingFakeLLM({"_tool_calls": tool_call}, {"_tool_calls": None}, final)
        monkeypatch.setattr(poc_mod, "get_llm", lambda *a, **k: fake)
        monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)

        out = poc_mod.poc_planner_node(state)

        assert out["poc_plan"]["status"] == "ok"
        assert "isn't configured" in str(fake.calls[-1])


# ── Tech Stack Recommender ───────────────────────────────────────────────────
class TestTechStack:

    def test_happy_path_advances_to_critique(self, state, fake_llm, monkeypatch):
        monkeypatch.setattr(tech_mod, "grounding_for", lambda *a, **k: GROUNDING)
        state["architecture"] = _artifact("architecture", {"components": [{"name": "API"}]})
        fake = fake_llm({"options": [{"name": "A"}, {"name": "B"}],
                         "recommendation": {"option_name": "A"}})
        monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
        # tech_mod also calls get_llm() directly for the tech-radar tool-calling
        # step (not just through invoke_json/base) — FakeLLM has no bind_tools(),
        # so this cleanly no-ops and the test stays deterministic either way; the
        # patch just keeps it from reaching a real client if .env got loaded
        # earlier in the same test session.
        monkeypatch.setattr(tech_mod, "get_llm", lambda *a, **k: fake)
        out = tech_mod.tech_stack_node(state)
        assert out["current_stage"] == Stage.CRITIQUE
        assert len(out["tech_stack"]["content"]["options"]) == 2

    def test_hold_technology_is_retried_once_then_succeeds(self, state, fake_llm, monkeypatch):
        # Scope control: the prompt already says "never HOLD/RETIRE" — this
        # must be enforced for real against the actual radar, not just asked
        # for. Java / Spring is HOLD in knowledge_base/.../tech_radar.md.
        monkeypatch.setattr(tech_mod, "grounding_for", lambda *a, **k: GROUNDING)
        state["architecture"] = _artifact("architecture", {"components": [{"name": "API"}]})

        hold_option = {"options": [{"name": "A", "layers": {"language": "Java"}}],
                       "recommendation": {"option_name": "A"}}
        fixed = {"options": [{"name": "A", "layers": {"language": "Python"}}],
                 "recommendation": {"option_name": "A"}}
        fake = fake_llm(hold_option, fixed)
        monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
        monkeypatch.setattr(tech_mod, "get_llm", lambda *a, **k: fake)

        out = tech_mod.tech_stack_node(state)

        assert fake.call_count == 2                            # HOLD option, retry
        assert out["tech_stack"]["status"] == "ok"
        assert out["tech_stack"]["content"]["options"][0]["layers"]["language"] == "Python"
        assert "Java" in str(fake.calls[1])                     # the violation was fed back

    def test_radar_tool_is_called_and_findings_reach_the_prompt(self, state, monkeypatch):
        # Real LLM-native tool-calling: the model requests check_tech_radar_status,
        # the tool runs for real against the actual tech_radar.md KB file, and its
        # finding must reach the final prompt before the recommendation is drafted.
        monkeypatch.setattr(tech_mod, "grounding_for", lambda *a, **k: GROUNDING)
        state["architecture"] = _artifact("architecture", {"components": [{"name": "API"}]})

        tool_call = [{"name": "check_tech_radar_status", "args": {"technology": "FastAPI"}, "id": "call_1"}]
        final = {"options": [{"name": "A"}], "recommendation": {"option_name": "A"}}
        fake = _ToolCallingFakeLLM(
            {"_tool_calls": tool_call},   # 1: model asks to check FastAPI
            {"_tool_calls": None},        # 2: model is done gathering facts
            final,                        # 3: invoke_json's final JSON answer
        )
        monkeypatch.setattr(tech_mod, "get_llm", lambda *a, **k: fake)
        monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)

        out = tech_mod.tech_stack_node(state)

        assert fake.call_count == 3
        assert out["tech_stack"]["content"]["options"][0]["name"] == "A"
        # the tool's real, KB-backed answer reached the prompt for the final call
        assert "FastAPI: ADOPT" in str(fake.calls[2])


# ── Revision behaviour (shared via specialist_base.finish) ────────────────────
class TestRevisionRun:

    def test_revision_run_routes_back_to_critic(self, state, fake_llm, monkeypatch):
        monkeypatch.setattr(arch_mod, "grounding_for", lambda *a, **k: GROUNDING)
        state["pending_revision"] = "architecture"
        state["revision_counts"] = {**state["revision_counts"], "architecture": 1}
        state["critic_scores"] = {"architecture": {
            "agent": "architecture", "verdict": "revise",
            "issues": ["NFR R002 is not mapped"], "overall": 0.5,
        }}
        fake = fake_llm({"context": "x", "components": [{"name": "API"}], "data_flows": [],
                         "nfr_mapping": [{"nfr_category": "performance", "requirement_ids": ["R002"]}],
                         "key_decisions": [], "mermaid": "g"})
        monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)

        out = arch_mod.solution_architect_node(state)

        assert out["current_step"] == "architecture_revised"
        assert out["current_stage"] == Stage.CRITIQUE
        assert out["pending_revision"] is None
        assert out["architecture"]["revision"] == 1
        assert "FIX THESE ISSUES" in str(fake.calls[0])
        assert "NFR R002 is not mapped" in str(fake.calls[0])


# ── Persistence ──────────────────────────────────────────────────────────────
def test_artifact_saved_to_disk(state, fake_llm, monkeypatch, tmp_path):
    monkeypatch.setattr(arch_mod, "grounding_for", lambda *a, **k: GROUNDING)
    fake = fake_llm({"context": "x", "components": [], "nfr_mapping": [], "key_decisions": []})
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
    arch_mod.solution_architect_node(state)
    saved = json.loads((tmp_path / "deliverables" / "architecture.json").read_text())
    assert saved["agent"] == "architecture"
    assert saved["brd_id"] == "BRD-S1"
