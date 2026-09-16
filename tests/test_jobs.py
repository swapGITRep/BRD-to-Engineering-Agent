"""
tests/test_jobs.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for streamlit_app/jobs.py — the background job runner. No
Streamlit and no real LLM calls: orchestration.langgraph_workflow.run_pipeline
is monkeypatched (jobs._run imports it lazily, so patching the module
attribute before start_job() is picked up correctly).
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import time

import pytest

import streamlit_app.jobs as jobs


def _wait_until(predicate, timeout=2.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture(autouse=True)
def _jobs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    return tmp_path / "jobs"


def _patch_run_pipeline(monkeypatch, fn):
    monkeypatch.setattr("orchestration.langgraph_workflow.run_pipeline", fn)


# ── start_job ────────────────────────────────────────────────────────────────
class TestStartJob:

    def test_creates_a_running_record_immediately(self, monkeypatch):
        # Block inside run_pipeline so we can inspect the record before it finishes.
        started = {"ok": False}

        def slow_pipeline(**kwargs):
            started["ok"] = True
            time.sleep(0.2)
            return {"brd_id": kwargs["brd_id"], "current_stage": "complete", "quality_badges": {}}

        _patch_run_pipeline(monkeypatch, slow_pipeline)
        job_id = jobs.start_job(brd_text="hello", brd_id="BRD-1")

        job = jobs.get_job(job_id)
        assert job["status"] == "running"
        assert job["brd_id"] == "BRD-1"
        assert job["thread_id"]
        assert job["started_at"]
        assert job["finished_at"] is None

        assert _wait_until(lambda: started["ok"])  # let the thread actually run
        # Drain the thread fully before the test (and its JOBS_DIR monkeypatch)
        # tears down — otherwise its completion write lands in the real dir.
        assert _wait_until(lambda: jobs.get_job(job_id)["status"] != "running")

    def test_unknown_job_returns_none(self):
        assert jobs.get_job("nope") is None


# ── completion ───────────────────────────────────────────────────────────────
class TestJobCompletion:

    def test_successful_run_is_recorded_as_complete(self, monkeypatch):
        def fake_pipeline(**kwargs):
            return {
                "brd_id": kwargs["brd_id"], "current_stage": "complete",
                "brd_metadata": {"project_name": "Demo"},
                "quality_badges": {"_overall": "green"},
            }

        _patch_run_pipeline(monkeypatch, fake_pipeline)
        job_id = jobs.start_job(brd_text="hello", brd_id="BRD-OK")

        assert _wait_until(lambda: jobs.get_job(job_id)["status"] != "running")
        job = jobs.get_job(job_id)
        assert job["status"] == "complete"
        assert job["brd_id"] == "BRD-OK"
        assert job["overall_badge"] == "green"
        assert job["error"] is None
        assert job["finished_at"]
        assert job["started_at"]  # preserved from the initial write

    def test_pipeline_returning_failed_stage_is_recorded_as_failed(self, monkeypatch):
        def fake_pipeline(**kwargs):
            return {"brd_id": kwargs["brd_id"], "current_stage": "failed",
                    "quality_badges": {}, "brd_metadata": {}}

        _patch_run_pipeline(monkeypatch, fake_pipeline)
        job_id = jobs.start_job(brd_text="", brd_id="BRD-BAD")

        assert _wait_until(lambda: jobs.get_job(job_id)["status"] != "running")
        job = jobs.get_job(job_id)
        assert job["status"] == "failed"
        assert "ingestion" in job["error"].lower()

    def test_exception_in_pipeline_is_caught_and_recorded(self, monkeypatch):
        def boom(**kwargs):
            raise RuntimeError("kaboom")

        _patch_run_pipeline(monkeypatch, boom)
        job_id = jobs.start_job(brd_text="x", brd_id="BRD-CRASH")

        assert _wait_until(lambda: jobs.get_job(job_id)["status"] != "running")
        job = jobs.get_job(job_id)
        assert job["status"] == "failed"
        assert "kaboom" in job["error"]

    def test_thread_crash_does_not_raise_in_caller(self, monkeypatch):
        """start_job() itself must never raise, even if the job explodes."""
        def boom(**kwargs):
            raise ValueError("nope")

        _patch_run_pipeline(monkeypatch, boom)
        job_id = jobs.start_job(brd_text="x")  # should not raise
        assert _wait_until(lambda: jobs.get_job(job_id)["status"] != "running")


# ── latest_job ───────────────────────────────────────────────────────────────
class TestLatestJob:

    def test_returns_none_when_no_jobs(self):
        assert jobs.latest_job() is None

    def test_returns_most_recently_started(self, monkeypatch, tmp_path):
        def fake_pipeline(**kwargs):
            time.sleep(0.05)
            return {"brd_id": kwargs["brd_id"], "current_stage": "complete", "quality_badges": {}}

        _patch_run_pipeline(monkeypatch, fake_pipeline)
        first_id = jobs.start_job(brd_text="a", brd_id="FIRST")
        time.sleep(0.2)  # comfortably exceed filesystem mtime resolution under load
        second_id = jobs.start_job(brd_text="b", brd_id="SECOND")

        latest = jobs.latest_job()
        assert latest["job_id"] == second_id
        assert latest["brd_id"] == "SECOND"

        # Drain both background threads before the JOBS_DIR monkeypatch reverts —
        # otherwise their completion writes land in the real output/jobs/.
        assert _wait_until(lambda: jobs.get_job(first_id)["status"] != "running")
        assert _wait_until(lambda: jobs.get_job(second_id)["status"] != "running")


# ── live_stage ───────────────────────────────────────────────────────────────
class TestLiveStage:

    def test_uses_checkpoint_state_while_running(self, monkeypatch):
        monkeypatch.setattr(
            "orchestration.langgraph_workflow.get_thread_state",
            lambda thread_id: {"current_stage": "architecture"},
        )
        job = {"status": "running", "thread_id": "t-1", "current_stage": "ingest"}
        assert jobs.live_stage(job) == "architecture"

    def test_falls_back_to_stored_stage_on_lookup_failure(self, monkeypatch):
        def boom(thread_id):
            raise RuntimeError("db locked")

        monkeypatch.setattr("orchestration.langgraph_workflow.get_thread_state", boom)
        job = {"status": "running", "thread_id": "t-1", "current_stage": "schedule"}
        assert jobs.live_stage(job) == "schedule"

    def test_not_consulted_once_job_is_done(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            "orchestration.langgraph_workflow.get_thread_state",
            lambda thread_id: called.append(1) or {"current_stage": "poc"},
        )
        job = {"status": "complete", "thread_id": "t-1", "current_stage": "complete"}
        assert jobs.live_stage(job) == "complete"
        assert called == []
