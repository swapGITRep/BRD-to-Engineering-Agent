"""
agents/assemble_agent.py
─────────────────────────────────────────────────────────────────────────────
LangGraph node: Assemble.

Compiles the five deliverables + Critic quality badges into a single Markdown
BRD response document (structure mirrors
knowledge_base/corpus/templates/brd_response_template.md) and writes it to
output/reports/<brd_id>_response.md.

Reads:  all deliverables, critic_scores, quality_badges, brd_metadata, brd_summary
Writes: state["brd_response_doc"], state["quality_badges"]["_overall"],
        state["current_stage"] = COMPLETE
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from orchestration.state import (
    SPECIALIST_AGENTS,
    BRDState,
    Stage,
    resolve_output_dir,
    revision_improvement,
)

logger = logging.getLogger(__name__)

_BADGE_ICON = {"green": "🟢", "amber": "🟡", "red": "🔴"}
_SECTIONS = [
    ("engineering_plan", "Engineering Plan"),
    ("schedule",         "Schedule & Estimates"),
    ("architecture",     "Solution Architecture"),
    ("poc_plan",         "Proof-of-Concept Plan"),
    ("tech_stack",       "Technology Stack Options"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Node
# ─────────────────────────────────────────────────────────────────────────────
def assemble_node(state: BRDState) -> Dict[str, Any]:
    logger.info("=" * 65)
    logger.info("📦 ASSEMBLE — compiling BRD response document")
    logger.info("=" * 65)

    brd_id   = state.get("brd_id", "BRD-UNKNOWN")
    metadata = state.get("brd_metadata", {})
    scores   = state.get("critic_scores", {})
    badges   = dict(state.get("quality_badges", {}))
    overall  = _rollup_badge(badges)
    confidentiality_notes = state.get("confidentiality_notes", [])

    out: List[str] = []
    out += [
        f"# BRD Response — {metadata.get('project_name') or brd_id}",
        "",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · BRD `{brd_id}` · "
        f"{len(state.get('requirements', []))} requirements · {len(state.get('brd_sections', []))} sections_",
        "",
    ]
    if confidentiality_notes:
        out += [
            f"> 🔒 **Confidentiality guardrail** — {'; '.join(confidentiality_notes)} before analysis. "
            "Redacted values are never sent to the model or stored anywhere.",
            "",
        ]
    out += [
        "## Executive Summary",
        "",
        state.get("brd_summary", "") or "_(no summary available)_",
        "",
        f"**Overall readiness: {_BADGE_ICON.get(overall, '⚪')} {overall.upper()}**",
        "",
        _scorecard(scores, badges),
    ]

    improvement = revision_improvement(state.get("score_history", {}))
    if improvement:
        out += ["", _revision_improvement_section(improvement, dict(_SECTIONS))]

    open_notes: List[str] = []
    for key, title in _SECTIONS:
        art = state.get(key)
        badge = badges.get(key, "—")
        icon = _BADGE_ICON.get(badge, "⚪")
        out += ["", "---", "", f"## {title} &nbsp;·&nbsp; {icon} {badge}", ""]

        if not art or art.get("status") != "ok":
            out.append("_Not produced — the responsible agent failed. See run errors._")
            continue

        out.append(_RENDERERS[key](art.get("content", {})))
        if art.get("citations"):
            out += ["", "_Grounding: " + ", ".join(f"`{c}`" for c in art["citations"]) + "_"]

        s = scores.get(key)
        if s and s.get("issues") and badge != "green":
            open_notes.append(f"**{title}** ({icon} {badge}):")
            open_notes += [f"- {i}" for i in s["issues"]]

    if open_notes:
        out += ["", "---", "", "## Open Critic Notes", ""] + open_notes

    doc = "\n".join(out).rstrip() + "\n"
    badges["_overall"] = overall
    _save(brd_id, state, doc)
    logger.info("✅ Assembled response doc (%d chars) — overall %s", len(doc), overall)

    return {
        "brd_response_doc": doc,
        "quality_badges":   badges,
        "current_stage":    Stage.COMPLETE,
        "current_step":     "assemble_complete",
        "errors":           state.get("errors", []),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Scorecard
# ─────────────────────────────────────────────────────────────────────────────
def _scorecard(scores: Dict[str, Any], badges: Dict[str, str]) -> str:
    header = ("| Deliverable | Badge | Overall | Complete | Consistent | Actionable | Grounded | Revs |\n"
              "| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    rows = []
    for key, title in _SECTIONS:
        s = scores.get(key)
        icon = _BADGE_ICON.get(badges.get(key, ""), "⚪")
        if s:
            rows.append(
                f"| {title} | {icon} {s['badge']} | {s['overall']:.2f} | {s['completeness']:.2f} | "
                f"{s['consistency']:.2f} | {s['actionability']:.2f} | {s['groundedness']:.2f} | "
                f"{s.get('scored_revision', 0)} |"
            )
        else:
            rows.append(f"| {title} | {icon} — | — | — | — | — | — | — |")
    return "## Quality Scorecard\n\n" + header + "\n" + "\n".join(rows)


def _revision_improvement_section(improvement: Dict[str, Dict[str, Any]], titles: Dict[str, str]) -> str:
    """The concrete before/after evidence the revision loop is meant to
    produce — one row per agent that was actually revised, not just a claim
    that the loop 'works'."""
    header = "| Deliverable | Revisions | Before | After | Change |\n| --- | :---: | :---: | :---: | :---: |"
    rows = []
    for key, delta in improvement.items():
        arrow = "📈" if delta["delta"] > 0 else ("📉" if delta["delta"] < 0 else "➡️")
        rows.append(
            f"| {titles.get(key, key)} | {delta['revisions']} | {delta['first_overall']:.2f} | "
            f"{delta['last_overall']:.2f} | {arrow} {delta['delta']:+.2f} |"
        )
    return "## Revision Improvement\n\n" + header + "\n" + "\n".join(rows)


def _rollup_badge(badges: Dict[str, str]) -> str:
    vals = [b for k, b in badges.items() if not k.startswith("_")]
    if not vals or "red" in vals:
        return "red"
    return "amber" if "amber" in vals else "green"


# ─────────────────────────────────────────────────────────────────────────────
# Markdown helpers
# ─────────────────────────────────────────────────────────────────────────────
def _lst(content: Dict[str, Any], key: str) -> List[Any]:
    v = content.get(key)
    return v if isinstance(v, list) else []


def _cell(v: Any) -> str:
    if isinstance(v, (list, tuple)):
        return ", ".join(_cell(x) for x in v) or "—"
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_cell(x)}" for k, x in v.items()) or "—"
    return str(v).replace("\n", " ").replace("|", "\\|") if v not in (None, "") else "—"


def _table(headers: List[str], rows: List[List[Any]]) -> str:
    if not rows:
        return "_(none)_"
    head = "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join("| " + " | ".join(_cell(c) for c in r) + " |" for r in rows)
    return head + "\n" + body


def _bullets(items: List[Any]) -> str:
    return "\n".join(f"- {_cell(i)}" for i in items) if items else "_(none)_"


# ─────────────────────────────────────────────────────────────────────────────
# Per-deliverable renderers
# ─────────────────────────────────────────────────────────────────────────────
def _render_engineering_plan(c: Dict[str, Any]) -> str:
    parts = ["### Phases", _table(
        ["Phase", "Objective", "Entry criteria", "Exit criteria", "Deliverables"],
        [[p.get("name"), p.get("objective"), p.get("entry_criteria"),
          p.get("exit_criteria"), p.get("deliverables")] for p in _lst(c, "phases")],
    )]
    parts += ["\n### Risk Register", _table(
        ["Risk", "Likelihood", "Impact", "Mitigation", "Owner", "Retire by"],
        [[r.get("risk"), r.get("likelihood"), r.get("impact"), r.get("mitigation"),
          r.get("owner"), r.get("retire_by_phase")] for r in _lst(c, "risks")],
    )]
    parts += ["\n### Milestones", _table(
        ["Milestone", "Target week", "Depends on"],
        [[m.get("name"), m.get("target_week"), m.get("depends_on")] for m in _lst(c, "milestones")],
    )]
    parts += ["\n### Team Composition", _table(
        ["Role", "Count", "Allocation %", "Phase"],
        [[t.get("role"), t.get("count"), t.get("allocation_pct"), t.get("phase")]
         for t in _lst(c, "team_composition")],
    )]
    if _lst(c, "requirement_coverage"):
        parts += ["\n### Requirement Coverage", _table(
            ["Requirement", "Phase"],
            [[r.get("req_id"), r.get("phase")] for r in _lst(c, "requirement_coverage")],
        )]
    parts += ["\n### Assumptions", _bullets(_lst(c, "assumptions")),
              "\n### Out of Scope", _bullets(_lst(c, "out_of_scope"))]
    return "\n".join(parts)


def _render_schedule(c: Dict[str, Any]) -> str:
    align = "✅ aligned to the plan's phases" if c.get("alignment_ok", True) else \
            f"⚠️ **not aligned** — {c.get('alignment_notes', 'see notes')}"
    parts = [align, "\n### Effort by Phase", _table(
        ["Phase", "Person-weeks", "Confidence"],
        [[e.get("phase"), e.get("person_weeks"), e.get("confidence")] for e in _lst(c, "phase_effort")],
    )]
    parts += ["\n### Timeline", _table(
        ["Phase", "Start week", "End week", "Parallel with"],
        [[t.get("phase"), t.get("start_week"), t.get("end_week"), t.get("parallel_with")]
         for t in _lst(c, "timeline")],
    )]
    parts += ["\n### Resource Allocation", _table(
        ["Role", "Phase", "Allocation %"],
        [[r.get("role"), r.get("phase"), r.get("allocation_pct")] for r in _lst(c, "resource_matrix")],
    )]
    cp = c.get("critical_path")
    parts.append("\n**Critical path:** " + (" → ".join(map(str, cp)) if isinstance(cp, list) and cp else "—"))
    parts.append(f"**Contingency:** {c.get('contingency_pct', '—')}%")
    tot = c.get("total_calendar_weeks", {})
    if isinstance(tot, dict) and tot:
        parts.append(
            f"**Total calendar weeks:** optimistic {tot.get('optimistic', '—')} · "
            f"likely {tot.get('likely', '—')} · pessimistic {tot.get('pessimistic', '—')}"
        )
    return "\n".join(parts)


def _render_architecture(c: Dict[str, Any]) -> str:
    parts = [c.get("context") or "_(no context provided)_"]
    parts += ["\n### Components", _table(
        ["Component", "Responsibility", "Area", "Interfaces"],
        [[x.get("name"), x.get("responsibility"), x.get("tech_area"), x.get("interfaces")]
         for x in _lst(c, "components")],
    )]
    parts += ["\n### Data Flows", _table(
        ["From", "To", "Data", "Protocol", "Mode"],
        [[f.get("from"), f.get("to"), f.get("data"), f.get("protocol"), f.get("mode")]
         for f in _lst(c, "data_flows")],
    )]
    if _lst(c, "integrations"):
        parts += ["\n### Integrations", _table(
            ["System", "Direction", "Method"],
            [[i.get("system"), i.get("direction"), i.get("method")] for i in _lst(c, "integrations")],
        )]
    parts += ["\n### NFR Mapping", _table(
        ["NFR", "Requirement IDs", "Tactic", "Verification"],
        [[m.get("nfr_category"), m.get("requirement_ids"), m.get("tactic"), m.get("verification")]
         for m in _lst(c, "nfr_mapping")],
    )]
    if _lst(c, "key_decisions"):
        parts += ["\n### Key Decisions"] + [
            f"- **{d.get('decision', '')}** — {d.get('rationale', '')}"
            + (f" _(rejected: {_cell(d.get('alternatives_rejected'))})_" if d.get("alternatives_rejected") else "")
            for d in _lst(c, "key_decisions")
        ]
    if c.get("mermaid"):
        from skills.mermaid_utils import sanitize_mermaid
        parts += ["\n### Diagram", "```mermaid", sanitize_mermaid(str(c["mermaid"])), "```"]
    return "\n".join(parts)


def _render_poc(c: Dict[str, Any]) -> str:
    parts = [f"**Goal:** {c.get('poc_goal') or '—'}"]
    if _lst(c, "hypotheses"):
        parts += ["\n### Hypotheses", _bullets(_lst(c, "hypotheses"))]
    parts += ["\n### In Scope", _bullets(_lst(c, "in_scope")),
              "\n### Out of Scope", _bullets(_lst(c, "out_of_scope"))]
    parts += ["\n### Modules", _table(
        ["Module", "Maps to component", "Boundary", "Interfaces", "Collaborators"],
        [[m.get("name"), m.get("maps_to_component"), m.get("boundary"),
          m.get("interfaces"), m.get("collaborators")] for m in _lst(c, "modules")],
    )]
    parts += ["\n### Success Criteria", _table(
        ["Metric", "Threshold", "Measurement method"],
        [[s.get("metric"), s.get("threshold"), s.get("measurement_method")]
         for s in _lst(c, "success_criteria")],
    )]
    parts.append(f"\n**Duration:** {c.get('duration_weeks', '—')} weeks · "
                 f"resources: {_cell(c.get('resources'))}")
    parts += ["\n### Exit Decision Matrix", _table(
        ["Outcome", "Decision"],
        [[e.get("outcome"), e.get("decision")] for e in _lst(c, "exit_decision_matrix")],
    )]
    return "\n".join(parts)


def _render_tech_stack(c: Dict[str, Any]) -> str:
    parts: List[str] = []
    for opt in _lst(c, "options"):
        parts.append(f"### Option: {opt.get('name', '?')}"
                     + (f" — _{opt['shape']}_" if opt.get("shape") else ""))
        layers = opt.get("layers", {})
        if isinstance(layers, dict) and layers:
            parts += ["", _table(["Layer", "Choice"], [[k, v] for k, v in layers.items()])]
        sc = opt.get("scores", {})
        if isinstance(sc, dict) and sc:
            parts += ["", _table(["Dimension", "Score (1–5)"], [[k, v] for k, v in sc.items()])]
        if opt.get("tradeoffs"):
            parts.append(f"\n_Trade-offs:_ {opt['tradeoffs']}")
        if opt.get("best_when"):
            parts.append(f"_Best when:_ {opt['best_when']}")
        parts.append("")
    rec = c.get("recommendation", {})
    if isinstance(rec, dict) and rec:
        parts += ["### Recommendation",
                  f"**{rec.get('option_name', '—')}** — {rec.get('justification', '')}"
                  + (f"\n\n_Dominant constraint:_ {rec['dominant_constraint']}"
                     if rec.get("dominant_constraint") else "")]
    return "\n".join(parts) or "_(no options produced)_"


_RENDERERS: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "engineering_plan": _render_engineering_plan,
    "schedule":         _render_schedule,
    "architecture":     _render_architecture,
    "poc_plan":         _render_poc,
    "tech_stack":       _render_tech_stack,
}


# ─────────────────────────────────────────────────────────────────────────────
def _save(brd_id: str, state: BRDState, doc: str) -> None:
    out_dir = resolve_output_dir(state.get("framework_config", {}).get("output", {}).get("report_dir", "output/reports"))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{brd_id}_response.md"
    path.write_text(doc, encoding="utf-8")
    (out_dir / f"{brd_id}_deliverables.json").write_text(
        json.dumps({a: state.get(a) for a in SPECIALIST_AGENTS}, indent=2), encoding="utf-8"
    )
    # A small index record — lets a History view list/filter/reload past runs
    # without re-parsing the full deliverables bundle for every listed run.
    manifest = {
        "brd_id":            brd_id,
        "thread_id":         state.get("thread_id", ""),
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "project_name":      state.get("brd_metadata", {}).get("project_name") or "",
        "brd_summary":       state.get("brd_summary", ""),
        "section_count":     len(state.get("brd_sections", [])),
        "requirement_count": len(state.get("requirements", [])),
        "critic_scores":     state.get("critic_scores", {}),
        "quality_badges":    {**state.get("quality_badges", {}), "_overall": _rollup_badge(state.get("quality_badges", {}))},
        "revision_counts":   state.get("revision_counts", {}),
        "revision_improvement": revision_improvement(state.get("score_history", {})),
        "confidentiality_notes": state.get("confidentiality_notes", []),
        "errors":            state.get("errors", []),
    }
    (out_dir / f"{brd_id}_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("💾 Saved %s", path)
