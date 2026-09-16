"""
tests/test_critic_agent.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for agents/critic_agent.critic_node.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import pytest

import agents.critic_agent as mod
import agents.specialist_base as base
from orchestration.state import SPECIALIST_AGENTS, Stage, make_initial_state, revision_improvement

PASS = {"completeness": 0.9, "consistency": 0.9, "actionability": 0.9, "groundedness": 0.9, "issues": []}
FAIL = {"completeness": 0.4, "consistency": 0.5, "actionability": 0.5, "groundedness": 0.5,
        "issues": ["fix the thing"]}


def _art(agent, content=None, revision=0, status="ok"):
    return {"agent": agent, "content": content or {"x": 1}, "citations": ["KB:doc.md#0"],
            "revision": revision, "self_review": None, "status": status}


@pytest.fixture
def state(brd_framework_config):
    brd_framework_config["rubric_weights"] = {
        "completeness": 0.30, "consistency": 0.25, "actionability": 0.25, "groundedness": 0.20,
    }
    brd_framework_config["badges"] = {"green": 0.80, "amber": 0.60}
    brd_framework_config["required_sections"] = {
        "engineering_plan": ["phases", "risks"],
    }
    brd_framework_config["_llm_config"]["revision"] = {
        "max_revisions_per_agent": 2, "min_pass_score": 0.75,
    }
    s = make_initial_state("BRD-C1", "t-c1", brd_framework_config)
    s["brd_summary"] = "summary"
    s["requirements"] = [{"req_id": "R001", "text": "do X"}]
    for a in SPECIALIST_AGENTS:
        s[a] = _art(a, content={"phases": [1], "risks": [1]} if a == "engineering_plan" else {"y": 2})
    return s


@pytest.fixture(autouse=True)
def _no_real_retriever(monkeypatch):
    class _R:
        def resolve_citations(self, refs):
            return {r: "supporting KB text" for r in refs}
    monkeypatch.setattr(mod, "get_retriever", lambda *a, **k: _R())


# ── Happy path ───────────────────────────────────────────────────────────────
def test_all_pass_goes_to_assemble(state, fake_llm, monkeypatch):
    fake = fake_llm(*([PASS] * 5))
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
    out = mod.critic_node(state)
    assert out["pending_revision"] is None
    assert out["current_stage"] == Stage.ASSEMBLE
    assert out["current_step"] == "critic_complete"
    assert set(out["quality_badges"]) == set(SPECIALIST_AGENTS)
    assert all(b == "green" for b in out["quality_badges"].values())
    assert all(out["critic_scores"][a]["scored_revision"] == 0 for a in SPECIALIST_AGENTS)


def test_overall_is_weighted_sum(state, fake_llm, monkeypatch):
    s = {"completeness": 1.0, "consistency": 0.0, "actionability": 1.0, "groundedness": 0.0, "issues": []}
    fake = fake_llm(*([s] * 5))
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
    out = mod.critic_node(state)
    # 1*.30 + 0*.25 + 1*.25 + 0*.20 = 0.55
    assert out["critic_scores"]["schedule"]["overall"] == pytest.approx(0.55)
    assert out["critic_scores"]["schedule"]["verdict"] == "revise"   # any dim < 0.5


# ── Revision routing ─────────────────────────────────────────────────────────
def test_low_score_routes_back(state, fake_llm, monkeypatch):
    # engineering_plan passes, schedule fails, rest pass
    fake = fake_llm(PASS, FAIL, PASS, PASS, PASS)
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
    out = mod.critic_node(state)
    assert out["pending_revision"] == "schedule"
    assert out["revision_counts"]["schedule"] == 1
    assert out["current_stage"] == Stage.CRITIQUE
    assert out["current_step"] == "critic_revise:schedule"


def test_earliest_failing_agent_is_chosen(state, fake_llm, monkeypatch):
    fake = fake_llm(FAIL, FAIL, PASS, PASS, PASS)
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
    out = mod.critic_node(state)
    assert out["pending_revision"] == "engineering_plan"
    assert out["revision_counts"]["engineering_plan"] == 1
    assert out["revision_counts"]["schedule"] == 0


def test_maxed_agent_is_not_rerouted(state, fake_llm, monkeypatch):
    state["revision_counts"]["schedule"] = 2       # already at max
    fake = fake_llm(PASS, FAIL, PASS, PASS, PASS)
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
    out = mod.critic_node(state)
    assert out["pending_revision"] is None
    assert out["current_stage"] == Stage.ASSEMBLE
    assert out["quality_badges"]["schedule"] in ("amber", "red")


# ── Schema validation on the Critic's own scoring reply ──────────────────────
def test_scoring_schema_violation_is_retried_once_then_succeeds(state, fake_llm, monkeypatch):
    # A dimension that can't coerce to float is a real schema violation (not
    # just a missing key, which CriticDimensions defaults) — must be retried
    # with the problem fed back, the same as the five specialists already are.
    bad = {"completeness": "excellent", "consistency": 0.8, "actionability": 0.8,
           "groundedness": 0.8, "issues": []}
    fixed = {"completeness": 0.8, "consistency": 0.8, "actionability": 0.8,
             "groundedness": 0.8, "issues": []}
    fake = fake_llm(bad, fixed, PASS, PASS, PASS, PASS)   # engineering_plan: bad+retry, then 4 more
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
    out = mod.critic_node(state)
    assert fake.call_count == 6
    assert out["critic_scores"]["engineering_plan"]["completeness"] == pytest.approx(0.8)


# ── Before/after revision history ─────────────────────────────────────────────
def test_score_history_tracks_before_and_after_a_revision(state, fake_llm, monkeypatch):
    # Pass 1: schedule fails and is routed back for revision. critic_scores
    # only ever holds the latest score — score_history is the only place a
    # before/after delta can be read from, so it must capture the failing
    # score here, before anything is revised.
    fake1 = fake_llm(PASS, FAIL, PASS, PASS, PASS)
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake1)
    out1 = mod.critic_node(state)

    assert out1["pending_revision"] == "schedule"
    # FAIL @ weights .30/.25/.25/.20 = .4*.30 + .5*.25 + .5*.25 + .5*.20 = 0.47
    assert [round(s["overall"], 2) for s in out1["score_history"]["schedule"]] == [0.47]

    # Pass 2: the specialist "re-ran" (revision bumped, current_step marks the
    # re-entry) and now scores well. score_history must now hold BOTH scores,
    # in order, and _improvement_summary must report the real delta.
    state2 = {**state, **out1}
    state2["schedule"] = _art("schedule", content={"y": 2}, revision=1)
    state2["current_step"] = "schedule_revised"

    fake2 = fake_llm(*([PASS] * 5))   # "_revised" step forces a full rescore
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake2)
    out2 = mod.critic_node(state2)

    hist = out2["score_history"]["schedule"]
    assert len(hist) == 2
    assert round(hist[0]["overall"], 2) == 0.47
    assert round(hist[1]["overall"], 2) == 0.9

    # The "_revised" step force-rescores every agent (existing, established
    # behavior — see test_revised_step_forces_full_rescore), giving all five
    # a second score_history entry. But only schedule's artifact revision
    # actually changed (0 -> 1); the other four were re-scored with the same
    # content (scored_revision stays 0 both times) — that's LLM scoring
    # jitter on unchanged content, not improvement, and revision_improvement
    # must exclude it, not report a misleading ~0 delta as if it were real.
    improvement = revision_improvement(out2["score_history"])
    assert improvement["schedule"]["revisions"] == 1
    assert improvement["schedule"]["first_overall"] == pytest.approx(0.47)
    assert improvement["schedule"]["last_overall"] == pytest.approx(0.9)
    assert improvement["schedule"]["delta"] == pytest.approx(0.43)
    assert set(improvement) == {"schedule"}


# ── Deterministic overrides ──────────────────────────────────────────────────
def test_missing_required_section_caps_completeness(state, fake_llm, monkeypatch):
    state["engineering_plan"]["content"] = {"phases": [1]}     # 'risks' missing
    fake = fake_llm(*([PASS] * 5))
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
    out = mod.critic_node(state)
    sc = out["critic_scores"]["engineering_plan"]
    assert sc["completeness"] <= 0.45
    assert any("risks" in i for i in sc["issues"])
    assert sc["verdict"] == "revise"


def test_no_citations_caps_groundedness(state, fake_llm, monkeypatch):
    for a in SPECIALIST_AGENTS:
        state[a]["citations"] = []
    fake = fake_llm(*([PASS] * 5))
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
    out = mod.critic_node(state)
    sc = out["critic_scores"]["architecture"]
    assert sc["groundedness"] <= 0.5
    assert any("citation" in i.lower() for i in sc["issues"])


# ── Dirty tracking ───────────────────────────────────────────────────────────
def test_second_pass_only_rescores_changed_artifact(state, fake_llm, monkeypatch):
    fake = fake_llm(*([PASS] * 5))
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
    first = mod.critic_node(state)
    # simulate: architecture revised, everything else untouched
    state["critic_scores"] = first["critic_scores"]
    state["quality_badges"] = first["quality_badges"]
    state["revision_counts"] = first["revision_counts"]
    state["architecture"]["revision"] = 1
    state["current_step"] = "orchestration_complete"          # not a *_revised step

    fake = fake_llm(PASS)
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
    second = mod.critic_node(state)
    assert fake.call_count == 1                                # only architecture
    assert second["critic_scores"]["architecture"]["scored_revision"] == 1


def test_revised_step_forces_full_rescore(state, fake_llm, monkeypatch):
    fake = fake_llm(*([PASS] * 5))
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
    first = mod.critic_node(state)
    state["critic_scores"] = first["critic_scores"]
    state["schedule"]["revision"] = 1
    state["current_step"] = "schedule_revised"

    fake = fake_llm(*([PASS] * 5))
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
    mod.critic_node(state)
    assert fake.call_count == 5


# ── Failed artifact ──────────────────────────────────────────────────────────
def test_failed_artifact_gets_red_and_revise_without_llm(state, fake_llm, monkeypatch):
    state["architecture"] = _art("architecture", status="failed")
    fake = fake_llm(PASS, PASS, PASS, PASS)      # 4 ok artifacts, architecture not scored by LLM
    monkeypatch.setattr(base, "get_llm", lambda *a, **k: fake)
    out = mod.critic_node(state)
    assert fake.call_count == 4
    assert out["quality_badges"]["architecture"] == "red"
    assert out["pending_revision"] == "architecture"
