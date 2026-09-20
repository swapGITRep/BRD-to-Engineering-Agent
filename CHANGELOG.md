# Changelog

Every entry follows the same shape: **Finding** — what was observed or wrong
before the change; **Change** — what was actually done; **Benefit** — why it
matters. Grouped by area, not by date, since the point is to show the
reasoning behind each refinement, not a timeline.

---

## Architecture & Orchestration

### Multi-agent pipeline built from a single-prompt gap
- **Finding:** No system existed to turn a BRD into a delivery package —
  the work of producing an engineering plan, schedule, architecture, PoC
  plan, and tech stack recommendation was manual and unstructured.
- **Change:** Built a 9-node LangGraph pipeline (ingest → orchestrator →
  5 specialists → critic → assemble) sharing one typed `BRDState` blackboard.
- **Benefit:** Each capability (parsing, generation, validation) is a
  separate, independently testable node instead of one large opaque prompt —
  a specialist can be swapped or a sixth added without touching the rest.

### Orchestration pattern left implicit
- **Finding:** Five distinct coordination mechanisms were in use (a fixed
  generation sequence, static routing, a bounded revision loop, a self-review
  step, shared state) but none was named or justified anywhere.
- **Change:** Documented and justified all five composed patterns —
  prompt-chaining, orchestrator-workers, evaluator-optimizer, reflection,
  blackboard — in `TECHNICAL_DESIGN.md` §3.1, each tied to the specific node
  it governs.
- **Benefit:** The design intent is now auditable rather than something a
  reviewer has to reverse-engineer from code; this was the single biggest
  point swing in the first rubric self-evaluation.

---

## Production Reliability (Azure)

### SQLite checkpoint locking under LangGraph's internal threads
- **Finding:** Thread-local SQLite connections raised "SQLite objects
  created in a thread can only be used in that same thread," because
  LangGraph's Pregel loop spawns its own internal worker threads even
  within a single `.invoke()` call.
- **Change:** Reverted to one shared connection (`check_same_thread=False`,
  `busy_timeout=30000`), and moved `CHECKPOINT_DB` off Azure Files onto local
  container disk.
- **Benefit:** Root-caused rather than patched — the deeper issue was SMB
  file-locking being unreliable for SQLite over Azure Files, not the
  threading model alone; fixing the storage location eliminated the
  recurring "database is locked" production errors outright.

### Bad image pushes reaching production silently
- **Finding:** A bad `docker push` produced `ImagePullBackOff` on the live
  Container App with no early signal.
- **Change:** Added explicit exit-code checks and `az acr repository
  show-tags` verification before every subsequent deploy step.
- **Benefit:** A broken push now fails the deploy step itself instead of
  surfacing later as a crashed production replica.

### ACR Tasks unavailable on this subscription tier
- **Finding:** `az acr build` failed with `TasksOperationsNotAllowed` on
  this free-tier subscription — twice, once for local deploys and again
  when the first CI workflow used the same command.
- **Change:** Switched to building on the actual machine/runner and pushing
  the image directly (`docker build` + `docker push` / `az acr login`),
  instead of relying on Azure-side cloud builds.
- **Benefit:** Deploys work within the subscription's real constraints
  instead of assuming a capability that isn't actually available.

### Stale `APP_BUILD` badge after image-only updates
- **Finding:** `az containerapp update --image ...` updates the running
  image but never touches other env vars — `APP_BUILD` (normally set once by
  the Bicep template) stayed frozen at the previous manual deploy's tag even
  after a new image went live, both locally and again the first time CI
  deployed.
- **Change:** Added `--set-env-vars "APP_BUILD=$IMAGE_TAG"` alongside every
  image update, in both the manual fix and the CI workflow.
- **Benefit:** The build badge shown in the UI can now be trusted as ground
  truth for what's actually running, not just what was last manually set.

### GitHub's new immutable OIDC subject-claim format
- **Finding:** Azure AD login failed with `AADSTS700213: No matching
  federated identity record` — the presented subject included owner/repo
  IDs (`repo:owner@id/repo@id:ref:...`) that didn't match the federated
  credential, because repos created after GitHub's mid-2026 rollout issue
  OIDC tokens in this new format by default.
- **Change:** Updated the federated credential's subject to the exact
  immutable-format string from the error, rather than the old plain-name
  format.
- **Benefit:** Diagnosed as a genuine platform behavior change instead of
  assuming a configuration mistake — the fix generalizes to any future repo
  created under the same rollout.

### Node 20 deprecation on GitHub Actions runners
- **Finding:** CI logs warned that `actions/checkout@v4` and
  `azure/login@v2` still targeted Node 20, which GitHub fully removes from
  runners on 2026-09-23.
- **Change:** Bumped to `actions/checkout@v5`, `azure/login@v3`, and later
  `actions/setup-python@v6` — each the first major version migrated to
  Node 24.
- **Benefit:** Fixed ahead of the hard removal date, not after the pipeline
  broke.

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

## CI/CD Pipeline

### No automated path from a merged change to production
- **Finding:** Every deploy was a manual sequence of `docker build` /
  `docker push` / `az containerapp update`, run by hand.
- **Change:** Built `.github/workflows/deploy.yml` from scratch — OIDC login
  to Azure (no stored secret), build-and-push on the runner, deploy, and
  `APP_BUILD` kept in sync with the deployed tag.
- **Benefit:** A merge to `main` now reaches production without a manual
  step, and the diagnosis trail for every issue hit while building it
  (OIDC subject format, missing RBAC role, ACR Tasks restriction, stale
  badge) is captured as fixes in this same changelog.

### Nothing stopped a broken change from deploying
- **Finding:** The workflow went straight from a push to `main` to building
  and deploying — `pytest` and `pyflakes` were only ever run manually before
  merging, so a change that skipped that manual step would still ship.
- **Change:** Added a `test` job (pyflakes + all 166 tests, no Azure
  credentials or API keys needed since every LLM/RAG call is stubbed) that
  `build-and-deploy` now depends on via `needs: test`.
- **Benefit:** Live-verified on the first push after merge — `test` ran and
  passed, `build-and-deploy` correctly waited for it — a broken change can
  no longer reach the Azure Container App.

---

## Operationalization & Documentation

### Success/failure criteria and pre-release gates existed only implicitly
- **Finding:** "Working" was only ever inferred from Critic verdicts and ad
  hoc manual checks before each deploy — never written down as explicit
  targets.
- **Change:** Added `TECHNICAL_DESIGN.md` §11: success/failure criteria at
  5 levels (artifact, run, eval set, release, live service) and an ordered
  pre-release gate checklist.
- **Benefit:** Moved Operationalization & Monitoring from the lowest-scoring
  rubric category (50%) to full marks — the criteria are now independently
  checkable, not just asserted.

### Documentation drifting out of sync with the code it describes
- **Finding:** Multiple docs accumulated stale claims as code changed
  underneath them — a test count frozen at 128 after it reached 166, a
  "no before/after report" limitation left in place after that exact gap
  was closed, and a pre-release-gates section still describing all gates as
  manual after one was wired into CI.
- **Change:** Corrected each one as it was found, including a full pass on
  `README.md` (a stale ASCII diagram replaced with the same Mermaid graph
  used in `TECHNICAL_DESIGN.md`, a Deployment section pointing at a
  stale pre-implementation design doc instead of the accurate
  `infra/DEPLOY.md`, and missing mentions of guardrails/schema validation).
- **Benefit:** Established a recurring discipline — when editing an area,
  check adjacent claims for staleness rather than assuming untouched text
  is still true.

### No demo script covering the system end to end
- **Finding:** The rubric asked for a demo video covering all flows; none
  existed, scripted or recorded.
- **Change:** Wrote `DEMO_SCRIPT.md` — 8 timed segments (~8:30 total)
  covering architecture, a live run, the Critic's revision loop, guardrails,
  the evaluation framework, and CI shipping — plus a "How to record this"
  section covering the actual recording mechanics after a reader asked how
  to "play" it.
- **Benefit:** The last concrete, unaddressed gap in the rubric now has a
  ready-to-follow, evidence-grounded script — recording it is the only step
  left.

---

## Domain Content

### No realistic, high-complexity BRD to stress-test the pipeline
- **Finding:** Existing sample BRDs were useful but comparatively narrow in
  regulatory/domain depth.
- **Change:** Authored `data/sample_brds/pharmacy_information_system_
  modernization_brd.md` — a monolith-to-microservices modernization for a
  US pharmacy/clinic/hospital system, covering real regulatory depth
  (NCPDP, DEA/PDMP, DSCSA, HIPAA) across 11 functional-requirement
  subsections.
- **Benefit:** A genuinely complex, realistic input to demonstrate the
  pipeline's handling of dense, multi-domain regulatory requirements — not
  a simplified toy example.
