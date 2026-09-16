# Proof-of-Concept Plan Template

A PoC exists to retire the largest technical risk or unknown before the team
commits to the full build. It is time-boxed and throwaway by default.

## PoC Goal

One sentence: the single question the PoC answers. Good goals are falsifiable
("can we match 500k settlement lines in under 30 minutes on one worker node?").

## Hypotheses to Validate

The specific assumptions being tested, each phrased so the result is a clear
yes/no or a number compared to a threshold.

## Scope

- **In scope** — the minimum slice that exercises the risk.
- **Out of scope** — everything deferred (auth, UI polish, full data volume,
  production hardening). Be explicit; PoCs fail by creeping toward production.

## Modules and Boundaries

List the modules built for the PoC. For each: its boundary, the interface it
presents, and whether collaborators are real or mocked. Modules should map 1:1
to components in the solution architecture so PoC learnings transfer.

## Success Criteria

Measurable criteria with a metric, a threshold, and a measurement method. Avoid
"works well" — use "p95 latency < 300 ms measured over a 10k-request run".

## Duration and Resources

Time-box (typically 1–3 weeks) and the people involved.

## Exit Decision Matrix

For each outcome (all criteria met / partially met / not met): the recommended
decision (proceed as planned / proceed with design change / re-scope / stop).
