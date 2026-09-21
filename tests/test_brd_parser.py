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
        # Section A fails twice (the reply and its one retry), so it is
        # dropped; section B is unaffected.
        secs = extract_sections("# 1. A\nLong enough text here to be classified please.\n"
                                "# 2. B\nAnother sufficiently long section of text here.")
        llm = fake_llm("not json at all", "still not json",
                       {"requirements": [{"text": "Ok.", "type": "functional"}]})
        reqs = classify_requirements(secs, llm)
        assert len(reqs) == 1
        assert reqs[0]["section_id"] == "S002"
        assert llm.call_count == 3

    def test_schema_violation_is_retried_once_with_the_problem_fed_back(self, fake_llm):
        # `requirements` as a string is valid JSON but the wrong shape — it
        # used to reach `.get(...)` unchecked. Now it is a schema failure.
        secs = extract_sections("# 1. Stuff\nThis section has enough text to be classified.")
        llm = fake_llm(
            {"requirements": "the system must do X"},
            {"requirements": [{"text": "The system must do X.", "type": "functional"}]},
        )
        reqs = classify_requirements(secs, llm)
        assert [r["text"] for r in reqs] == ["The system must do X."]
        assert llm.call_count == 2
        feedback = llm.calls[1][-1].content
        assert "did not match the required schema" in feedback

    def test_top_level_json_array_is_retried_not_a_crash(self, fake_llm):
        # A bare JSON array parses fine, then used to blow up on `.get`.
        secs = extract_sections("# 1. Stuff\nThis section has enough text to be classified.")
        llm = fake_llm([{"text": "X."}],
                       {"requirements": [{"text": "X.", "type": "functional"}]})
        reqs = classify_requirements(secs, llm)
        assert len(reqs) == 1
        assert llm.call_count == 2

    def test_requirement_missing_text_is_retried(self, fake_llm):
        secs = extract_sections("# 1. Stuff\nThis section has enough text to be classified.")
        llm = fake_llm(
            {"requirements": [{"type": "functional", "priority": "must"}]},
            {"requirements": [{"text": "Do X.", "type": "functional", "priority": "must"}]},
        )
        reqs = classify_requirements(secs, llm)
        assert [r["text"] for r in reqs] == ["Do X."]
        assert llm.call_count == 2

    def test_valid_reply_costs_no_retry_and_tolerates_extra_fields(self, fake_llm):
        secs = extract_sections("# 1. Stuff\nThis section has enough text to be classified.")
        llm = fake_llm({"requirements": [
            {"text": "Do X.", "type": "Functional", "priority": "MUST", "rationale": "extra"},
        ]})
        reqs = classify_requirements(secs, llm)
        assert reqs[0]["type"] == "functional" and reqs[0]["priority"] == "must"
        assert llm.call_count == 1

    def test_nfr_category_in_type_field_maps_to_non_functional(self, fake_llm):
        # Seen live on gpt-4.1-mini: type="security". That used to be
        # silently relabelled "functional", losing the NFR classification.
        secs = extract_sections("# 1. Stuff\nThis section has enough text to be classified.")
        llm = fake_llm({"requirements": [
            {"text": "Encrypt data at rest.", "type": "security", "priority": "must"},
            {"text": "Respond in 1s.", "type": "Performance"},
        ]})
        reqs = classify_requirements(secs, llm)
        assert [(r["type"], r["nfr_category"]) for r in reqs] == [
            ("non_functional", "security"), ("non_functional", "performance"),
        ]
        assert llm.call_count == 1                     # deterministic — no retry

    def test_explicit_nfr_category_wins_over_the_one_in_type(self, fake_llm):
        secs = extract_sections("# 1. Stuff\nThis section has enough text to be classified.")
        llm = fake_llm({"requirements": [
            {"text": "Audit every access.", "type": "security", "nfr_category": "compliance"},
        ]})
        reqs = classify_requirements(secs, llm)
        assert (reqs[0]["type"], reqs[0]["nfr_category"]) == ("non_functional", "compliance")

    def test_genuinely_unknown_type_still_falls_back_and_warns(self, fake_llm, caplog):
        secs = extract_sections("# 1. Stuff\nThis section has enough text to be classified.")
        llm = fake_llm({"requirements": [{"text": "Do X.", "type": "banana"}]})
        with caplog.at_level("WARNING", logger="skills.brd_parser"):
            reqs = classify_requirements(secs, llm)
        assert reqs[0]["type"] == "functional" and reqs[0]["nfr_category"] is None
        assert "unrecognised requirement type 'banana'" in caplog.text

    def test_value_coercion_is_no_longer_silent(self, fake_llm, caplog):
        secs = extract_sections("# 1. Stuff\nThis section has enough text to be classified.")
        llm = fake_llm({"requirements": [{"text": "Do X.", "type": "banana", "priority": "urgent"}]})
        with caplog.at_level("WARNING", logger="skills.brd_parser"):
            classify_requirements(secs, llm)
        assert "unrecognised requirement type 'banana'" in caplog.text
        assert "unrecognised priority 'urgent'" in caplog.text


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
        llm = fake_llm("garbage", "still garbage")     # the reply and its one retry
        md = tag_metadata(secs, llm)
        assert md["project_name"] == ""
        assert md["stakeholders"] == []

    def test_wrong_container_type_is_retried_once(self, fake_llm):
        # stakeholders as a bare string used to pass straight through.
        secs = extract_sections("# Overview\nProject Phoenix for the payments team.")
        llm = fake_llm(
            {"project_name": "Phoenix", "stakeholders": "VP Finance"},
            {"project_name": "Phoenix", "stakeholders": ["VP Finance"]},
        )
        md = tag_metadata(secs, llm)
        assert md["stakeholders"] == ["VP Finance"]
        assert llm.call_count == 2

    def test_null_fields_mean_absent_and_cost_no_retry(self, fake_llm):
        secs = extract_sections("# Overview\nSome text.")
        llm = fake_llm({"project_name": None, "stakeholders": None, "glossary": None})
        md = tag_metadata(secs, llm)
        assert md["project_name"] == ""
        assert md["stakeholders"] == [] and md["glossary"] == []
        assert llm.call_count == 1

    def test_structured_items_are_kept(self, fake_llm):
        secs = extract_sections("# Overview\nSome text.")
        llm = fake_llm({"target_dates": [{"label": "go-live", "date": "Q3"}],
                        "glossary": [{"term": "PSP", "definition": "payment provider"}]})
        md = tag_metadata(secs, llm)
        assert md["target_dates"] == [{"label": "go-live", "date": "Q3"}]
        assert md["glossary"][0]["term"] == "PSP"
