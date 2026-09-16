# NFR Catalogue

Default targets and the tactics that satisfy them. The Solution Architect maps
every BRD non_functional requirement to an entry here.

## Performance

- Interactive web pages: p95 time-to-interactive < 2.5 s on 4G mid-range mobile.
- Internal APIs: p95 < 300 ms, p99 < 800 ms under expected peak load.
- Batch jobs: state a wall-clock budget and the input volume it applies to.
- Tactics: pagination, caching (Redis), async offload, precomputation, indexing,
  right-sized worker parallelism. Verify with a load test in a prod-like env.

## Scalability

- State the peak concurrency and growth horizon (e.g. 3× in 18 months).
- Tactics: stateless services + horizontal scale, partitioned data, queue-based
  load levelling. Container Apps autoscale on concurrency or queue depth.

## Availability

- Standard internal target: 99.5% business hours. Customer-facing: 99.9%.
- Tactics: multi-replica, health probes, graceful degradation, retries with
  backoff, circuit breakers, dead-letter queues. No single points of failure on
  the critical path.

## Security

- See security_baseline.md. All NFRs referencing "secure", "encrypted",
  "access control", or a regulation map here plus to the baseline.

## Compliance (GDPR / audit / retention)

- Data export and deletion on request within 30 days.
- Retention periods are explicit per data class; enforce with lifecycle policies.
- Audit trails are append-only and cover who/what/when for sensitive actions.

## Usability / Accessibility

- Customer-facing UIs meet WCAG 2.1 AA.
- Tactics: design system components, keyboard navigation, screen-reader labels,
  automated axe checks in CI plus one manual audit before launch.
