# Engineering Plan Template

An engineering plan turns a BRD into an executable delivery approach. It is
reviewed by the Engineering Manager and shared with the sponsor.

## Phases

Break delivery into 3–6 phases. Each phase has:

- **Name and objective** — what capability exists at the end of the phase.
- **Entry criteria** — what must be true to start (dependencies, decisions, access).
- **Exit criteria** — demonstrable, testable outcomes that let the next phase start.
- **Key deliverables** — artifacts produced (schema, service, runbook, dashboard).

Typical shape: Discovery & Design → Foundation / Walking Skeleton → Core Build
→ Hardening (NFRs, security, perf) → Launch & Stabilization.

## Risk Register

List the top 5–10 risks. For each: description, likelihood (low/med/high),
impact (low/med/high), mitigation, owner, and the phase by which it must be
retired. Call out external dependencies and unknowns from the BRD explicitly.

## Milestones

Milestones are dated, externally meaningful checkpoints (e.g. "integration
environment live", "private beta", "GA"). Each milestone lists the phases and
deliverables it depends on. Keep milestones to one line each.

## Team Composition

Specify roles, headcount, and allocation percentage per phase. Note skills that
must be hired or borrowed. A plan that assumes more people than the BRD's
constraints allow is not actionable — reconcile against stated team size.

## Quality bar

- Every requirement in the BRD maps to at least one phase deliverable.
- Every "must" priority requirement is addressed no later than the Hardening phase.
- Assumptions and out-of-scope items from the BRD are restated in the plan.
