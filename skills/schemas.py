"""
skills/schemas.py
─────────────────────────────────────────────────────────────────────────────
Pydantic models mirroring each specialist agent's JSON schema — until now
declared only as prompt text (see each agent's _SCHEMA/_SYSTEM block), with
nothing checking that a reply that parses as JSON actually has the right
shape. invoke_json() validates against these after parsing; a missing
required field or wrong type is now a validation failure retried the same
way a JSON syntax error already is (see specialist_base.invoke_json),
instead of silently reaching finish() with a malformed artifact.

Deliberately lenient beyond the few identifying fields each item needs to be
useful (a Phase needs a name; a full description is not required to exist to
be worth keeping) — the goal is catching real structural breakage, not
policing prompt-adherence the LLM already mostly gets right. `extra = allow`
throughout so an LLM enriching its answer with an extra field never fails.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="allow")


# ── Engineering Plan ──────────────────────────────────────────────────────
class Phase(_Lenient):
    name: str
    objective: str = ""
    entry_criteria: List[str] = Field(default_factory=list)
    exit_criteria: List[str] = Field(default_factory=list)
    deliverables: List[str] = Field(default_factory=list)


class Risk(_Lenient):
    risk: str
    likelihood: str = ""
    impact: str = ""
    mitigation: str = ""
    owner: str = ""
    retire_by_phase: str = ""


class Milestone(_Lenient):
    name: str
    target_week: float = 0
    depends_on: List[str] = Field(default_factory=list)


class TeamRole(_Lenient):
    role: str
    count: float = 0
    allocation_pct: float = 0
    phase: str = ""


class RequirementCoverage(_Lenient):
    req_id: str
    phase: str = ""


class EngineeringPlan(_Lenient):
    phases: List[Phase]
    risks: List[Risk] = Field(default_factory=list)
    milestones: List[Milestone] = Field(default_factory=list)
    team_composition: List[TeamRole] = Field(default_factory=list)
    requirement_coverage: List[RequirementCoverage] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    out_of_scope: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)


# ── Schedule ──────────────────────────────────────────────────────────────
class PhaseEffort(_Lenient):
    phase: str
    person_weeks: float = 0
    confidence: str = ""


class TimelineEntry(_Lenient):
    phase: str
    start_week: float = 0
    end_week: float = 0
    parallel_with: List[str] = Field(default_factory=list)


class ResourceMatrixEntry(_Lenient):
    role: str
    phase: str = ""
    allocation_pct: float = 0


class CalendarWeeks(_Lenient):
    optimistic: float = 0
    likely: float = 0
    pessimistic: float = 0


class Schedule(_Lenient):
    alignment_ok: bool = True
    alignment_notes: str = ""
    phase_effort: List[PhaseEffort]
    timeline: List[TimelineEntry] = Field(default_factory=list)
    resource_matrix: List[ResourceMatrixEntry] = Field(default_factory=list)
    critical_path: List[str] = Field(default_factory=list)
    contingency_pct: float = 0
    total_calendar_weeks: CalendarWeeks = Field(default_factory=CalendarWeeks)
    citations: List[str] = Field(default_factory=list)


# ── Solution Architecture ──────────────────────────────────────────────────
class Component(_Lenient):
    name: str
    responsibility: str = ""
    tech_area: str = ""
    interfaces: List[str] = Field(default_factory=list)


class DataFlow(_Lenient):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    from_: str = Field(default="", alias="from")
    to: str = ""
    data: str = ""
    protocol: str = ""
    mode: str = ""


class Integration(_Lenient):
    system: str
    direction: str = ""
    method: str = ""


class NfrMapping(_Lenient):
    nfr_category: str = ""
    requirement_ids: List[str] = Field(default_factory=list)
    tactic: str = ""
    verification: str = ""


class KeyDecision(_Lenient):
    decision: str
    rationale: str = ""
    alternatives_rejected: List[str] = Field(default_factory=list)


class SolutionArchitecture(_Lenient):
    context: str = ""
    components: List[Component]
    data_flows: List[DataFlow] = Field(default_factory=list)
    integrations: List[Integration] = Field(default_factory=list)
    nfr_mapping: List[NfrMapping] = Field(default_factory=list)
    key_decisions: List[KeyDecision] = Field(default_factory=list)
    mermaid: str = ""
    citations: List[str] = Field(default_factory=list)


# ── PoC Plan ─────────────────────────────────────────────────────────────
class PocModule(_Lenient):
    name: str
    maps_to_component: str = ""
    boundary: str = ""
    interfaces: List[str] = Field(default_factory=list)
    collaborators: str = ""


class SuccessCriterion(_Lenient):
    metric: str
    threshold: str = ""
    measurement_method: str = ""


class Resource(_Lenient):
    role: str
    count: float = 0


class ExitDecision(_Lenient):
    outcome: str
    decision: str = ""


class PocPlan(_Lenient):
    poc_goal: str
    hypotheses: List[str] = Field(default_factory=list)
    in_scope: List[str] = Field(default_factory=list)
    out_of_scope: List[str] = Field(default_factory=list)
    modules: List[PocModule]
    success_criteria: List[SuccessCriterion] = Field(default_factory=list)
    duration_weeks: float = 0
    resources: List[Resource] = Field(default_factory=list)
    exit_decision_matrix: List[ExitDecision] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)


# ── Tech Stack ───────────────────────────────────────────────────────────
class StackLayers(_Lenient):
    language: str = ""
    framework: str = ""
    datastore: str = ""
    infra: str = ""
    ci_cd: str = ""
    observability: str = ""


class StackScores(_Lenient):
    scalability: float = 0
    team_familiarity: float = 0
    integration_risk: float = 0
    cost: float = 0
    time_to_market: float = 0


class StackOption(_Lenient):
    name: str
    shape: str = ""
    layers: StackLayers = Field(default_factory=StackLayers)
    scores: StackScores = Field(default_factory=StackScores)
    tradeoffs: str = ""
    best_when: str = ""


class Recommendation(_Lenient):
    option_name: str = ""
    justification: str = ""
    dominant_constraint: str = ""


class TechStack(_Lenient):
    options: List[StackOption]
    recommendation: Recommendation = Field(default_factory=Recommendation)
    citations: List[str] = Field(default_factory=list)


# ── Critic — dimension scores (agents/critic_agent.py) ──────────────────────
# Every field defaults to 0.5 (the same neutral fallback critic_agent.py used
# before this schema existed), so a response missing a dimension degrades to
# "uncertain," not a validation failure over something recoverable.
class CriticDimensions(_Lenient):
    completeness: float = 0.5
    consistency: float = 0.5
    actionability: float = 0.5
    groundedness: float = 0.5
    issues: List[str] = Field(default_factory=list)


# ── Engineering Plan Reflection (agents/engineering_plan_agent.py::_reflect) ─
class ReflectionReview(_Lenient):
    issues: List[str] = Field(default_factory=list)
    verdict: str = "ok"


# ── BRD ingestion (skills/brd_parser.py) ──────────────────────────────────────
# What these check is *structure*, not prompt-adherence: the reply is an object
# whose `requirements` is a list of objects each carrying a string `text`, and
# whose metadata fields are the container types downstream code indexes into.
# Before this, a reply shaped wrong (a top-level JSON array, `requirements` as
# a string, a non-object item) reached `.get(...)` unchecked and could crash
# ingest outright. Enum values (`type`, `priority`, `nfr_category`) are
# deliberately left as plain strings: brd_parser._coerce_requirement
# normalizes those deterministically and logs when it had to correct one.
class RequirementItem(_Lenient):
    text: str
    type: str = "functional"
    nfr_category: Optional[str] = None
    priority: str = "should"
    ambiguity_flag: bool = False


class RequirementsResponse(_Lenient):
    requirements: List[RequirementItem] = Field(default_factory=list)


class TargetDate(_Lenient):
    label: str = ""
    date: str = ""


class GlossaryEntry(_Lenient):
    term: str = ""
    definition: str = ""


class ProjectMetadata(_Lenient):
    project_name: str = ""
    stakeholders: List[str] = Field(default_factory=list)
    target_dates: List[TargetDate] = Field(default_factory=list)
    business_goals: List[str] = Field(default_factory=list)
    success_metrics: List[str] = Field(default_factory=list)
    glossary: List[GlossaryEntry] = Field(default_factory=list)
    referenced_systems: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _null_means_absent(cls, data: Any) -> Any:
        # The prompt asks for an empty list/string when a field is absent;
        # models often emit null instead. That's absent, not malformed —
        # let the defaults apply.
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


# agent_key (as used in state/output/deliverables) -> its schema. Lets tooling
# (e.g. scripts/verify_deliverables.py) look up the right model generically
# instead of hardcoding a parallel if/elif per agent.
AGENT_SCHEMAS = {
    "engineering_plan": EngineeringPlan,
    "schedule": Schedule,
    "architecture": SolutionArchitecture,
    "poc_plan": PocPlan,
    "tech_stack": TechStack,
}
