"""
agents/brd_ingest_agent.py
─────────────────────────────────────────────────────────────────────────────
LangGraph node: BRD Ingestion & Parsing (Capability 1).

Reads:  state["brd_path"] or state["brd_raw_text"], state["framework_config"]
Writes: state["brd_text"], state["brd_sections"], state["requirements"],
        state["brd_metadata"], state["confidentiality_notes"],
        state["current_stage"], state["current_step"]

Persists output/parsed/<brd_id>_parsed.json.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from orchestration.state import BRDState, Stage, resolve_output_dir
from skills.brd_parser import (
    classify_requirements,
    extract_sections,
    load_document,
    tag_metadata,
)
from skills.confidentiality import scan_and_redact
from skills.llm_factory import get_llm

logger = logging.getLogger(__name__)


def brd_ingest_node(state: BRDState) -> Dict[str, Any]:
    logger.info("=" * 65)
    logger.info("📥 BRD INGEST — parsing, section extraction, classification")
    logger.info("=" * 65)

    framework_config = state.get("framework_config", {})
    llm_config = framework_config.get("_llm_config", {})

    # ── 1. Resolve raw text ──────────────────────────────────────────────
    raw_text = state.get("brd_raw_text", "") or ""
    brd_path = state.get("brd_path", "") or ""
    if not raw_text and brd_path:
        try:
            raw_text = load_document(brd_path)
        except Exception as e:  # noqa: BLE001
            return _fail(state, f"Could not load BRD '{brd_path}': {e}")
    if not raw_text.strip():
        return _fail(state, "No BRD content provided (brd_path and brd_raw_text both empty).")

    # ── 1a. Confidentiality guardrail ─────────────────────────────────────
    # Redact before anything else touches this text — every LLM call below,
    # every downstream agent's grounding/generation, and everything persisted
    # to disk all read the result of this, not the original. One choke point
    # for every entry path (UI upload, paste, sample, CLI, the eval harness).
    raw_text, confidentiality_notes = scan_and_redact(raw_text)
    if confidentiality_notes:
        logger.warning("🔒 Confidentiality guardrail: %s", "; ".join(confidentiality_notes))

    # ── 2. Sections ──────────────────────────────────────────────────────
    sections = extract_sections(raw_text)
    min_sections = framework_config.get("ingestion", {}).get("min_sections", 1)
    if len(sections) < min_sections:
        return _fail(state, f"Only {len(sections)} section(s) found; need >= {min_sections}.")
    logger.info("📑 Extracted %d section(s)", len(sections))

    # ── 3. Classify + tag (LLM) ──────────────────────────────────────────
    llm = get_llm("brd_ingest", llm_config)
    requirements = classify_requirements(sections, llm)
    metadata = tag_metadata(sections, llm)
    logger.info(
        "✅ %d requirement(s) | project: %s",
        len(requirements), metadata.get("project_name") or "—",
    )

    # ── 4. Persist ───────────────────────────────────────────────────────
    _persist(state.get("brd_id", "BRD-UNKNOWN"), framework_config, sections, requirements,
             metadata, confidentiality_notes)

    return {
        "brd_text":               raw_text,
        "brd_sections":           sections,
        "requirements":           requirements,
        "brd_metadata":           metadata,
        "confidentiality_notes":  confidentiality_notes,
        "current_stage":          Stage.ORCHESTRATE,
        "current_step":           "brd_ingest_complete",
        "errors":                 state.get("errors", []),
        "messages": state.get("messages", []) + [
            {"role": "assistant",
             "content": f"Ingested BRD: {len(sections)} sections, {len(requirements)} requirements"}
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _persist(
    brd_id: str,
    framework_config: Dict[str, Any],
    sections: list,
    requirements: list,
    metadata: Dict[str, Any],
    confidentiality_notes: list,
) -> None:
    out_dir = resolve_output_dir(framework_config.get("output", {}).get("parsed_dir", "output/parsed"))
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "brd_id": brd_id,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "section_count": len(sections),
        "requirement_count": len(requirements),
        "confidentiality_notes": confidentiality_notes,
        "sections": sections,
        "requirements": requirements,
        "metadata": metadata,
    }
    path = out_dir / f"{brd_id}_parsed.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("💾 Saved %s", path)


def _fail(state: BRDState, error_msg: str) -> Dict[str, Any]:
    logger.error("❌ BRD ingest: %s", error_msg)
    return {
        "errors":        state.get("errors", []) + [f"BRDIngest: {error_msg}"],
        "current_stage": Stage.FAILED,
        "current_step":  "brd_ingest_failed",
    }
