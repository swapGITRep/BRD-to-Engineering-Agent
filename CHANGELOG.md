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

---

## Guardrails & Validation

### Only 5 of 7 agent outputs were schema-validated
- **Finding:** The Critic's own scoring JSON and the Reflection step's JSON
  both went through `extract_json` only, with no pydantic schema — so "all
  agents produce validated JSON" wasn't actually true.
- **Change:** Added `CriticDimensions` and `ReflectionReview` pydantic
  models, wired through the same `invoke_json()` retry path every specialist
  already used.
- **Benefit:** Closed a specific, named gap instead of a generic "add more
  validation" pass — this alone moved Structured Output Contracts from
  60% to 80% in the rubric self-evaluation.

### No enforcement that agents stay grounded in each other's real output
- **Finding:** Only one handoff (PoC → Architecture) had a real cross-agent
  input check; Schedule reading the Plan and Tech Stack reading Architecture
  didn't re-validate anything.
- **Change:** Added `_check_phase_alignment` (Schedule's phases must be real
  Engineering Plan phases) and `_check_radar_compliance` (Tech Stack options
  must never be tagged HOLD/RETIRE, enforced via a real `bind_tools` call to
  `check_tech_radar_status`).
- **Benefit:** Live-verified catching a real mistake — the model inventing
  "Contingency"/"All" as pseudo-phases that didn't exist upstream — proving
  the checks do real work, not just add ceremony.

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

---