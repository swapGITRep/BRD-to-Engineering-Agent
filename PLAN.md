# IK_BRD_Dev_Agent — Implementation Plan

> Transform the current repo (an exact clone of the ETL agent skeleton) into an
> autonomous **BRD analysis multi-agent system**: ingest a Business Requirements
> Document, ground every agent in organizational knowledge (RAG), run 5 specialist
> agents to produce delivery artifacts, and score + revise them before presenting
> quality badges to the Engineering Manager.

**LLM provider:** OpenAI API, model `gpt-4.1` for all agents (embeddings:
`text-embedding-3-large`).
**Hosting:** Azure Container Apps (single always-on web process) + Azure Files +
Key Vault + Blob, provisioned with Bicep, shipped by GitHub Actions.

---

## 1. Target architecture

```
Streamlit UI  ──►  LangGraph Orchestrator (in-process, SqliteSaver checkpoints)
                        │
                        ▼
              brd_ingest_node        ── Capability 1: Ingestion & Parsing
                        ▼
              orchestrator_node      ── routing, state, retry/revision policy
                        ▼
   ┌──────────────── specialist agents (Capability 3) ────────────────┐
   │ engineering_plan_generator   (+ Reflection self-review step)     │
   │ schedule_estimator           (consumes plan phases)              │
   │ solution_architect                                               │
   │ poc_planner                  (consumes architecture)             │
   │ tech_stack_recommender                                           │
   └─────────────────────────────────────────────────────────────────┘
                        ▼
              critic_node            ── Capability 4: score + revision loop
                        │  (verdict=revise) ──► back to the failing agent
                        ▼
              assemble_node          ── compile BRD response doc + badges
                        ▼
                       END

   rag_retriever (Capability 2) — called by every agent above for grounding
```

**Provider:** `langchain_openai.ChatOpenAI(model="gpt-4.1")` via a shared factory.
No Azure OpenAI, no Gemini.

---

## 2. The 4 capabilities → the 8 agents

| Capability | Delivered by |
|---|---|
| 1. BRD Ingestion & Parsing — parse uploads, extract sections, classify requirements, tag metadata | `skills/brd_parser.py` + `agents/brd_ingest_agent.py` |
| 2. Knowledge Augmentation (RAG) — ground outputs in past BRDs, templates, patterns, org standards | `skills/rag_retriever.py` + `knowledge_base/corpus/` |
| 3. Multi-Agent Generation — plans, schedules, architecture, PoC, tech-stack options | the 5 specialist agents below |
| 4. Validation & Evaluation — score outputs, enforce revisions, quality badges | `agents/critic_agent.py` + `config/brd_config.yaml` rubric |

| # | Agent | Discipline | Responsibility |
|---|---|---|---|
| 1 | **BRD Ingest** | Ingestion | Load the BRD, redact credentials/PII, split into sections, classify requirements, tag project metadata (`gpt-4.1-mini`). |
| 2 | **Orchestrator** | Orchestration | Route BRD sections to specialists; manage state; handle errors and retries. Pure router on revision re-entry. |
| 3 | **Engineering Plan Generator** | Planning | Phases, risks, milestones, team composition. Runs a **Reflection** (draft → self-critique → revise) step internally. |
| 4 | **Schedule Estimator** | Planning | Effort estimates, timelines, resource allocation. Phase names/order must align to the plan. |
| 5 | **Solution Architect** | Design | High-level system design, components, data flows, NFR mapping. |
| 6 | **PoC Planner** | Design | PoC scope, measurable success criteria, modular boundaries mapped to architecture components. |
| 7 | **Tech Stack Recommender** | Design | 2–3 stack options with trade-offs (scalability, team familiarity, integration risk, cost) + a recommendation. |
| 8 | **Critic** | Validation | Score every artifact on completeness, consistency, actionability, groundedness. Enforce the revision loop; emit badges. |

(A ninth node, `assemble`, compiles the final document deterministically — no LLM call, so it isn't counted as an agent.)

---

## 3. LLM provider — OpenAI `gpt-4.1` for all agents

The ETL skeleton hard-codes Azure wiring inline in every agent. **Recommendation:
centralize it in one factory** instead of repeating it across 8 new agents.

### 3.1 New: `skills/llm_factory.py`

```python
import os
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

def get_llm(agent_name: str, llm_config: dict) -> ChatOpenAI:
    agent_cfg = llm_config.get("agents", {}).get(agent_name, {})
    oa = llm_config.get("openai", {})
    return ChatOpenAI(
        model=os.environ.get("OPENAI_MODEL", oa.get("model", "gpt-4.1")),
        temperature=agent_cfg.get("temperature", oa.get("temperature", 0.2)),
        max_tokens=agent_cfg.get("max_tokens", oa.get("max_tokens", 8192)),
        timeout=oa.get("timeout_seconds", 120),
        max_retries=oa.get("max_retries", 3),
        api_key=os.environ["OPENAI_API_KEY"],
    )

def get_embeddings(llm_config: dict) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-large"),
        api_key=os.environ["OPENAI_API_KEY"],
    )
```

Every node calls `get_llm("<agent_name>", llm_config)`; `rag_retriever` calls
`get_embeddings(llm_config)`.

### 3.2 `config/llm_config.yaml` (rewrite)

```yaml
provider: openai
openai:
  model: "gpt-4.1"
  embed_model: "text-embedding-3-large"
  temperature: 0.2
  max_tokens: 8192
  timeout_seconds: 120
  max_retries: 3
agents:
  orchestrator:               {temperature: 0.0}
  brd_ingest:                 {temperature: 0.0, model: "gpt-4.1-mini"}  # cheap classification pass
  engineering_plan_generator: {temperature: 0.3}
  schedule_estimator:         {temperature: 0.1}
  solution_architect:         {temperature: 0.2}
  poc_planner:                {temperature: 0.2}
  tech_stack_recommender:     {temperature: 0.3}
  critic:                     {temperature: 0.0}
revision:
  max_revisions_per_agent: 2
  min_pass_score: 0.75
rag:
  chunk_tokens: 800
  chunk_overlap: 100
  top_k: 6
```

> `get_llm` should honor a per-agent `model:` override (see `brd_ingest`) — add
> `agent_cfg.get("model")` to the `os.environ.get(..., ...)` fallback chain.

### 3.3 `.env.example` (rewrite)

```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1
OPENAI_EMBED_MODEL=text-embedding-3-large
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=...
LANGCHAIN_PROJECT=brd-dev-agent
# Azure runtime (set by infra, not needed for local dev)
VECTORSTORE_DIR=./vectorstore
CHECKPOINT_DB=./checkpoints/langgraph_states.db
ARTIFACT_STORE=local            # local | blob
```

Delete every `AZURE_OPENAI_*`, `GITHUB_TOKEN`, `AIRFLOW_*`.

### 3.4 `run.sh`
Change the credential guard from `AZURE_OPENAI_API_KEY` → `OPENAI_API_KEY` (same
check/exit logic). Add: run `python scripts/build_index.py` when `vectorstore/`
is missing, before launching the UI.

---

## 4. State redesign — `orchestration/state.py` (rewrite)

```python
class Stage(str, Enum):
    INGEST = "ingest"; ORCHESTRATE = "orchestrate"
    PLAN = "engineering_plan"; SCHEDULE = "schedule"
    ARCHITECTURE = "architecture"; POC = "poc"; TECH_STACK = "tech_stack"
    CRITIQUE = "critique"; ASSEMBLE = "assemble"
    COMPLETE = "complete"; FAILED = "failed"

class BRDSection(TypedDict):
    section_id: str; title: str; level: int; raw_text: str; page_range: str

class Requirement(TypedDict):
    req_id: str; section_id: str; text: str
    type: str            # functional | non_functional | constraint | assumption | out_of_scope
    nfr_category: Optional[str]   # performance | security | scalability | availability | compliance | usability
    priority: str        # must | should | could | wont
    ambiguity_flag: bool

class AgentArtifact(TypedDict):
    agent: str; content: dict
    citations: list[str]         # KB refs the agent used
    revision: int
    self_review: Optional[dict]  # Reflection notes (plan generator only)
    status: str                  # ok | failed

class CriticScore(TypedDict):
    agent: str
    completeness: float; consistency: float; actionability: float; groundedness: float
    overall: float
    verdict: str        # pass | revise
    issues: list[str]
    badge: str          # green | amber | red

class BRDState(TypedDict):
    # input
    brd_id: str; brd_path: str; brd_raw_text: str
    framework_config: dict; thread_id: str
    # ingest
    brd_text: str; brd_sections: list[BRDSection]
    requirements: list[Requirement]; brd_metadata: dict
    # orchestrator
    agent_plan: list[str]; routing_map: dict           # agent -> [section_id]
    # deliverables
    engineering_plan: Optional[AgentArtifact]
    schedule: Optional[AgentArtifact]
    architecture: Optional[AgentArtifact]
    poc_plan: Optional[AgentArtifact]
    tech_stack: Optional[AgentArtifact]
    # validation
    critic_scores: dict            # agent -> CriticScore
    revision_counts: dict          # agent -> int
    pending_revision: Optional[str]
    # output
    brd_response_doc: str
    quality_badges: dict           # agent -> badge
    # control
    current_stage: str; current_step: str
    errors: list[str]; messages: list[dict]
```

Keep the `make_initial_state(...)` factory and the SqliteSaver singleton pattern
from `orchestration/langgraph_workflow.py`, but read the DB path from
`os.environ["CHECKPOINT_DB"]`.

---

## 5. Capability 1 — BRD Ingestion & Parsing

### 5.1 New: `skills/brd_parser.py`
- `load_document(path) -> str` — dispatch by extension: `.docx` (python-docx),
  `.pdf` (pypdf), `.md`/`.txt` (plain). Returns normalized text + heading map.
- `extract_sections(text) -> list[BRDSection]` — heading splitter (markdown `#`,
  numbered `1.` / `1.1`, ALL-CAPS lines, docx heading styles).
- `classify_requirements(sections, llm) -> list[Requirement]` — LLM call per
  section (or batched) emitting the `Requirement` schema JSON.
- `tag_metadata(sections, requirements, llm) -> dict` — project name, stakeholders,
  target dates, business goals, success metrics, glossary, referenced systems.
- Reuse the JSON-extraction helpers (`_extract_json`, fence-stripping) from the
  existing `agents/agile_coach_agent.py`.

### 5.2 New: `agents/brd_ingest_agent.py`
`brd_ingest_node(state) -> dict`
- Reads `state["brd_path"]` (or `brd_raw_text`).
- Runs the parser functions; writes `brd_text`, `brd_sections`, `requirements`,
  `brd_metadata`, `current_step="brd_ingest_complete"`.
- Persists `output/parsed/<brd_id>_parsed.json` (or Blob when `ARTIFACT_STORE=blob`).
- On failure → `current_step="brd_ingest_failed"` (mirror `_fail` pattern).

### 5.3 Sample inputs
Replace `data/sample_stories/` with `data/sample_brds/` — 2–3 example BRDs (`.md`
is fine) + one golden parsed JSON fixture for tests. Delete `data/sample_data/*`.

---

## 6. Capability 2 — Knowledge Augmentation (RAG)

### 6.1 Knowledge base restructure — `knowledge_base/`
Delete the pyspark/etl YAMLs. New layout:

```
knowledge_base/
  corpus/
    past_brds/       *.md   historical BRDs + their delivered plans
    templates/       engineering_plan_template.md, architecture_template.md, poc_template.md
    patterns/        architecture_patterns.md, estimation_heuristics.md
    org_standards/   tech_radar.md, security_baseline.md, nfr_catalog.md, sdlc_policy.md
  personas/
    engineering_plan_generator.md
    schedule_estimator.md
    solution_architect.md
    poc_planner.md
    tech_stack_recommender.md
    critic.md
```

### 6.2 New: `skills/rag_retriever.py` (replaces `knowledge_base_loader.py`)
- `class RagRetriever` with a pluggable backend (`RAG_BACKEND=chroma|azure_search`):
  - `build_index(corpus_dir, persist_dir)` — chunk (800 tok / 100 overlap), embed
    via `get_embeddings()`, store in Chroma. Idempotent: write a
    `manifest.json` with a corpus content hash; skip rebuild if unchanged.
  - `retrieve(query, k=6, filter=None) -> list[Chunk]` — metadata filter on
    `doc_type ∈ {past_brd, template, pattern, org_standard}`.
  - `retrieve_for_agent(agent_name, brd_summary, requirements) -> str` —
    agent-specific query composition + doc_type weighting (architect biases
    `patterns` + `nfr_catalog`; tech_stack biases `tech_radar`).
  - `format_context(chunks) -> str` with inline citation markers
    `[KB:<doc>#<chunk>]` so the Critic can verify groundedness.
- Keep persona loading (`get_persona` / `load_markdown`) — port into this module
  or a small `skills/persona_loader.py`.

### 6.3 Index bootstrap
- New `scripts/build_index.py` — CLI to (re)build the vector store.
- `run.sh` / container entrypoint call it when `vectorstore/` is empty.
- Add `vectorstore/` to `.gitignore`.

### 6.4 Grounding contract
Every specialist system prompt has a `{grounding_context}` slot filled by
`retrieve_for_agent(...)`. Every specialist emits `citations: [...]` in its JSON —
consumed by the Critic's groundedness score.

---

## 7. Capability 3 — The specialist agents (`agents/`)

Each agent = one module with `<name>_node(state) -> dict`, following current node
conventions: logging banner, `get_llm(...)`, `_extract_json`, `_fail` helper,
artifact save. Each returns an `AgentArtifact` envelope.

### 7.1 `agents/orchestrator_agent.py`
- Reads `requirements`, `brd_sections`, `brd_metadata`.
- Produces `agent_plan` (ordered specialists) + `routing_map` (agent → section IDs).
- Initializes `revision_counts` to 0.
- **On revision re-entry** (`pending_revision` set): pure pass-through, no re-plan.
- Non-blocking error policy: if a downstream agent hard-fails twice, mark its
  artifact `status="failed"` and continue.

### 7.2 `agents/engineering_plan_agent.py` — with Reflection
One node, three LLM calls:
1. `draft` — from plan prompt + `{grounding_context}` (templates + past BRDs).
2. `critique` — reflection prompt over the draft: phase coverage, risk-register
   completeness, milestone/deliverable alignment, team realism, unmapped requirements.
3. `final` — revise prompt (draft + critique). Store `self_review=critique`.
- `content`: `{phases:[{name, objectives, entry_criteria, exit_criteria, deliverables}],
  risks:[{risk, likelihood, impact, mitigation, owner}],
  milestones:[{name, target_week, dependencies}],
  team_composition:[{role, count, allocation_pct, phase}]}`

### 7.3 `agents/schedule_estimator_agent.py`
- Reads `engineering_plan.content.phases` + `team_composition` + `requirements` +
  `estimation_heuristics` (RAG).
- `content`: per-phase effort (person-weeks), calendar timeline (start/end week
  with parallelism + ramp-up), resource matrix (role × phase × %), critical path,
  confidence range (optimistic/likely/pessimistic).
- Hard constraint: phase names/order match the plan; emit `alignment_ok: bool` + deltas.

### 7.4 `agents/solution_architect_agent.py`
- Reads `requirements` (esp. `non_functional`), `brd_metadata.referenced_systems`,
  RAG (`architecture_patterns`, `nfr_catalog`, `security_baseline`).
- `content`: `{context_diagram_desc, components:[{name, responsibility, tech_area,
  interfaces}], data_flows:[{from, to, data, protocol, sync|async}],
  integrations:[{system, direction, method}],
  nfr_mapping:[{nfr_category, requirement_ids, tactic, verification}],
  key_decisions:[{decision, rationale, alternatives}]}`
- Also emit a Mermaid diagram string for the UI.

### 7.5 `agents/poc_planner_agent.py`
- Reads `architecture`, `engineering_plan.risks`, highest-risk requirements.
- `content`: `{poc_goal, hypotheses, in_scope, out_of_scope,
  modules:[{name, boundary, interfaces, mock_vs_real}],
  success_criteria:[{metric, threshold, measurement_method}],
  duration_weeks, resources, exit_decision_matrix}`
- Constraint: every module maps to an `architecture.components` entry; success
  criteria must be measurable (Critic enforces).

### 7.6 `agents/tech_stack_agent.py`
- Reads `architecture.components`, `brd_metadata`, `tech_radar` (RAG).
- `content`: `options:[{name, layers:{language, framework, datastore, infra,
  ci_cd, observability}, tradeoffs:{scalability, team_familiarity,
  integration_risk, cost, time_to_market}, score_by_dimension:{...}, best_when}]`
  — exactly 2–3 options + `recommendation` tied to BRD constraints.

### 7.7 `agents/critic_agent.py` — Capability 4
One node that scores whichever artifacts are "dirty" and sets `pending_revision`.
- Per artifact, LLM scores 0–1 on:
  - **completeness** — required sections present (from `brd_config.yaml`)
  - **consistency** — cross-artifact (schedule vs plan phases, poc vs architecture,
    tech_stack vs components)
  - **actionability** — concrete, owned, measurable
  - **groundedness** — re-retrieve each cited KB ref and check it supports the claim
- `overall` = weighted sum (weights in `brd_config.yaml`).
  Badge: green ≥ 0.8, amber 0.6–0.8, red < 0.6.
- Revision loop: `verdict=="revise"` and `revision_counts[agent] < max_revisions`
  → set `pending_revision=agent`, increment count, attach `issues` so the agent's
  next prompt starts with `FIX THESE ISSUES:` (same mechanism as the ETL retry loop).
  Else accept with the current badge.
- Writes `critic_scores[agent]`, `quality_badges[agent]`.
- Rubric text lives in `knowledge_base/personas/critic.md`.

### 7.8 `agents/assemble_agent.py`
`assemble_node` compiles the 5 deliverables + `quality_badges` into
`output/reports/<brd_id>_response.md` (+ `.json`) using a template from
`knowledge_base/corpus/templates/`.

### 7.9 Delete (after replacements pass tests)
`agile_coach_agent.py`, `ingestion_agent.py`, `transformation_agent.py`,
`quality_agent.py`, `output_agent.py`, `pr_agent.py`, `deploy_agent.py`,
`skills/git_pr_helper.py`, `skills/framework_validator.py`,
`config/repo_config.yaml`, `tests/test_etl_developer.py`, all `output/generated_*`.

---

## 8. Orchestration — `orchestration/langgraph_workflow.py` (rewrite)

```
START → brd_ingest → orchestrator
orchestrator → route_after_orchestrator:
    pending_revision set  → <that agent>
    else                  → engineering_plan
engineering_plan → schedule → solution_architect → poc_planner → tech_stack → critic
critic → route_after_critic:
    pending_revision == "engineering_plan" → engineering_plan
    pending_revision == "schedule"         → schedule
    pending_revision == "solution_architect" → solution_architect
    pending_revision == "poc_planner"      → poc_planner
    pending_revision == "tech_stack"       → tech_stack
    None                                   → assemble
assemble → END
```

- Routers mirror `route_after_quality` in the current file.
- `route_after_ingest`: fail → END, else `orchestrator`.
- Keep sequential for v1 (deterministic, debuggable). Later optimization: fan-out
  `solution_architect` ∥ `tech_stack` since tech-stack only needs a first
  architecture pass.
- Keep SqliteSaver checkpointing, `run_pipeline(...)` entry point, file logging,
  and the CLI `__main__` block. Rename params: `user_story` → `brd_path`/`brd_text`.
- `load_configs()` drops `repo_config`; merges `brd_config.yaml` + `llm_config.yaml`.

---

## 9. Config — `config/`

### 9.1 Rename `framework_config.yaml` → `brd_config.yaml`
```yaml
rubric_weights:
  completeness: 0.30
  consistency: 0.25
  actionability: 0.25
  groundedness: 0.20
badges:
  green: 0.80
  amber: 0.60
required_sections:
  engineering_plan: [phases, risks, milestones, team_composition]
  schedule:         [phase_effort, timeline, resource_matrix, critical_path]
  architecture:     [components, data_flows, nfr_mapping, key_decisions]
  poc_plan:         [poc_goal, modules, success_criteria, exit_decision_matrix]
  tech_stack:       [options, recommendation]
output:
  parsed_dir: "output/parsed"
  deliverables_dir: "output/deliverables"
  report_dir: "output/reports"
```

### 9.2 `llm_config.yaml` — see §3.2. Delete `config/repo_config.yaml`.

---

## 10. Streamlit UI — `streamlit_app/`

- `app.py`: rebrand ("Autonomous BRD Analysis"). Sidebar: single **OpenAI API Key**
  password field → `os.environ["OPENAI_API_KEY"]`. Stat cards: Requirements parsed /
  Deliverables generated / Avg quality score / Revisions triggered / Overall badge.
  Replace sample-story selector with a BRD **file uploader** (`.docx/.pdf/.md`) +
  sample picker.
- `components/agent_status.py` → 8-agent stage tracker.
- `components/code_viewer.py` → `deliverable_viewer.py`: render each deliverable's
  markdown + `CriticScore` badge + expandable issues/citations. Render architecture
  Mermaid.
- Pages:
  1. `1_brd_upload.py`
  2. `2_parsed_requirements.py` — sections table, requirement classification, metadata tags
  3. `3_deliverables.py` — tabs: Plan / Schedule / Architecture / PoC / Tech Stack
  4. `4_quality_report.py` — Critic scorecards, badges, revision history
  5. `5_export.py` — download the assembled BRD response doc

---

## 11. Tests — `tests/`

- `conftest.py` — `fake_llm` fixture (queued canned JSON responses) reused everywhere.
- `test_brd_parser.py` — section extraction on a `.md` fixture; requirement + metadata
  schema validation with `fake_llm`.
- `test_rag_retriever.py` — index build on a tiny corpus; retrieval + metadata filter.
- `test_critic.py` — scoring math (weights → overall → badge); `route_after_critic`
  dispatch; `max_revisions` cap.
- `test_workflow_smoke.py` — full graph, all LLM calls patched; asserts state reaches
  `ASSEMBLE` with all 5 deliverables + badges present.
- `test_state.py` — `make_initial_state` shape.

---

## 12. Azure deployment

### 12.1 What we deploy
One long-running process: **Streamlit UI + in-process LangGraph pipeline**. Three
pieces of local-disk state from the skeleton must move to managed storage:

| State | Local today | Azure target (Tier 1) | Azure target (Tier 2) |
|---|---|---|---|
| RAG vector index | `vectorstore/` (Chroma) | Azure Files share | Azure AI Search |
| LangGraph checkpoints | `checkpoints/*.db` (SQLite) | Azure Files share | Azure DB for PostgreSQL Flexible |
| BRD uploads + deliverables | `data/`, `output/` | Azure Blob Storage | Azure Blob Storage |
| Secrets | `.env` | Azure Key Vault | Azure Key Vault |

**Hosting: Azure Container Apps (ACA).** Streamlit is a stateful, websocket,
always-on process — wrong shape for Functions. ACA gives HTTPS ingress, scale-to-1
(not zero, so sessions survive), Azure Files volume mounts, Key Vault secret refs,
managed identity, and revision-based rollout with less ceremony than AKS.
(App Service for Containers is an equivalent alternative.)

### 12.2 Architecture

```
Developer ─► GitHub Actions (OIDC) ─► Azure Container Registry (image)
                                            │
 EM/users ─► HTTPS ─► Container Apps Environment
                        └─ Container App: brd-agent  (Streamlit :8501)
                             identity: system-assigned Managed Identity
                             ├─ secretRef → Key Vault: OPENAI_API_KEY, LANGCHAIN_API_KEY
                             ├─ volume → Azure Files: /app/vectorstore
                             ├─ volume → Azure Files: /app/checkpoints
                             ├─ Blob SDK → brd uploads + deliverables
                             └─ stdout + OTel → Log Analytics + Application Insights
                          outbound ─► api.openai.com, LangSmith
```

### 12.3 New files
```
Dockerfile
.dockerignore
scripts/entrypoint.sh          # build RAG index if missing, then launch Streamlit
infra/main.bicep               # all Azure resources
infra/main.parameters.json
azure.yaml                     # enables `azd up` one-shot provision + deploy
.github/workflows/deploy.yml   # CI/CD
```

**Dockerfile**
```dockerfile
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
ENTRYPOINT ["scripts/entrypoint.sh"]
```

**scripts/entrypoint.sh**
```bash
#!/usr/bin/env bash
set -e
if [ ! -f "${VECTORSTORE_DIR:-/app/vectorstore}/manifest.json" ]; then
  python scripts/build_index.py
fi
exec streamlit run streamlit_app/app.py \
  --server.port 8501 --server.address 0.0.0.0 \
  --server.headless true --server.enableCORS false --server.enableXsrfProtection true
```

### 12.4 Resources provisioned by `infra/main.bicep`
1. **Resource Group** `rg-brd-agent-<env>`.
2. **Azure Container Registry** (Basic). ACA pulls via MI (`AcrPull`).
3. **Log Analytics workspace** + **Application Insights**.
4. **Storage Account** — File shares `vectorstore`, `checkpoints`; Blob container `brd-artifacts`.
5. **Key Vault** — secrets `OPENAI-API-KEY`, `LANGCHAIN-API-KEY`; MI granted `Key Vault Secrets User`.
6. **Container Apps Environment** — bound to Log Analytics; declares the two Files storage links.
7. **Container App** `brd-agent`:
   - image `<acr>.azurecr.io/brd-agent:<sha>`
   - ingress: external, target port 8501, HTTP/2 + websockets, HTTPS only
   - `minReplicas: 1`, `maxReplicas: 1` (see §12.6), sticky sessions
   - env: `OPENAI_MODEL=gpt-4.1`, `OPENAI_EMBED_MODEL`, `LANGCHAIN_*`,
     `VECTORSTORE_DIR=/app/vectorstore`, `CHECKPOINT_DB=/app/checkpoints/langgraph_states.db`,
     `ARTIFACT_STORE=blob`
   - secrets: `openai-api-key` → Key Vault reference → injected as `OPENAI_API_KEY`
   - volume mounts: `vectorstore` → `/app/vectorstore`, `checkpoints` → `/app/checkpoints`
   - probes: HTTP GET `/_stcore/health`
8. **Role assignments**: MI → `AcrPull` on ACR, `Key Vault Secrets User` on KV,
   `Storage Blob Data Contributor` + `Storage File Data SMB Share Contributor` on storage.
9. Optional: custom domain + managed cert; **Easy Auth (Azure AD)** so only org
   EMs can reach the UI.

### 12.5 Code changes for Azure
| Area | Change |
|---|---|
| `langgraph_workflow.py` | checkpoint DB path from `CHECKPOINT_DB` env. Tier 2: swap `SqliteSaver` → `PostgresSaver` (`langgraph-checkpoint-postgres`), DSN from `DATABASE_URL`. |
| `skills/rag_retriever.py` | `persist_dir` from `VECTORSTORE_DIR`. Tier 2: `AzureAISearchRetriever` backend behind the same interface, selected by `RAG_BACKEND`. |
| `skills/brd_parser.py`, ingest + assemble nodes | when `ARTIFACT_STORE=blob`, read/write via `azure-storage-blob` + `DefaultAzureCredential`; keep local FS for dev. |
| `streamlit_app/app.py` | init App Insights exporter when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set. |
| `requirements.txt` | add `azure-identity`, `azure-storage-blob`, `azure-monitor-opentelemetry`. Tier 2: `langgraph-checkpoint-postgres`, `psycopg[binary]`, `azure-search-documents`. |
| `.gitignore` | add `vectorstore/`, `checkpoints/`, `*.env`. |

### 12.6 Scaling caveat (important)
Streamlit keeps `st.session_state` in **one replica's memory**; the SQLite
checkpointer is a **single-writer file**. Therefore:
- **Default: `minReplicas = maxReplicas = 1`.** Correct and sufficient for an
  internal EM tool — the pipeline is LLM-bound (minutes/run), not CPU-bound.
- **To go multi-replica:** enable ACA sticky sessions **and** move checkpoints to
  PostgreSQL (Tier 2), and Blob-back artifacts so an upload isn't stranded.
- **Recommendation: ship Tier 1 single-replica.** Adopt Tier 2 only when
  concurrency or an availability SLA forces it.

### 12.7 CI/CD — `.github/workflows/deploy.yml`
1. Trigger: push to `main` + manual `workflow_dispatch`.
2. Auth: **OIDC federated credentials** (no stored SP secret).
3. `az acr build -t brd-agent:<git-sha> .`
4. `az containerapp update --image ...:<sha>` → new **revision**, traffic shifts.
   Rollback = shift traffic to previous revision.
5. Post-deploy smoke: `curl -f https://<app>/_stcore/health`.
6. Separate job: `az deployment group create` on `infra/**` changes only.
- `azd up` is the low-effort path for initial stand-up (provision + build + push +
  deploy in one command via `azure.yaml`).

### 12.8 Provisioning sequence
1. `az group create`
2. `az deployment group create -f infra/main.bicep`
3. `az keyvault secret set` → `OPENAI-API-KEY`, `LANGCHAIN-API-KEY`
4. `az acr build -t brd-agent:init .`
5. Point the Container App at the image
6. First boot: `entrypoint.sh` sees empty `vectorstore` → runs `build_index.py`
   against the KB corpus baked into the image; later boots skip it
7. Open the ingress URL, upload a sample BRD, confirm a run completes with
   deliverables + badges
8. Wire GitHub Actions OIDC; thereafter every `main` push ships a revision

### 12.9 Cost & ops
- ACA web tier: 0.5 vCPU / 1 GiB scale-to-1 is enough (1 vCPU / 2 GiB if index
  builds are slow). Pay per vCPU-second.
- File shares + Blob: cents at this scale.
- Log Analytics: set a daily cap, 30-day retention.
- **Dominant cost is OpenAI usage**, not Azure infra. A full 8-agent run with
  Reflection + one revision loop is a few dozen `gpt-4.1` calls. Keep LangSmith on
  to watch per-run token spend; `brd_ingest` already downshifts to `gpt-4.1-mini`.
- Tier 2 adds real cost (PostgreSQL Flexible burstable + Azure AI Search Basic) —
  only when single-replica limits actually bite.

---

## 13. Dependencies — `requirements.txt` (rewrite)

```
# Orchestration + LLM
langgraph>=0.2.0
langchain>=0.2.0
langchain-core>=0.2.0
langchain-openai>=0.1.0
langsmith>=0.1.75

# BRD ingestion
python-docx>=1.1.0
pypdf>=4.2.0
markdown-it-py>=3.0.0

# RAG
chromadb>=0.5.0
langchain-chroma>=0.1.0
tiktoken>=0.7.0

# UI
streamlit>=1.35.0

# Config / util
pydantic>=2.7.0
PyYAML>=6.0.1
python-dotenv>=1.0.0

# Azure runtime
azure-identity>=1.17.0
azure-storage-blob>=12.20.0
azure-monitor-opentelemetry>=1.6.0

# Tests
pytest>=8.2.0
pytest-cov>=5.0.0

# Tier 2 (add when needed)
# langgraph-checkpoint-postgres>=1.0.0
# psycopg[binary]>=3.2.0
# azure-search-documents>=11.5.0
```

Removed: `langchain-openai` Azure usage, `PyGithub`, `pyflakes`, `black`,
`streamlit-ace`, `requests` (Airflow), `pygments`, `rich`, `tabulate`.

---

## 14. Build order

| Step | Deliverable | Depends on |
|---|---|---|
| 1 | `state.py` rewrite + `make_initial_state` + `test_state.py` | — |
| 2 | `skills/llm_factory.py`; `config/llm_config.yaml` + `config/brd_config.yaml`; `.env.example` | — |
| 3 | `skills/brd_parser.py` + `agents/brd_ingest_agent.py` + `data/sample_brds/` + tests | 1, 2 |
| 4 | `knowledge_base/corpus/` + `personas/`; `skills/rag_retriever.py` + `scripts/build_index.py` + tests | 2 |
| 5 | `agents/orchestrator_agent.py` | 1, 3 |
| 6 | 5 specialist agents (plan → schedule → architect → poc → tech_stack) with grounding + personas | 4, 5 |
| 7 | `agents/critic_agent.py` + revision loop + rubric | 6 |
| 8 | `orchestration/langgraph_workflow.py` rewrite (routers, graph, `run_pipeline`) + `test_workflow_smoke.py` | 6, 7 |
| 9 | `agents/assemble_agent.py` + response template | 8 |
| 10 | Streamlit UI rebuild (`app.py`, components, 5 pages) | 8, 9 |
| 11 | Delete ETL files; finalize `requirements.txt`, `run.sh`, `README.md` | 1–10 |
| 12 | `Dockerfile`, `.dockerignore`, `scripts/entrypoint.sh`; verify container runs locally with mounted volumes | 11 |
| 13 | `infra/main.bicep` + params; `azure.yaml`; `az deployment` dry run | 12 |
| 14 | Key Vault secrets, managed identity roles, first manual image push + deploy | 13 |
| 15 | `.github/workflows/deploy.yml` (OIDC); revision rollout + smoke test | 14 |
| 16 | Env-driven Blob artifact store; App Insights wiring | 14 |
| 17 | *(Optional Tier 2)* PostgresSaver + Azure AI Search backend | 15 |

---

## 15. Key recommendations (summary)

1. **Centralize LLM construction** in `skills/llm_factory.py` — don't copy the
   ETL skeleton's inline `ChatOpenAI(...)` into 8 agents.
2. **One Critic node**, not a critic per agent — it needs cross-artifact context
   to score consistency, and it owns the single `pending_revision` router.
3. **Reflection lives inside the plan generator** (3 calls in one node), keeping
   the graph flat and the checkpoint history readable.
4. **Ship Tier 1 (ACA single-replica + Azure Files + Blob + Key Vault).** It is
   correct for an internal EM tool. Only move to Postgres + Azure AI Search when
   real concurrency/SLA pressure appears.
5. **`gpt-4.1` everywhere, `gpt-4.1-mini` for the ingestion classification pass** —
   its 1M-token context lets the Critic and Reflection steps pass whole
   deliverables without chunking.
6. **Groundedness is verified, not trusted** — the Critic re-retrieves each cited
   KB reference and checks it supports the claim.
7. **Keep the graph sequential for v1.** Add the `architect ∥ tech_stack` fan-out
   only after the sequential pipeline is stable.
