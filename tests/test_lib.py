"""
tests/test_lib.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for streamlit_app/lib.py's brd_id derivation helpers and other
pure (non-Streamlit-session) functions.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json

import streamlit_app.lib as lib
from streamlit_app.lib import _derive_brd_id, _derive_brd_id_from_text, list_eval_runs, rag_chunk_config


# ── _derive_brd_id (filename/label -> id) ─────────────────────────────────────
class TestDeriveBrdId:

    def test_strips_extension_and_slugifies(self):
        assert _derive_brd_id("payments_reconciliation_brd.md") == "PAYMENTS_RECONCILIATION_BRD"

    def test_non_alnum_runs_collapse_to_one_underscore(self):
        assert _derive_brd_id("My BRD (v2) - final!!.txt") == "MY_BRD_V2_FINAL"

    def test_empty_name_falls_back_to_BRD(self):
        assert _derive_brd_id("") == "BRD"


# ── _derive_brd_id_from_text (pasted text -> id) ──────────────────────────────
class TestDeriveBrdIdFromText:

    def test_strips_the_boilerplate_title_prefix(self):
        # This project's house style opens every BRD with the same
        # "Business Requirements Document —" prefix; the id should reflect
        # the distinctive project title, not that shared boilerplate.
        text = "# Business Requirements Document — Bank Statement Auto-Reconciliation Assistant\n\n## 1. Overview\n..."
        assert _derive_brd_id_from_text(text) == "BANK_STATEMENT_AUTO_RECONCILIATION_ASSISTANT"

    def test_plain_heading_without_boilerplate(self):
        assert _derive_brd_id_from_text("# Widget Tracker Revamp\n...") == "WIDGET_TRACKER_REVAMP"

    def test_leading_blank_lines_are_skipped(self):
        text = "\n   \n\n# Trimmed Leading Blank Lines\nbody"
        assert _derive_brd_id_from_text(text) == "TRIMMED_LEADING_BLANK_LINES"

    def test_no_heading_falls_back_to_first_line(self):
        # Better than nothing, and still far more useful than a random id --
        # not every pasted BRD starts with a markdown heading.
        text = "Project Atlas needs a new reporting pipeline.\n\nMore detail below."
        assert _derive_brd_id_from_text(text) == "PROJECT_ATLAS_NEEDS_A_NEW_REPORTING_PIPELINE"

    def test_empty_text_returns_empty_string_not_a_fixed_fallback(self):
        # Empty (not "BRD") on purpose: run_pipeline()'s own random
        # `BRD-<hex>` fallback should still kick in for text with nothing
        # to derive from, exactly as it did before this helper existed --
        # colliding every such run onto a fixed "BRD" id would be worse.
        assert _derive_brd_id_from_text("") == ""
        assert _derive_brd_id_from_text("   \n  \n") == ""

    def test_heading_level_does_not_matter(self):
        assert _derive_brd_id_from_text("### Deep Heading\nbody") == "DEEP_HEADING"

    def test_result_is_capped_at_48_chars(self):
        long_title = "# " + " ".join(f"word{i}" for i in range(30))
        assert len(_derive_brd_id_from_text(long_title)) <= 48


# ── rag_chunk_config (mirrors RagRetriever's own chunk sizing) ────────────────
class TestRagChunkConfig:

    def test_reads_real_config_values(self):
        # config/llm_config.yaml's rag: block is the same file RagRetriever
        # itself reads -- this proves the Knowledge Base page's chunk preview
        # can't silently drift from what the retriever actually chunks with.
        assert rag_chunk_config() == (800, 100)


# ── list_eval_runs (backed by output/eval/<run_id>/summary.json) ─────────────
def _write_summary(eval_dir, run_id: str, **fields) -> None:
    d = eval_dir / run_id
    d.mkdir(parents=True)
    (d / "summary.json").write_text(json.dumps({"total": 1, "passed": 1, "results": [], **fields}))


class TestListEvalRuns:

    def test_no_eval_dir_returns_empty_list(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lib, "EVAL_DIR", tmp_path / "does_not_exist")
        assert list_eval_runs() == []

    def test_lists_runs_newest_first(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lib, "EVAL_DIR", tmp_path)
        _write_summary(tmp_path, "20260916T094223Z")
        _write_summary(tmp_path, "20260920T083346Z")
        runs = list_eval_runs()
        assert [r["run_id"] for r in runs] == ["20260920T083346Z", "20260916T094223Z"]

    def test_run_id_defaults_to_folder_name_when_missing(self, tmp_path, monkeypatch):
        # run_eval.py's own summary.json always sets "run_id", but the loader
        # shouldn't depend on that -- a hand-edited or older file should still
        # be identifiable by its folder name.
        monkeypatch.setattr(lib, "EVAL_DIR", tmp_path)
        d = tmp_path / "20260101T000000Z"
        d.mkdir()
        (d / "summary.json").write_text(json.dumps({"total": 1, "passed": 1, "results": []}))
        runs = list_eval_runs()
        assert runs[0]["run_id"] == "20260101T000000Z"

    def test_corrupt_summary_is_skipped_not_fatal(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lib, "EVAL_DIR", tmp_path)
        bad = tmp_path / "20260101T000000Z"
        bad.mkdir()
        (bad / "summary.json").write_text("{not valid json")
        _write_summary(tmp_path, "20260920T083346Z")
        runs = list_eval_runs()
        assert [r["run_id"] for r in runs] == ["20260920T083346Z"]
