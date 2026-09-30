# Changelog

**Finding** — what was observed or wrong
before the change;
**Change** — what was actually done; **Benefit** — why it matters.

---

## Correctness Bug Fixes

### `Enum.__str__` overriding the `str` mixin
- **Finding:** `str(Stage.INGEST)` returns `"Stage.INGEST"`, not `"ingest"`,
  because `Enum.__str__` wins over the `str` mixin — this surfaced
  repeatedly across different files (job status display, eval reports)
  before being recognized as one recurring pattern.
- **Change:** Introduced `.value`-preferring helpers (`_stage_str`, `_plain`)
  everywhere an enum crosses into display/JSON, and documented it as a named
  gotcha in `TECHNICAL_DESIGN.md` §5.
- **Benefit:** Naming the footgun once, in writing, stopped it from being
  independently rediscovered and re-fixed in every new file that touched an
  enum.

### Confidentiality scanner double-counting the same secret
- **Finding:** A value matching both a credential pattern (e.g.
  `sk-proj-...`) and the labeled-secret pattern (`api_key: ...`) got
  redacted twice and reported as two separate findings.
- **Change:** Excluded `[`/`]` from the labeled-secret regex's value
  character class, so it can no longer re-match its own `[REDACTED:...]`
  placeholder.
- **Benefit:** Confidentiality reports now reflect the true count of
  sensitive items found, not an inflated one.

### Revision-improvement metric polluted by scoring jitter
- **Finding:** The pre-existing "rescore everyone when any agent revises"
  behavior meant unrevised agents also got a second `score_history` entry;
  reporting all five as "improvement" would have shown misleading near-zero
  deltas for content that never actually changed.
- **Change:** Filtered `revision_improvement()` on whether the artifact's
  own `scored_revision` number actually changed between its first and last
  score — not merely whether it was scored more than once.
- **Benefit:** The before/after metric is trustworthy, not just present — a
  metric that exists but can't be trusted is worse than no metric at all.

### `run.sh` broke after the project folder moved, with confusing errors
- **Finding:** Two separate, live-caught failures on a fresh `./run.sh`: (1)
  `pip: command not found` — every script in `venv/bin` (pip, streamlit) has a
  shebang hardcoding the absolute path the venv was created under, which
  breaks the moment the project folder is renamed or moved, even though
  `venv/bin/python` itself still works (it's a symlink, not a shebang
  script); (2) `.env: line N: Development: command not found` — a `source`d
  `.env` value with an unquoted space (`JIRA_PROJECT=Agent Development
  Team`) is parsed as three shell tokens, and `set -e` then kills the script
  on that line with no explanation of why.
- **Change:** `run.sh` now installs dependencies and launches Streamlit via
  `python -m pip` / `python -m streamlit` instead of the bare commands,
  which resolves through the working interpreter rather than each script's
  own shebang. The `.env` load now catches a non-zero exit from `source` and
  prints what's actually wrong (an unquoted multi-word value) instead of
  just dying on bash's raw error. `.env.example` documents the quoting rule
  up front and shows it on the one placeholder most likely to need it.
- **Benefit:** A moved/renamed project folder or a real Jira project name
  with a space in it no longer produces a cryptic, unrelated-looking error —
  the script's own message names the real cause.

---

## Guardrails & Validation

### Only 5 of 8 agent outputs were schema-validated
- **Finding:** The Critic's own scoring JSON and the Reflection step's JSON
  both went through `extract_json` only, with no pydantic schema — so "all
  agents produce validated JSON" wasn't actually true.
- **Change:** Added `CriticDimensions` and `ReflectionReview` pydantic
  models, wired through the same `invoke_json()` retry path every specialist
  already used.
- **Benefit:** Closed a specific, named gap instead of a generic "add more
  validation" pass — this alone moved Structured Output Contracts from
  60% to 80% in the rubric self-evaluation.

### BRD ingestion's LLM replies had no schema check and could crash ingest
- **Finding:** Ingest was the one LLM-backed agent besides the Orchestrator
  with no schema validation: `classify_requirements` and `tag_metadata`
  parsed the reply with `extract_json` alone and no retry. A reply that was
  valid JSON but the wrong shape — a bare array, `requirements` as a
  string — reached `.get(...)` unchecked and could raise out of ingest;
  `stakeholders` as a string, or a `null` project name, passed straight
  through to downstream code. (Earlier notes here called the Orchestrator the
  only unvalidated agent; that was wrong — Ingest was a real gap too.)
- **Change:** Added `RequirementsResponse` and `ProjectMetadata` pydantic
  models and moved the parse → validate → retry-once-with-feedback loop out
  of `invoke_json()` into one shared function,
  `skills/json_utils.py::invoke_validated_json()`, used by both the
  specialists and ingestion. `null` metadata fields now count as absent, and
  ingestion logs a warning whenever it has to coerce an unrecognised
  `type`/`priority` instead of doing so silently. That logging immediately
  paid off: a live run on `gpt-4.1-mini` showed it returning
  `type="security"` (an NFR category, not a type) for two requirements, which
  had been silently relabelled `functional`. `_coerce_requirement` now maps an
  NFR category found in the `type` field to `non_functional` with that
  category — deterministic, no extra LLM call.
- **Benefit:** 7 of 8 agents are now schema-validated (the Orchestrator emits
  free text, so it has nothing to validate). Malformed ingest replies get one
  corrective retry instead of a crash or silent bad data, and the retry loop
  has a single definition instead of two copies.

### No enforcement that agents stay grounded in each other's real output
- **Finding:** Only one handoff (PoC → Architecture) had a real cross-agent
  input check; Schedule reading the Plan and Tech Stack reading Architecture
  didn't re-validate anything. Solution Architect's own prompt rule ("EVERY
  non_functional requirement id must appear in nfr_mapping") also had no
  code enforcing it — the schema can validate shape but not completeness.
- **Change:** Added `_check_phase_alignment` (Schedule's phases must be real
  Engineering Plan phases), `_check_radar_compliance` (Tech Stack options
  must never be tagged HOLD/RETIRE, enforced via a real `bind_tools` call to
  `check_tech_radar_status`), and `_check_nfr_coverage` (Solution Architect's
  `nfr_mapping` must cover every routed non_functional req_id).
- **Benefit:** Live-verified catching a real mistake — the model inventing
  "Contingency"/"All" as pseudo-phases that didn't exist upstream — proving
  the checks do real work, not just add ceremony. All four specialist agents
  with a deterministic invariant to enforce now enforce it; Engineering Plan
  remains the only one whose failure modes needed a full LLM self-review
  instead (see `TECHNICAL_DESIGN.md` §3.1, Reflection).

### No guardrail against sensitive content reaching the model
- **Finding:** A BRD containing credentials or PII (emails, SSNs, card
  numbers) would go straight into an LLM call with no screening.
- **Change:** Built `skills/confidentiality.py` — deterministic, no-LLM
  regex scanning and redaction — wired as the single choke point in
  `brd_ingest_node`, before section extraction or any model call.
- **Benefit:** Sensitive content never reaches a model call at all, and the
  report only ever states counts ("2 email address(es) redacted"), never
  the values themselves.

---

## External Tool Integrations

### Only one deterministic tool existed, and it was purely local
- **Finding:** `check_tech_radar_status` proved the tool-calling mechanism
  worked, but it only ever read a local file — the app's own docs named "no
  external API/ticketing integration" as a known limitation, and there was
  no real example of a tool that leaves the process.
- **Change:** Added `check_related_jira_tickets`, a second tool on the same
  `bind_tools` mechanism, wired into the PoC Planner. `skills/jira_tickets.py`
  runs a real JQL search against a live Jira Cloud project (auth via email +
  API token, config via env vars, `JIRA_API_TOKEN` through Key Vault the same
  way `OPENAI_API_KEY` already is) before the PoC is drafted, so it doesn't
  propose work that's already tracked. A missing/failed Jira call degrades to
  "not configured" / "no related tickets found" rather than failing the run —
  the same best-effort posture `grounding_for()` already has.
- **Benefit:** Proves the tool-calling mechanism generalizes to a real
  external service, not just a local file — closes the exact gap the docs
  named, without touching the local tech-radar tool's behavior at all.
- **Live-caught regression, fixed in the same change:** adding a second
  direct `get_llm()` call site (for the tool-gathering step, same pattern
  `tech_stack_agent.py` already used) silently made `test_workflow_smoke.py`
  hit the *real* OpenAI API — its `_stub_everything` fixture patched
  `get_llm` on a fixed list of modules that predated this agent needing its
  own entry, and an unpatched module here doesn't fail fast, it just looks
  like a slow test. Caught by a 1.2s → 23.7s full-suite timing jump, not a
  test failure, then fixed back to 1.17s by adding the new module to both
  patch lists and leaving a comment naming the exact failure mode for the
  next tool that does this.

---

## Evaluation & Metrics

### No structural regression check across a labeled set
- **Finding:** Every prompt or config change was verified against whatever
  BRD happened to be at hand, with no repeatable, labeled benchmark.
- **Change:** Built `scripts/run_eval.py` over `data/eval_brds/labels.yaml`
  — 8 BRDs (2 baselines + 6 built to stress a specific edge case:
  ambiguous language, conflicting NFRs, an oversized migration, a sparse
  2-requirement BRD, regulatory depth, integration variety) — checking real
  pipeline behavior against each one's `expect` block.
- **Benefit:** A second, independent evaluation method alongside the
  Critic's own LLM-judged scoring — one checks "did the system do the right
  thing," the other checks "is the output any good," and they catch
  different failure modes.

### Revision loop had no measurable before/after
- **Finding:** The Critic's revision loop demonstrably ran (verified live),
  but `critic_scores[agent]` was overwritten on every revision, so there was
  no record of the actual improvement it produced.
- **Change:** Added `score_history` (every score, kept) and
  `revision_improvement()` in `orchestration/state.py`, rendered as a table
  in the assembled report and aggregated across the whole eval set in
  `run_eval.py`'s summary.
- **Benefit:** "Cycle improvement on at least two metrics" became a
  concrete, citable number (e.g. Architecture 0.70 → 0.81) instead of an
  assertion that the loop "works."

---

## User Experience

### Blocking UI with no feedback during a run
- **Finding:** Clicking "Run analysis" froze the UI on every Streamlit
  script rerun, with no indication of progress or even that anything was
  happening.
- **Change:** Rewrote execution as a background daemon thread
  (`streamlit_app/jobs.py`) with disk-persisted job state and a live
  progress dialog reading LangGraph's own checkpoint for the run's actual
  current stage.
- **Benefit:** The UI stays responsive during a multi-minute run, survives
  a page refresh or a new browser tab adopting the same job, and shows real
  progress instead of a spinner.

### Operational facts invisible to the user
- **Finding:** There was no way to tell which build was actually deployed,
  or whether LangSmith tracing was connected, without checking logs
  directly.
- **Change:** Surfaced `APP_BUILD` and LangSmith connection status directly
  in the UI, plus real Open Graph/Twitter-card metadata for link previews
  (`scripts/patch_streamlit_index.py`, since `st.set_page_config()` only
  updates client-side).
- **Benefit:** Operational state that used to require a terminal is now
  visible at a glance in the product itself.

### The knowledge base grounding every agent was invisible to the user
- **Finding:** `knowledge_base/corpus/**` and `knowledge_base/personas/**`
  ground every specialist agent's output (`skills/rag_retriever.py`), but
  there was no way to see what was actually in them, which agent a persona
  belongs to, or which chunks a given run actually cited, short of reading
  the repo directly.
- **Change:** Added a read-only "Knowledge Base" page (`streamlit_app/views/
  knowledge_base.py`), reachable from a new "Reference" nav group. It renders
  every corpus/persona file, shows the real chunk boundaries via the same
  pure `chunk_text()` the retriever uses (no embedding calls, so it's free),
  the per-doc-type weight multipliers from `AGENT_DOC_WEIGHTS`, and — when a
  result is loaded — which agent(s) actually cited each document this run.
- **Benefit:** Turns an opaque grounding step into something auditable. The
  page is explicitly read-only: the corpus is baked into the deployed image
  (not on either Azure Files share — only `vectorstore` and `output` are
  mounted), so live editing was deliberately scoped out pending a decision
  on how edits should persist.

---