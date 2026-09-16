# Business Requirements Document — Core Platform Re-Platforming (Monolith to Services)

## 1. Overview

The 12-year-old Java monolith that runs order management, inventory,
pricing, customer accounts, and fulfillment routing has become the primary
blocker to shipping anything quickly: a single deploy train, a shared
database every team is afraid to touch, and an average of 3 production
incidents per month traced back to unrelated teams' changes colliding in the
same codebase. This BRD covers the phased decomposition of the monolith into
independently deployable services, migrating traffic incrementally with no
customer-visible downtime.

Sponsor: VP Engineering. Target: substantial completion within 4 quarters,
phased.

## 2. Goals

- Let each domain team (Orders, Inventory, Pricing, Accounts, Fulfillment)
  deploy independently, multiple times a day if they choose.
- Reduce cross-team production incidents caused by unrelated changes by 80%.
- Migrate all read and write traffic off the monolith's shared database with
  zero customer-visible downtime and no data loss.
- Preserve exact current behavior for every domain during migration — this is
  a re-platform, not a rewrite of business logic.

## 3. Functional Requirements

3.1 The system must extract Order Management into an independently deployable
    service, including order creation, modification, and cancellation.

3.2 The system must extract Inventory into an independently deployable
    service, including stock levels, reservations, and low-stock alerts.

3.3 The system must extract Pricing into an independently deployable service,
    including promotional pricing rules and tax calculation.

3.4 The system must extract Customer Accounts into an independently
    deployable service, including authentication, profile, and address book.

3.5 The system must extract Fulfillment Routing into an independently
    deployable service, including carrier selection and shipment tracking.

3.6 Each extracted service must own its own datastore; no service may read or
    write another service's tables directly.

3.7 The system must provide a strangler-fig routing layer that can direct a
    given request to either the monolith or the new service during migration,
    per domain, per percentage of traffic.

3.8 The system must support a dual-write or change-data-capture mechanism so
    the monolith's database and each new service's database stay consistent
    during the migration window for that domain.

3.9 The system must provide a reconciliation job that detects and reports any
    drift between the monolith and a migrated service's data during the
    transition period.

3.10 The system must support an emergency rollback of any single domain's
     traffic back to the monolith within 15 minutes, without a deploy.

3.11 Order Management must publish domain events (created, modified,
     cancelled) that Inventory and Fulfillment can consume, replacing today's
     in-process method calls.

3.12 Pricing must expose a versioned API so Orders can pin to a pricing
     calculation version during an in-flight checkout.

3.13 The system must provide a service catalog documenting every extracted
     service's owner, API contract, and current migration status.

3.14 Customer Accounts must remain the single source of truth for
     authentication throughout the migration; no other service may issue or
     validate credentials independently.

3.15 The system must support canary release of each new service to internal
     employees before any customer traffic is routed to it.

## 4. Non-Functional Requirements

4.1 No phase of the migration may cause customer-visible downtime, defined as
    any 5xx rate increase above the current monolith baseline.

4.2 Each extracted service must independently meet or beat the monolith's
    current p99 latency for the equivalent operation.

4.3 The reconciliation job in 3.9 must detect data drift within 15 minutes of
    it occurring.

4.4 All five extracted services must individually meet 99.9% availability
    once fully cut over, even though the monolith today runs at a single
    99.5% availability figure shared across all domains.

4.5 The strangler-fig routing layer itself must not become a new single point
    of failure; it must degrade to routing 100% of traffic to the monolith if
    it cannot reach a routing decision.

4.6 Every domain event in 3.11 must be delivered at-least-once with idempotent
    consumers; no order may be double-fulfilled due to a duplicated event.

4.7 The migration must be auditable: every traffic-percentage change and
    rollback must be logged with who initiated it and when.

## 5. Constraints and Assumptions

- The monolith cannot be feature-frozen during migration; the five domain
  teams continue shipping changes to it throughout, which the migration must
  account for.
- Current team: 5 domain squads of 4-6 engineers each, plus a 3-person
  platform team building the shared routing/CDC infrastructure — 28
  engineers total across the effort.
- The company is already committed to Azure; no new cloud provider.
- Two of the five domains (Pricing, Fulfillment) have undocumented business
  logic that will need to be reverse-engineered from the existing code during
  extraction.
- Existing monolith database is a single large PostgreSQL instance; per-domain
  ownership of tables is not currently enforced anywhere.

## 6. Out of Scope

- Any new customer-facing features during the migration — this is
  infrastructure work only.
- Changing the underlying business logic or pricing rules during extraction
  (behavior must be preserved exactly, bugs included, to be fixed later).
- Migrating the data warehouse / analytics pipeline, which reads from the
  monolith's replica today and is being handled by a separate initiative.

## 7. Success Metrics

- All five domains fully migrated off the monolith's shared database within
  4 quarters.
- Cross-team production incidents down 80% from the current monthly baseline.
- Zero customer-visible downtime incidents attributable to the migration
  itself across the whole program.
- Each domain team able to deploy independently at least once per day by the
  end of their migration phase.
