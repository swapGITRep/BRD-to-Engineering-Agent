# SDLC Policy

## Delivery model

- Trunk-based development, short-lived branches, PRs reviewed by one other engineer.
- CI on every PR: lint, unit tests, dependency + image scan. Green required to merge.
- CD to a staging environment on merge to main; promotion to production is a
  deliberate, logged action with a rollback plan.

## Phase gates

- **Design gate** — architecture reviewed by EM + one principal before build.
- **Hardening gate** — NFR verification, threat-model review, load test, and a
  runbook exist before launch.
- **Launch gate** — on-call rota, dashboards, alerts, and backup/restore tested.

## Definition of done (per phase deliverable)

- Automated tests at the appropriate level; meaningful coverage of new logic.
- Observability: structured logs, key metrics, and traces for new paths.
- Documentation: updated runbook and architecture notes.
- No known criticals from security scans.

## Team & estimation norms

- Squads are 4–8 engineers plus an EM; one tech lead per squad.
- Plans state assumptions and are re-baselined at each phase boundary.
- Every BRD requirement is traceable to a phase deliverable and a test.
