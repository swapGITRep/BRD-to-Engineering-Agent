# Estimation Heuristics

Used by the Schedule Estimator. Estimates are ranges, not points.

## Baseline effort by component type (one senior engineer, first of its kind)

- New CRUD service with datastore + API + tests: 2–3 weeks.
- Batch pipeline stage (ingest / normalize / match): 1.5–2.5 weeks each.
- Third-party integration (well-documented REST API): 1–2 weeks.
- Third-party integration (file-based / poorly documented): 2–4 weeks.
- Web portal screen with forms + validation + state: 3–5 days each.
- SSO / OIDC integration with an existing IdP: 1–2 weeks.
- Reporting / dashboard surface: 1–2 weeks per coherent report.
- Audit trail + immutable store: 1 week on top of the feature it audits.

## Multipliers

- First integration with a given external system: ×1.5 (discovery tax).
- Team unfamiliar with the chosen technology: ×1.3–1.8.
- Hard NFR (sub-second latency, >99.9% availability, strict compliance): ×1.4 on
  the affected components for hardening.
- Shared/borrowed specialist (not full-time): ×1.3 on their tasks (context switching).

## Schedule construction

- Assume 3.5–4 productive days per engineer-week after meetings and support.
- Ramp-up: a new joiner contributes ~40% in week 1–2, ~70% weeks 3–4.
- Do not run more than ~60% of the team on the critical path; keep slack.
- Hardening + launch is 20–30% of total build effort; never zero.
- Add an explicit contingency line: 15% (low uncertainty) to 30% (high).

## Confidence bands

Report optimistic (all assumptions hold), likely (base estimate), and
pessimistic (discovery tax + one integration surprise) timelines.
