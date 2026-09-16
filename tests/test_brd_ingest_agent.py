"""
tests/test_brd_ingest_agent.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for agents/brd_ingest_agent.brd_ingest_node.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json

import pytest

import agents.brd_ingest_agent as mod
from orchestration.state import Stage, make_initial_state

BRD_TEXT = """# 1. Overview
Project Atlas modernizes the reporting stack for the analytics team.

# 2. Functional Requirements
The system must export reports as PDF. The system must email reports on a schedule.

# 3. Non-Functional Requirements
Report generation must finish within 60 seconds for a 100-page report.
"""


@pytest.fixture
def state(tmp_path, brd_framework_config):
    brd_framework_config["output"]["parsed_dir"] = str(tmp_path / "parsed")
    s = make_initial_state(
        brd_id="BRD-TEST-1",
        thread_id="t-1",
        framework_config={**brd_framework_config, **{"_llm_config": brd_framework_config["_llm_config"]}},
        brd_raw_text=BRD_TEXT,
    )
    return s


def test_happy_path(state, fake_llm, monkeypatch, tmp_path):
    llm = fake_llm(
        {"requirements": []},                                   # S001 Overview — no reqs
        {"requirements": [                                      # S002 Functional
            {"text": "The system must export reports as PDF.", "type": "functional", "priority": "must"},
            {"text": "The system must email reports on a schedule.", "type": "functional", "priority": "must"},
        ]},
        {"requirements": [                                      # S003 NFR
            {"text": "Report generation must finish within 60s for 100 pages.",
             "type": "non_functional", "nfr_category": "performance", "priority": "must"},
        ]},
        {"project_name": "Project Atlas", "stakeholders": ["Analytics Lead"]},  # metadata
    )
    monkeypatch.setattr(mod, "get_llm", lambda *a, **k: llm)

    out = mod.brd_ingest_node(state)

    assert out["current_stage"] == Stage.ORCHESTRATE
    assert out["current_step"] == "brd_ingest_complete"
    assert len(out["brd_sections"]) == 3
    assert len(out["requirements"]) == 3
    assert out["brd_metadata"]["project_name"] == "Project Atlas"

    parsed_file = tmp_path / "parsed" / "BRD-TEST-1_parsed.json"
    assert parsed_file.exists()
    saved = json.loads(parsed_file.read_text())
    assert saved["requirement_count"] == 3


def test_no_input_fails(state, monkeypatch):
    state["brd_raw_text"] = ""
    state["brd_path"] = ""
    out = mod.brd_ingest_node(state)
    assert out["current_stage"] == Stage.FAILED
    assert out["current_step"] == "brd_ingest_failed"
    assert any("No BRD content" in e for e in out["errors"])


def test_bad_path_fails(state, monkeypatch):
    state["brd_raw_text"] = ""
    state["brd_path"] = "data/sample_brds/nope.md"
    out = mod.brd_ingest_node(state)
    assert out["current_stage"] == Stage.FAILED
    assert any("Could not load BRD" in e for e in out["errors"])


def test_confidentiality_guardrail_redacts_before_any_llm_call(state, fake_llm, monkeypatch, tmp_path):
    # A real secret embedded in the BRD must never reach the LLM, and must not
    # be persisted to disk either — this is the whole point of redacting at
    # ingest, before section extraction or classification.
    secret = "AKIAIOSFODNN7EXAMPLE"
    state["brd_raw_text"] = BRD_TEXT + f"\nInfra note: our AWS key is {secret} — rotate quarterly.\n"

    llm = fake_llm(
        {"requirements": []}, {"requirements": []}, {"requirements": []}, {"requirements": []},
        {"project_name": "Project Atlas"},
    )
    monkeypatch.setattr(mod, "get_llm", lambda *a, **k: llm)

    out = mod.brd_ingest_node(state)

    assert secret not in out["brd_text"]
    assert "[REDACTED:AWS_ACCESS_KEY]" in out["brd_text"]
    assert out["confidentiality_notes"] == ["1 AWS access key redacted"]

    # the secret never reached the (fake) LLM in any classify/tag call
    assert not any(secret in str(call) for call in llm.calls)

    # nor does it land on disk
    parsed_file = tmp_path / "parsed" / "BRD-TEST-1_parsed.json"
    assert secret not in parsed_file.read_text()


def test_no_confidentiality_notes_when_nothing_sensitive(state, fake_llm, monkeypatch):
    llm = fake_llm(
        {"requirements": []}, {"requirements": []}, {"requirements": []},
        {"project_name": "Project Atlas"},
    )
    monkeypatch.setattr(mod, "get_llm", lambda *a, **k: llm)
    out = mod.brd_ingest_node(state)
    assert out["confidentiality_notes"] == []
