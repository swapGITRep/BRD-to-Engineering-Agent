# IK BRD Dev Agent

> Autonomous multi-agent system that turns a **Business Requirements Document**
> into a delivery package — engineering plan, schedule, solution architecture,
> PoC plan, and technology-stack options — each scored and revised before it
> reaches the Engineering Manager.
>
> LangGraph · OpenAI `gpt-4.1` · Retrieval-Augmented Generation · Streamlit

---

## What it does

1. **Ingest & parse** — reads a BRD (`.md` / `.txt` / `.docx` / `.pdf`), splits it
   into sections, classifies each requirement (functional / non-functional /
   constraint / assumption / out-of-scope, priority, NFR category, ambiguity),
   and tags project metadata.
2. **Ground everything (RAG)** — every agent is grounded in a knowledge base of
   past deliveries, templates, architecture patterns, estimation heuristics, and
   org standards (`knowledge_base/corpus/`).
3. **Generate (5 specialist agents)** — Engineering Plan (with a Reflection
   self-review step), Schedule Estimator, Solution Architect, PoC Planner, Tech
   Stack Recommender.
4. **Validate & evaluate** — one Critic scores each deliverable on
   completeness · consistency · actionability · groundedness, enforces a
   per-agent revision loop, and assigns 🟢 / 🟡 / 🔴 quality badges.
5. **Assemble** — compiles a single Markdown BRD response document with a quality
   scorecard.

---

## Architecture

```
Streamlit UI ──► LangGraph pipeline (SqliteSaver checkpoints)

  brd_ingest ─► orchestrator ─► engineering_plan ─► schedule ─► architecture
             ─► poc_plan ─► tech_stack ─► critic ──(revise)──► failing agent
                                             └──(pass)──► assemble ─► END

  rag_retriever (knowledge_base/corpus) — grounding for every agent
```

| Agent | Role |
| --- | --- |
| Orchestrator | Route BRD sections to specialists; manage state; revision routing |
| Engineering Plan Generator | Phases, risks, milestones, team — with a Reflection self-review |
| Schedule Estimator | Effort, timeline, resource matrix, critical path (aligned to the plan) |
| Solution Architect | Components, data flows, NFR mapping, key decisions, Mermaid diagram |
| PoC Planner | Falsifiable goal, modules mapped to architecture, measurable success criteria |
| Tech Stack Recommender | 2–3 stack options + trade-offs + a recommendation |
| Critic | Score deliverables, enforce the revision loop, emit quality badges |

---

## Quick start

Requires **Python 3.12** (`brew install python@3.12`).

```bash
cp .env.example .env          # set OPENAI_API_KEY
chmod +x run.sh

./run.sh                      # Streamlit UI at http://localhost:8501
./run.sh cli data/sample_brds/payments_reconciliation_brd.md   # headless run
./run.sh test                 # pytest
```

`run.sh` finds Python 3.12 (override with `PYTHON=/path/to/python3.12 ./run.sh`),
creates a venv, installs `requirements.txt`, and builds the RAG index
(`scripts/build_index.py`) on first run. If an existing `venv/` was built with a
different Python version it is rebuilt automatically.

### Configuration

- `config/llm_config.yaml` — provider (`openai`), model (`gpt-4.1`; `brd_ingest`
  uses `gpt-4.1-mini`), per-agent temperature, revision budget, RAG settings.
- `config/brd_config.yaml` — Critic rubric weights, badge thresholds, required
  deliverable sections, output paths.
- `.env` — `OPENAI_API_KEY`, optional `LANGCHAIN_*` for LangSmith tracing,
  runtime paths (`VECTORSTORE_DIR`, `CHECKPOINT_DB`, `ARTIFACT_STORE`).

---

## Knowledge base

Add your organization's material under `knowledge_base/corpus/`:

```
corpus/past_brds/       historical BRDs + their delivered plans
corpus/templates/       plan / architecture / PoC / response templates
corpus/patterns/        architecture patterns, estimation heuristics
corpus/org_standards/   tech radar, security baseline, NFR catalogue, SDLC policy
```

Then rebuild: `python scripts/build_index.py --force`.

---

## Outputs

```
output/parsed/<brd_id>_parsed.json            parsed sections + requirements + metadata
output/deliverables/<agent>.json              each specialist's artifact
output/reports/<brd_id>_response.md            the assembled BRD response document
output/reports/<brd_id>_deliverables.json      all deliverables bundled
```

---

## Tests

```bash
pytest tests/ -q
```

All LLM and RAG calls are stubbed; `tests/test_workflow_smoke.py` runs the full
compiled graph end to end.

---

## Evaluation

Unit tests stub every LLM call; the evaluation set runs the real pipeline
against real BRDs to check the *system's* behavior, not just the code's.

`data/eval_brds/labels.yaml` labels 8 BRDs (the 2 samples above plus 6 new
ones under `data/eval_brds/`) with the edge case each is designed to stress —
ambiguous/hedged requirements, directly conflicting NFRs, an oversized
multi-service migration, a minimal 2-requirement BRD, regulatory/compliance
depth, and integration variety (SOAP, batch files, REST, a message queue) —
plus what the pipeline is expected to do with each one.

```bash
python scripts/run_eval.py                                    # the whole set
python scripts/run_eval.py --only AMBIGUOUS_ANALYTICS,CONFLICTING_NFRS
```

Writes `output/eval/<run_id>/summary.md` — per-BRD stage/requirement counts
and whether its expectations were met, plus every agent's Critic scores and
revision count. Exits non-zero on any unmet expectation (pipeline didn't
complete, too few requirements found, ambiguity wasn't flagged), so it's
CI-usable on a prompt or config change; quality scores are always reported,
never pass/fail on their own — a lower score is data about the system, not a
bug in the check. Compare two run_ids' `summary.json` for real before/after
numbers across a change.

---

## Deployment

See [PLAN.md](PLAN.md) §12 — Azure Container Apps (single always-on web process),
Azure Files for the vector index + checkpoints, Blob for artifacts, Key Vault for
secrets, GitHub Actions (OIDC) for CI/CD. Bicep + `azd` supported.
