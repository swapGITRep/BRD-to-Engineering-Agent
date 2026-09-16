# Architecture Patterns Catalogue

Reusable patterns and when to apply them. Cite the pattern name in key decisions.

## Batch file ingestion + reconciliation

For systems that ingest provider files on a schedule and match them against an
internal source of truth: land raw files immutably (object storage), normalize
into a canonical schema, run a deterministic match pass, then a fuzzy pass on
the residual, and queue exceptions for human review. Keep every decision
(auto-match, manual action) in an append-only audit store. Idempotent re-runs by
(provider, business_date) are mandatory.

## Walking skeleton

Build the thinnest end-to-end slice through every layer first (ingress →
service → datastore → output), deployed to a real environment, before adding
features. De-risks integration and deployment early.

## Synchronous vs event-driven integration

Prefer synchronous request/response when the caller needs an immediate answer
and the dependency is highly available. Prefer events when the producer should
not care about consumers, when work can be deferred, or when the consumer's
availability is lower. Do not introduce a broker for a single consumer that
needs a synchronous answer.

## Read replica / CQRS-lite

When a system must read from another team's database without writing to it, read
from a replica and treat it as eventually consistent. Never share a write path.

## Backend-for-frontend (BFF)

A portal or mobile client with bespoke aggregation needs benefits from a thin
BFF that composes downstream services and shapes responses for the UI, keeping
domain services generic.

## Strangler fig (legacy replacement)

Replace a legacy system incrementally: route new traffic to the new system
capability-by-capability behind a facade, migrating data per capability, until
the legacy system carries no traffic.
