"""
tests/test_brd_parser.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for skills/brd_parser.py.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from pathlib import Path

import pytest

from skills.brd_parser import (
    classify_requirements,
    extract_sections,
    load_document,
    tag_metadata,
)

SAMPLE_DIR = Path(__file__).parent.parent / "data" / "sample_brds"


# ── load_document ────────────────────────────────────────────────────────────
class TestLoadDocument:

    def test_reads_markdown(self):
        text = load_document(str(SAMPLE_DIR / "payments_reconciliation_brd.md"))
        assert "Payments Reconciliation Platform" in text

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_document("data/sample_brds/does_not_exist.md")

    def test_unsupported_extension_raises(self, tmp_path):
        p = tmp_path / "brd.rtf"
        p.write_text("x")
        with pytest.raises(ValueError):
            load_document(str(p))


# ── extract_sections ─────────────────────────────────────────────────────────
class TestExtractSections:

    def test_markdown_headings(self):
        text = "# Title\nintro line\n\n## 1. Overview\nbody a\n\n## 2. Goals\nbody b"
        secs = extract_sections(text)
        titles = [s["title"] for s in secs]
        assert titles == ["Title", "1. Overview", "2. Goals"]
        assert secs[1]["raw_text"] == "body a"

    def test_numbered_heading_levels(self):
        text = "1. Introduction\ntop\n2.1 Scope\nnested\n2.1.3 Detail\ndeep"
        secs = extract_sections(text)
        assert [s["level"] for s in secs] == [1, 2, 3]

    def test_allcaps_heading(self):
        text = "BUSINESS REQUIREMENTS DOCUMENT\n\nCUSTOMER PORTAL REVAMP\n\nsome text here"
        secs = extract_sections(text)
        assert secs[0]["title"] == "Business Requirements Document"
        assert secs[1]["title"] == "Customer Portal Revamp"

    def test_preamble_captured_before_first_heading(self):
        text = "This document describes the project scope.\n\n# 1. Goals\nreduce cost"
        secs = extract_sections(text)
        assert secs[0]["title"] == "Preamble"
        assert "project scope" in secs[0]["raw_text"]

    def test_section_ids_sequential(self):
        secs = extract_sections("# A\nx\n# B\ny\n# C\nz")
        assert [s["section_id"] for s in secs] == ["S001", "S002", "S003"]

    def test_sample_brd_extracts_multiple_sections(self):
        text = load_document(str(SAMPLE_DIR / "payments_reconciliation_brd.md"))
        secs = extract_sections(text)
        assert len(secs) >= 6
        assert any("Functional Requirements" in s["title"] for s in secs)


# ── classify_requirements ────────────────────────────────────────────────────
class TestClassifyRequirements:

    def test_flattens_and_assigns_ids(self, fake_llm):
        secs = extract_sections("# 1. Functional\nThe system must do X. The system must do Y.\n"
                                "# 2. NFR\nThe system must be fast.")
        llm = fake_llm(
            {"requirements": [
                {"text": "The system must do X.", "type": "functional", "priority": "must"},
                {"text": "The system must do Y.", "type": "functional", "priority": "must"},
            ]},
            {"requirements": [
                {"text": "The system must respond within 1s.", "type": "non_functional",
                 "nfr_category": "performance", "priority": "must", "ambiguity_flag": False},
            ]},
        )
        reqs = classify_requirements(secs, llm)
        assert [r["req_id"] for r in reqs] == ["R001", "R002", "R003"]
        assert reqs[0]["section_id"] == "S001"
        assert reqs[2]["section_id"] == "S002"
        assert reqs[2]["nfr_category"] == "performance"

    def test_coerces_bad_fields(self, fake_llm):
        secs = extract_sections("# 1. Stuff\nThis section has enough text to be classified.")
        llm = fake_llm({"requirements": [
            {"text": "Do the thing.", "type": "banana", "priority": "urgent",
             "nfr_category": "performance"},   # type not non_functional → nfr dropped
        ]})
        reqs = classify_requirements(secs, llm)
        assert reqs[0]["type"] == "functional"
        assert reqs[0]["priority"] == "should"
        assert reqs[0]["nfr_category"] is None

    def test_skips_short_sections(self, fake_llm):
        secs = extract_sections("# Tiny\nshort\n# Real\nThis section is long enough to classify.")
        llm = fake_llm({"requirements": [{"text": "A requirement.", "type": "functional"}]})
        reqs = classify_requirements(secs, llm)
        assert len(reqs) == 1
        assert llm.call_count == 1          # short section not sent

    def test_bad_json_from_one_section_is_skipped(self, fake_llm):
        secs = extract_sections("# 1. A\nLong enough text here to be classified please.\n"
                                "# 2. B\nAnother sufficiently long section of text here.")
        llm = fake_llm("not json at all", {"requirements": [{"text": "Ok.", "type": "functional"}]})
        reqs = classify_requirements(secs, llm)
        assert len(reqs) == 1


# ── tag_metadata ─────────────────────────────────────────────────────────────
class TestTagMetadata:

    def test_returns_normalized_keys(self, fake_llm):
        secs = extract_sections("# Overview\nProject Phoenix for the payments team.")
        llm = fake_llm({
            "project_name": "Project Phoenix",
            "stakeholders": ["VP Finance"],
            "business_goals": ["cut effort"],
        })
        md = tag_metadata(secs, llm)
        assert md["project_name"] == "Project Phoenix"
        assert md["stakeholders"] == ["VP Finance"]
        assert md["glossary"] == []            # missing key → default
        assert set(md) == {
            "project_name", "stakeholders", "target_dates", "business_goals",
            "success_metrics", "glossary", "referenced_systems",
        }

    def test_llm_failure_returns_empty_shell(self, fake_llm):
        secs = extract_sections("# Overview\nSome text.")
        llm = fake_llm("garbage")
        md = tag_metadata(secs, llm)
        assert md["project_name"] == ""
        assert md["stakeholders"] == []
