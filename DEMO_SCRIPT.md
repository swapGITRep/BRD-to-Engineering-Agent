# Demo Video Script — BRD Dev Agent

Target runtime: **8–9 minutes**. Each segment lists the on-screen action, the
talking points to narrate, and the exact evidence to point at — so the video
itself stands as proof for the rubric categories named in brackets, not just
a feature tour.

Record against the live deployment
(`https://ca-brdagent.niceflower-477a7d8d.centralindia.azurecontainerapps.io/`)
where possible, falling back to a local `streamlit run` session for anything
that needs a clean/fast state (e.g. the confidentiality demo, so a stray
production log never has to touch a real-looking secret).

---

## 1. Cold open — the problem (0:00–0:30)

**Show:** title card (`docs/assets/charter_title_card.html` — open it
directly in a browser, full screen), then the README's one-line description.

**Say:** "This turns a Business Requirements Document into a delivery
package — an engineering plan, schedule, solution architecture, PoC plan,
and tech stack options — each one scored and revised by a Critic before it
reaches an Engineering Manager. Nine LangGraph nodes, five specialist
agents, one shared state, grounded in a real knowledge base."

---

## 2. Architecture overview (0:30–2:00)

**[Agent Architecture & Orchestration]**

**Show:** the Mermaid diagram in `TECHNICAL_DESIGN.md` §2 (render it, don't
read raw markdown), then a quick pass over `agents/` in the file tree.

**Say:**
- "Eight agents: an Ingest agent, the Orchestrator, five specialists that
  run in a fixed sequence, and one Critic — plus a deterministic assembler
  — not a single do-everything prompt."
- Name the composed orchestration pattern and *why*: prompt-chaining for
  the five specialists, orchestrator-workers for routing, evaluator-optimizer
  for the Critic's revision loop, reflection inside the Engineering Plan
  agent, blackboard for the shared `BRDState` — cite `TECHNICAL_DESIGN.md`
  §3.1, which states the rationale, not just the name.
- One sentence on the failure policy: a single agent's JSON/schema failure
  retries once with the exact problem fed back, then fails that artifact
  without blocking the rest of the pipeline (§3.4).

---

## 3. Live run: ingest through generation (2:00–3:30)

**[Structured Output Contracts, RAG Implementation & Grounding]**

**Show:** open the Streamlit UI, pick a sample BRD (e.g.
`data/sample_brds/payments_reconciliation_brd.md`), click **Run analysis**,
and narrate over the progress dialog while it runs in the background thread.

**Say:**
- "Ingestion classifies every requirement — functional, non-functional,
  constraint, assumption, out-of-scope — and flags ambiguous ones."
- "Every specialist is grounded against `knowledge_base/corpus/` — past
  deliveries, templates, architecture patterns, org standards, 12 real
  documents across 4 categories, chunked and embedded, not just prompted
  with 'be accurate.'"
- Once the run reaches the Schedule/Architecture stage, pause and open the
  resulting deliverable JSON, point at a `"citations": ["KB:architecture_
  patterns.md#3", ...]` entry, and say: "that's a real chunk reference, not
  decoration — the Critic resolves it back to actual text and checks
  groundedness against it."
- Switch to the UI's **Knowledge Base** page and show that same document:
  the real chunk boundaries the retriever actually used, the per-agent
  weight multipliers for its category, and — once the run above has
  completed — a "cited in this run" badge on the exact chunk just referenced.
  "Same grounding step, made auditable instead of opaque."

---

## 4. Critic and the revision loop (3:30–5:00)

**[Critic Agent & Revision Loop, Evaluation Framework]**

**Show:** the Quality Scorecard in the assembled report — badges plus the
per-dimension scores (completeness / consistency / actionability /
groundedness). If the sample BRD didn't trigger a revision, use (or
re-run) one from `data/eval_brds/` known to score low on first pass —
`legacy_integration_heavy_brd.md` is a good candidate given its explicit
edge-case design.

**Say:**
- "Four weighted dimensions, feedback with a specific reason attached, not
  just a number."
- "When a score misses `min_pass_score`, the Critic routes back to that
  *one* agent — not the whole pipeline — for a bounded number of
  revisions."
- Point at the **Revision Improvement** table in the assembled report (or
  a manifest's `revision_improvement` key) and read one row aloud: first
  score, last score, delta. "That's the before/after, captured as data —
  `score_history` per agent, filtered so re-scoring jitter on *unrevised*
  agents never gets counted as improvement." (This distinction — the
  jitter-exclusion filter — is worth 10 seconds of screen time on
  `orchestration/state.py::revision_improvement`'s docstring; it's the
  detail that makes the metric trustworthy rather than just present.)
- Show two cross-agent consistency checks *live* if time allows: PoC ↔
  Architecture component alignment, Schedule ↔ Plan phase alignment.
- If time allows, also point at real LLM-native tool-calling in a LangSmith
  trace: the Tech Stack Recommender calling `check_tech_radar_status`
  against the actual tech radar file, and the PoC Planner calling
  `check_related_jira_tickets` against a real Jira project before
  finalizing scope — both are real tool calls the model chooses to make,
  not just prompted context.

---

## 5. Guardrails (5:00–6:00)

**[Guardrails & Safety]**

**Show:** paste a BRD snippet containing something that looks like a real
secret (e.g. a fake `sk-proj-...`-shaped string or an `api_key: ...` line —
never a real credential) into the upload/paste box, run ingestion, then
open the resulting report's confidentiality banner and the
`confidentiality_notes` field.

**Say:**
- "Nothing reaches an LLM call before this scan runs — it's the first
  thing ingestion does, deterministic regex, no model in the loop."
- "It reports counts, never values — '2 email address(es) redacted,' not
  the emails themselves."
- One sentence each on the other three guardrails already shown earlier:
  input validation (upload size/char-count caps), schema validation with
  one retry, and the deterministic contract checks from segment 4 —
  tying it back so the viewer sees these as one guardrail system, not
  five unrelated features.

---

## 6. Evaluation framework (6:00–6:45)

**[Evaluation Framework]**

**Show:** a terminal running `python scripts/run_eval.py`, then the UI's
**Eval Runs** page — the same per-BRD table and "Revision improvement"
aggregate section, rendered instead of a raw `output/eval/<run_id>/
summary.md` file, plus the per-agent score breakdown and a **Load** button
that jumps straight from an eval result into the full viewer pages.

**Say:** "Two independent evaluation methods: this structural harness over
8 labeled BRDs — 2 baselines, 6 built to stress a specific edge case — that
checks real pipeline behavior against each one's `expect` block; and the
Critic's own rubric scoring on every run. They're complementary, not
redundant — one checks 'did the system do the right thing,' the other
checks 'is the output any good.'"

---

## 7. Shipping it (6:45–8:00)

**[Operationalization & Monitoring, Documentation & Demo Quality]**

**Show:** `.github/workflows/deploy.yml` in the editor (scroll past the
`test` job's `needs: test` line), then a live GitHub Actions run going
green, then the deployed app's footer showing the matching `APP_BUILD`
tag.

**Say:**
- "Every push to `main` runs lint and the full test suite — 213 tests,
  stubbed LLM calls, no API key needed — before anything can build or
  deploy. `build-and-deploy` literally can't start until `test` passes."
- "Pre-release gates and success/failure criteria are written down, not
  just followed by habit — `TECHNICAL_DESIGN.md` §11, at five levels from
  a single artifact up to the live service."
- "In production: LangSmith traces every LLM call, Application Insights
  covers the infrastructure, and every agent logs its own stage
  entry/exit and revision decisions."

---

## 8. Close (8:00–8:30)

**Show:** the live app URL and the repo's README one more time.

**Say:** "That's ingestion through a grounded five-agent generation
pipeline, a Critic-driven revision loop with a real before/after metric,
guardrails that run before any model call, two evaluation methods, and a
CI pipeline that won't ship a broken change — all traceable back to the
code in this repo."

---

## How to record this

This is a script for a person to follow while recording a screen capture —
there's no video file or automation to run. The talking points are cues, not
a teleprompter: narrate them in your own words while performing the matching
"Show" action.

1. **Pick a screen recorder.** On Mac, QuickTime Player (File → New Screen
   Recording) is built in and free. OBS Studio is a good free alternative if
   you want picture-in-picture webcam or easier multi-source cuts.
2. **Pre-stage every segment's "Show" cue before hitting record** — the
   Streamlit UI open in one tab, a terminal ready with
   `python scripts/run_eval.py` in another, `TECHNICAL_DESIGN.md` §2's
   diagram open in a third, and so on. Don't navigate live while narrating;
   have each screen one click away.
3. **Record segment by segment.** Either one continuous take following the
   segment order below, or a separate short clip per segment stitched
   together afterward — the latter makes it easy to re-record just one
   segment without redoing the whole thing.
4. **Trim and stitch** in QuickTime's basic trim tool, iMovie, DaVinci
   Resolve (free tier), or OBS's built-in cuts, to land in the 7–10 minute
   target.
5. **Export as .mp4** and link it from the README (or wherever it needs to
   be submitted).

## Recording notes

- Keep each segment's **Show** action cued up in a separate browser
  tab/terminal pane beforehand — don't navigate live during narration.
- Segment 3's live run takes longer than 90 seconds in practice; either
  speed up the recording during the wait or cut to a pre-run result and
  narrate over it, being explicit on-screen that it's a completed run
  ("here's a run I completed earlier — same pipeline, same code").
- If total runtime creeps past 9:30, cut segment 5's second guardrail
  recap line first — it repeats information already shown in segment 4.
