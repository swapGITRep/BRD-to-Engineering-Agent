"""
orchestration/state.py
─────────────────────────────────────────────────────────────────────────────
Central shared state for the BRD analysis multi-agent pipeline.

Flow:
    ingest → orchestrate → engineering_plan → schedule → architecture
           → poc → tech_stack → critique ─(revise)→ <failing agent>
                                         └(pass)──► assemble → complete

State is persisted via a LangGraph SqliteSaver checkpointer, keyed by thread_id.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from typing_extensions import TypedDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent  # orchestration/ -> project root


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────
class Stage(str, Enum):
    """Ordered pipeline stages."""
    INGEST       = "ingest"
    ORCHESTRATE  = "orchestrate"
    PLAN         = "engineering_plan"
    SCHEDULE     = "schedule"
    ARCHITECTURE = "architecture"
    POC          = "poc"
    TECH_STACK   = "tech_stack"
    CRITIQUE     = "critique"
    ASSEMBLE     = "assemble"
    COMPLETE     = "complete"
    FAILED       = "failed"


class RequirementType(str, Enum):
    FUNCTIONAL     = "functional"
    NON_FUNCTIONAL = "non_functional"
    CONSTRAINT     = "constraint"
    ASSUMPTION     = "assumption"
    OUT_OF_SCOPE   = "out_of_scope"


class Priority(str, Enum):
    MUST = "must"
    SHOULD = "should"
    COULD = "could"
    WONT = "wont"


class Verdict(str, Enum):
    PASS   = "pass"
    REVISE = "revise"


class Badge(str, Enum):
    GREEN = "green"
    AMBER = "amber"
    RED   = "red"


class ArtifactStatus(str, Enum):
    OK      = "ok"
    FAILED  = "failed"
    PENDING = "pending"


# The five specialist deliverables, in graph order. Used as the canonical list
# of agents the Critic scores and the revision router can route back to.
SPECIALIST_AGENTS: List[str] = [
    "engineering_plan",
    "schedule",
    "architecture",
    "poc_plan",
    "tech_stack",
]


# ─────────────────────────────────────────────────────────────────────────────
# Sub-models
# ─────────────────────────────────────────────────────────────────────────────
class BRDSection(TypedDict):
    """A single heading-delimited section extracted from the BRD."""
    section_id:  str
    title:       str
    level:       int
    raw_text:    str
    page_range:  str


class Requirement(TypedDict):
    """A single classified requirement extracted from a BRD section."""
    req_id:         str
    section_id:     str
    text:           str
    type:           str            # RequirementType value
    nfr_category:   Optional[str]  # performance | security | scalability | availability | compliance | usability
    priority:       str            # Priority value
    ambiguity_flag: bool


class AgentArtifact(TypedDict):
    """The output envelope every specialist agent returns."""
    agent:       str
    content:     Dict[str, Any]         # the structured deliverable
    citations:   List[str]              # KB refs used (e.g. "KB:architecture_patterns.md#3")
    revision:    int                    # 0 on first pass, incremented per revision
    self_review: Optional[Dict[str, Any]]  # Reflection notes (engineering_plan only)
    status:      str                    # ArtifactStatus value


class CriticScore(TypedDict):
    """Critic evaluation of a single agent artifact."""
    agent:           str
    completeness:    float
    consistency:     float
    actionability:   float
    groundedness:    float
    overall:         float
    verdict:         str        # Verdict value
    issues:          List[str]
    badge:           str        # Badge value
    scored_revision: int        # artifact.revision this score was computed against


# ─────────────────────────────────────────────────────────────────────────────
# Main state
# ─────────────────────────────────────────────────────────────────────────────
class BRDState(TypedDict):
    """Central shared state for all LangGraph nodes."""

    # ── Checkpointing ─────────────────────────────────────────────────────
    thread_id: str

    # ── Input ─────────────────────────────────────────────────────────────
    brd_id:           str
    brd_path:         str            # local path or blob URI ("" if raw text supplied)
    brd_raw_text:     str            # raw text when no file path is available
    framework_config: Dict[str, Any] # merged brd_config + llm_config

    # ── Ingestion & Parsing (Capability 1) ────────────────────────────────
    brd_text:      str
    brd_sections:  List[BRDSection]
    requirements:  List[Requirement]
    brd_metadata:  Dict[str, Any]
    confidentiality_notes: List[str]  # e.g. "2 email address(es) redacted" — never the values

    # ── Orchestrator ──────────────────────────────────────────────────────
    brd_summary:  str                       # 2-3 sentence summary (RAG queries + report)
    agent_plan:   List[str]                 # ordered specialist agent names to run
    routing_map:  Dict[str, List[str]]      # agent name → [section_id, ...]

    # ── Deliverables (Capability 3) ───────────────────────────────────────
    engineering_plan: Optional[AgentArtifact]
    schedule:         Optional[AgentArtifact]
    architecture:     Optional[AgentArtifact]
    poc_plan:         Optional[AgentArtifact]
    tech_stack:       Optional[AgentArtifact]

    # ── Validation & Evaluation (Capability 4) ────────────────────────────
    critic_scores:    Dict[str, CriticScore]        # agent → latest CriticScore
    score_history:    Dict[str, List[CriticScore]]  # agent → every score, in order — the
                                                      # before/after trail a single overwritten
                                                      # critic_scores entry can't show
    revision_counts:  Dict[str, int]          # agent → revisions performed
    pending_revision: Optional[str]           # agent name to re-run, or None

    # ── Output ────────────────────────────────────────────────────────────
    brd_response_doc: str                     # assembled markdown deliverable
    quality_badges:   Dict[str, str]          # agent → Badge value

    # ── Workflow control ──────────────────────────────────────────────────
    current_stage: str                        # Stage value
    current_step:  str                        # fine-grained step name
    errors:        List[str]                  # global error accumulator
    messages:      List[Dict[str, Any]]       # LLM conversation history for retries


# ─────────────────────────────────────────────────────────────────────────────
# State factory
# ─────────────────────────────────────────────────────────────────────────────
def make_initial_state(
    brd_id: str,
    thread_id: str,
    framework_config: Dict[str, Any],
    brd_path: str = "",
    brd_raw_text: str = "",
) -> BRDState:
    """Return a fresh BRDState for a new pipeline run."""
    return BRDState(
        thread_id=thread_id,
        brd_id=brd_id,
        brd_path=brd_path,
        brd_raw_text=brd_raw_text,
        framework_config=framework_config,
        brd_text="",
        brd_sections=[],
        requirements=[],
        brd_metadata={},
        confidentiality_notes=[],
        brd_summary="",
        agent_plan=[],
        routing_map={},
        engineering_plan=None,
        schedule=None,
        architecture=None,
        poc_plan=None,
        tech_stack=None,
        critic_scores={},
        score_history={},
        revision_counts={agent: 0 for agent in SPECIALIST_AGENTS},
        pending_revision=None,
        brd_response_doc="",
        quality_badges={},
        current_stage=Stage.INGEST,
        current_step="start",
        errors=[],
        messages=[],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def resolve_output_dir(configured: str) -> Path:
    """Anchor a configured output path (config/brd_config.yaml's output:
    block -- "output/parsed", "output/deliverables", "output/reports") to
    the project root, not the current process's cwd. Live-caught: running
    scripts/run_eval.py from inside scripts/ silently wrote a whole parallel
    output tree at scripts/output/ instead of the real output/ the Streamlit
    UI's Run History reads from -- every completed run "succeeded" with no
    error, it just wasn't visible anywhere. An already-absolute path (as
    Azure's deployment can set) passes through unchanged."""
    p = Path(configured)
    return p if p.is_absolute() else _PROJECT_ROOT / p


def empty_artifact(agent: str) -> AgentArtifact:
    """Return a blank, pending AgentArtifact envelope for the given agent."""
    return AgentArtifact(
        agent=agent,
        content={},
        citations=[],
        revision=0,
        self_review=None,
        status=ArtifactStatus.PENDING,
    )


def badge_for_score(overall: float, framework_config: Dict[str, Any]) -> str:
    """Map an overall Critic score to a quality badge using configured thresholds."""
    thresholds = framework_config.get("badges", {})
    green = float(thresholds.get("green", 0.80))
    amber = float(thresholds.get("amber", 0.60))
    if overall >= green:
        return Badge.GREEN
    if overall >= amber:
        return Badge.AMBER
    return Badge.RED


def revision_improvement(history: Dict[str, List[CriticScore]]) -> Dict[str, Dict[str, Any]]:
    """For every agent that was actually revised, the score before its first
    revision vs. its final score — the concrete before/after evidence the
    revision loop is meant to produce. Shared by critic_agent.py (which logs
    it) and assemble_agent.py (which renders it in the delivered document) so
    there is exactly one definition of what "improvement" means here.

    "Actually revised" means the artifact's own revision number changed
    between its first and last score, not merely that it was scored more
    than once: when one agent gets revised, current_step ending in "_revised"
    forces every agent to be re-scored on the next Critic pass (see
    _dirty_agents), even ones whose content never changed. Live-verified:
    that force-rescore produces small (+-0.01-0.04) same-content scoring
    jitter for the untouched agents — real signal, but not "improvement" —
    while the one agent genuinely revised showed scored_revision 0 -> 1
    alongside a real, larger delta. Filtering on scored_revision changing is
    what tells those two cases apart."""
    out: Dict[str, Dict[str, Any]] = {}
    for agent, entries in history.items():
        if len(entries) < 2:
            continue
        if entries[0].get("scored_revision") == entries[-1].get("scored_revision"):
            continue
        out[agent] = {
            "revisions":     len(entries) - 1,
            "first_overall": entries[0]["overall"],
            "last_overall":  entries[-1]["overall"],
            "delta":         round(entries[-1]["overall"] - entries[0]["overall"], 4),
        }
    return out
