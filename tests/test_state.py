"""
tests/test_state.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for the BRD pipeline state factory and helpers.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import pytest

from orchestration.state import (
    SPECIALIST_AGENTS,
    Badge,
    Stage,
    badge_for_score,
    empty_artifact,
    make_initial_state,
    resolve_output_dir,
    revision_improvement,
)


FRAMEWORK_CONFIG = {
    "badges": {"green": 0.80, "amber": 0.60},
    "rubric_weights": {
        "completeness": 0.30,
        "consistency": 0.25,
        "actionability": 0.25,
        "groundedness": 0.20,
    },
}


# ── make_initial_state ───────────────────────────────────────────────────────
class TestMakeInitialState:

    def test_returns_all_expected_keys(self):
        state = make_initial_state(
            brd_id="BRD-001",
            thread_id="thread-abc",
            framework_config=FRAMEWORK_CONFIG,
            brd_path="data/sample_brds/example.md",
        )
        expected = {
            "thread_id", "brd_id", "brd_path", "brd_raw_text", "framework_config",
            "brd_text", "brd_sections", "requirements", "brd_metadata", "confidentiality_notes",
            "brd_summary", "agent_plan", "routing_map",
            "engineering_plan", "schedule", "architecture", "poc_plan", "tech_stack",
            "critic_scores", "score_history", "revision_counts", "pending_revision",
            "brd_response_doc", "quality_badges",
            "current_stage", "current_step", "errors", "messages",
        }
        assert set(state.keys()) == expected

    def test_identity_fields_are_passed_through(self):
        state = make_initial_state(
            brd_id="BRD-002",
            thread_id="t-2",
            framework_config=FRAMEWORK_CONFIG,
            brd_raw_text="As an EM I want ...",
        )
        assert state["brd_id"] == "BRD-002"
        assert state["thread_id"] == "t-2"
        assert state["brd_raw_text"] == "As an EM I want ..."
        assert state["brd_path"] == ""

    def test_starts_at_ingest_stage(self):
        state = make_initial_state("BRD-003", "t-3", FRAMEWORK_CONFIG)
        assert state["current_stage"] == Stage.INGEST
        assert state["current_step"] == "start"

    def test_deliverables_start_none(self):
        state = make_initial_state("BRD-004", "t-4", FRAMEWORK_CONFIG)
        for key in ("engineering_plan", "schedule", "architecture", "poc_plan", "tech_stack"):
            assert state[key] is None

    def test_revision_counts_seeded_for_every_specialist(self):
        state = make_initial_state("BRD-005", "t-5", FRAMEWORK_CONFIG)
        assert state["revision_counts"] == {a: 0 for a in SPECIALIST_AGENTS}
        assert state["pending_revision"] is None

    def test_collections_start_empty(self):
        state = make_initial_state("BRD-006", "t-6", FRAMEWORK_CONFIG)
        assert state["brd_sections"] == []
        assert state["requirements"] == []
        assert state["errors"] == []
        assert state["messages"] == []
        assert state["critic_scores"] == {}
        assert state["quality_badges"] == {}

    def test_nested_mutable_defaults_are_not_shared_between_instances(self):
        a = make_initial_state("BRD-A", "t-a", FRAMEWORK_CONFIG)
        b = make_initial_state("BRD-B", "t-b", FRAMEWORK_CONFIG)
        a["revision_counts"]["schedule"] = 2
        a["errors"].append("boom")
        assert b["revision_counts"]["schedule"] == 0
        assert b["errors"] == []


# ── empty_artifact ───────────────────────────────────────────────────────────
class TestEmptyArtifact:

    def test_shape(self):
        art = empty_artifact("architecture")
        assert art["agent"] == "architecture"
        assert art["content"] == {}
        assert art["citations"] == []
        assert art["revision"] == 0
        assert art["self_review"] is None
        assert art["status"] == "pending"


# ── badge_for_score ──────────────────────────────────────────────────────────
class TestBadgeForScore:

    @pytest.mark.parametrize(
        "score,expected",
        [
            (0.95, Badge.GREEN),
            (0.80, Badge.GREEN),
            (0.79, Badge.AMBER),
            (0.60, Badge.AMBER),
            (0.59, Badge.RED),
            (0.0, Badge.RED),
        ],
    )
    def test_thresholds(self, score, expected):
        assert badge_for_score(score, FRAMEWORK_CONFIG) == expected

    def test_falls_back_to_defaults_when_config_missing(self):
        assert badge_for_score(0.85, {}) == Badge.GREEN
        assert badge_for_score(0.65, {}) == Badge.AMBER
        assert badge_for_score(0.40, {}) == Badge.RED


# ── revision_improvement ─────────────────────────────────────────────────────
def _s(overall, scored_revision):
    return {"agent": "x", "completeness": overall, "consistency": overall,
            "actionability": overall, "groundedness": overall, "overall": overall,
            "verdict": "pass", "issues": [], "badge": "green", "scored_revision": scored_revision}


class TestRevisionImprovement:

    def test_single_score_is_not_a_revision(self):
        # Scored exactly once — there is no "before" to compare against.
        assert revision_improvement({"schedule": [_s(0.8, 0)]}) == {}

    def test_genuine_revision_is_reported(self):
        history = {"architecture": [_s(0.64, 0), _s(0.78, 1)]}
        out = revision_improvement(history)
        assert out == {"architecture": {
            "revisions": 1, "first_overall": 0.64, "last_overall": 0.78, "delta": pytest.approx(0.14),
        }}

    def test_rescore_of_unchanged_content_is_excluded(self):
        # Two scores, same scored_revision both times: the Critic's force-
        # rescore of every agent when a *different* agent gets revised (see
        # agents/critic_agent.py::_dirty_agents) re-scores unchanged content
        # and produces ordinary LLM scoring jitter — that must not be
        # reported as "improvement", or the metric stops meaning anything.
        history = {"poc_plan": [_s(0.94, 0), _s(0.91, 0)]}
        assert revision_improvement(history) == {}

    def test_only_genuinely_revised_agents_appear_alongside_rescored_ones(self):
        history = {
            "architecture": [_s(0.64, 0), _s(0.78, 1)],   # real revision
            "poc_plan":      [_s(0.94, 0), _s(0.91, 0)],   # rescore jitter only
            "tech_stack":    [_s(1.00, 0)],                # scored once
        }
        assert set(revision_improvement(history)) == {"architecture"}

    def test_multiple_revisions_counted_correctly(self):
        history = {"schedule": [_s(0.40, 0), _s(0.60, 1), _s(0.85, 2)]}
        out = revision_improvement(history)
        assert out["schedule"]["revisions"] == 2
        assert out["schedule"]["first_overall"] == 0.40
        assert out["schedule"]["last_overall"] == 0.85
        assert out["schedule"]["delta"] == pytest.approx(0.45)

    def test_regression_is_reported_as_a_negative_delta(self):
        # A revision can make a score worse — that is real information, not
        # something to hide by only reporting positive deltas.
        history = {"schedule": [_s(0.80, 0), _s(0.70, 1)]}
        out = revision_improvement(history)
        assert out["schedule"]["delta"] == pytest.approx(-0.10)


# ── resolve_output_dir ────────────────────────────────────────────────────────
class TestResolveOutputDir:

    def test_relative_path_anchored_to_project_root_not_cwd(self, monkeypatch, tmp_path):
        # Live-caught: scripts/run_eval.py run from inside scripts/ made this
        # resolve against scripts/ instead of the real project root, silently
        # writing a whole parallel output/ tree the UI never looks at.
        monkeypatch.chdir(tmp_path)
        result = resolve_output_dir("output/reports")
        assert str(result) != str(tmp_path / "output/reports")
        assert result.is_absolute()
        assert result.parts[-2:] == ("output", "reports")

    def test_absolute_path_passes_through_unchanged(self, tmp_path):
        abs_path = tmp_path / "custom" / "reports"
        assert resolve_output_dir(str(abs_path)) == abs_path
